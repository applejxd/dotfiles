#!/usr/bin/env python3
"""away-shift skill の停止判定と実行記録を扱うガード。

無人実行では「止まるべきときに止まる」ことが最優先になる。停止条件の判定を
エージェントの記憶に任せると、サイクルが長引いたときに期限を跨いでしまう。
判定をこのスクリプトに寄せて、サイクルの先頭で必ず呼ぶ運用にする。

書き込み先はカレントディレクトリの ``.tmp/away-shift/`` の中に閉じる
(run_id の検査、シンボリックリンク・ハードリンクの拒否)。根は環境変数では変えられない。
例外は、専用 worktree を使う run の ``prepare`` が worktree の ``.tmp/away/`` へ書く子への指示だけ。

サブコマンド:

    init   実行ディレクトリと期限を作る。既存の run があれば再利用する。
           やり直すときは run_id を省略して新しい run を作る
    prepare  専用 worktree (枝つき) と run と子への指示 (brief-common.md) を一度に作る
    check  停止条件を判定する。継続なら exit 0、停止なら exit 3。
           停止済み (stopped が埋まっている) の run は確定状態で、状態を変えずに exit 3。
           worktree の run では WORKTREE・CHILD_TIMEOUT_MS・CHILD_CHECKPOINT_MS も出す
    audit  worktree の run の事後検査 (本体が無傷か・枝の成果・残りプロセス)。違反は exit 4
    log    サイクルの記録を追記する (--text / --note-file / 標準入力)。停止済みの run でも使える
    status 現在の run の要約を出す。停止済みの run でも使える
    sleep  <秒> (整数 1〜7200) だけ待つ。何も読み書きしない。pi の bg_run で再開を予約する用。
           --note <文> を付けると、待ち終えた最後に 1 行で出す (bg_run の完了通知に run_id と再開手順を載せる)
    snapshot  コードを変えて試す用に、リポジトリの作業コピーを work/src へ作る。
           隔離の保証ではない (SKILL.md の「コードを変えて検証する」)

exit code:

    0  継続してよい
    3  停止条件に当たった (stdout に理由)
    2  引数や状態の誤り・閉じ込めの違反
    4  audit が違反を見つけた (本体の HEAD が動いた・本体の作業ツリーが汚れた)

依存は標準ライブラリのみ。``uv run --no-project python`` で動く。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

STATE_NAME = "state.json"
# ユーザが手で置いて止めるためのファイル。run 側とリポジトリ直下の両方を見る
STOP_NAMES = ("STOP", "stop")

EXIT_CONTINUE = 0
EXIT_STOP = 3
EXIT_USAGE = 2
EXIT_AUDIT_VIOLATION = 4

# 子 (subagent) 1 回の実行時間の上限と、予備時間は check の --reserve-minutes (既定 15 分) を使う
CHILD_MAX_MINUTES = 30
CHILD_MIN_TIMEOUT_MS = 180000  # これ未満しか取れないなら、新しいサイクルを始めない
CHILD_CHECKPOINT_MAX_MS = 180000
GIT_TIMEOUT_SECONDS = 60
PREPARE_BRIEF_PLACEHOLDERS = ("worktree", "repo", "branch", "run_id", "deadline", "goal")  # goal は最後に置き換える
AUDIT_STATUS_MAX_LINES = 20
AUDIT_LOG_MAX_LINES = 50
AUDIT_COMMAND_MAX_CHARS = 80
KILL_WAIT_SECONDS = 2.0

# check の NEXT_WAKE_SECONDS は既定で 3600 まで (--max-wake-minutes 120 までは収まる)
SLEEP_MAX_SECONDS = 7200
NOTE_MAX_CHARS = 300  # sleep --note の出力の上限 (bg_run の通知に載せる 1 行)
WAKE_MAX_MINUTES = SLEEP_MAX_SECONDS // 60

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NOTE_MAX_BYTES = 64 * 1024
# Windows などには O_NOFOLLOW が無い。その場合は事前の lstat の検査だけになる
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

# "07:30" / "2026-09-10 07:30" / "8h" / "90m" を受け付ける
_CLOCK_RE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})$")
_DATETIME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<h>\d{1,2}):(?P<m>\d{2})$")
_DURATION_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[hm])$")


class Refused(Exception):
    """閉じ込めや引数の違反。main が stderr に出して終了コード 2 にする。"""


def now() -> dt.datetime:
    return dt.datetime.now()


def parse_deadline(value: str, base: dt.datetime) -> dt.datetime:
    """期限の指定を絶対時刻へ直す。

    ``07:30`` のような時刻だけの指定は「次にその時刻になる瞬間」と解釈する。
    夜に離席して翌朝で止める、昼に離席して夕方で止める、どちらも同じ書き方で
    済ませたいので、過ぎている時刻は翌日とみなす。
    """
    text = value.strip()

    match = _DATETIME_RE.match(text)
    if match:
        date = dt.date.fromisoformat(match.group("date"))
        return dt.datetime.combine(date, dt.time(int(match.group("h")), int(match.group("m"))))

    match = _CLOCK_RE.match(text)
    if match:
        target = dt.time(int(match.group("h")), int(match.group("m")))
        candidate = dt.datetime.combine(base.date(), target)
        if candidate <= base:
            candidate += dt.timedelta(days=1)
        return candidate

    match = _DURATION_RE.match(text)
    if match:
        amount = float(match.group("value"))
        delta = (
            dt.timedelta(hours=amount)
            if match.group("unit") == "h"
            else dt.timedelta(minutes=amount)
        )
        return base + delta

    raise ValueError(
        f"期限の書式が読めません: {value!r} (HH:MM / YYYY-MM-DD HH:MM / 8h / 90m のいずれか)"
    )


# ─── 閉じ込め ──────────────────────────────────────────────────────────────


def run_root() -> Path:
    """根。いまのディレクトリの `.tmp/away-shift`。環境変数では変えられない。"""
    return Path.cwd() / ".tmp" / "away-shift"


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
        raise Refused(
            f"run_id が不正です: {run_id!r} "
            "(英数字で始まり、英数字と . _ - だけの 64 文字以内。.. は不可)"
        )
    return run_id


def confine(path: Path) -> Path:
    """path が根の中で、途中にリンクが無いとき、解決したパスを返す。違えば Refused。

    - 根とその親 (.tmp) がシンボリックリンクなら拒否する
    - 根から path までの既存の各要素がシンボリックリンクなら拒否する
    - 既存の通常ファイルのハードリンク (st_nlink > 1) を拒否する
    - 解決したパスが根の外なら拒否する
    """
    root = run_root()
    for part in (root.parent, root):
        if part.is_symlink():
            raise Refused(f"{part} がシンボリックリンク。根はリンクにしない")
    resolved_root = root.resolve()
    target = Path(path)
    resolved = target.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise Refused(f"{resolved} は {resolved_root} の外")
    try:
        rel = target.relative_to(root)
    except ValueError:
        raise Refused(f"{target} は {root} の外") from None
    current = root
    for name in rel.parts:
        current = current / name
        if current.is_symlink():
            raise Refused(f"{current} がシンボリックリンク")
    if current.exists() and stat.S_ISREG(current.lstat().st_mode) and current.lstat().st_nlink > 1:
        raise Refused(f"{current} がハードリンク")
    return resolved


def run_dir(run_id: str) -> Path:
    return run_root() / validate_run_id(run_id)


def state_path(run_id: str) -> Path:
    return run_dir(run_id) / STATE_NAME


def make_dir(path: Path) -> None:
    confine(path)
    path.mkdir(parents=True, exist_ok=True)
    confine(path)


def append_text(path: Path, text: str) -> None:
    confine(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW, 0o666)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(text)


def read_bytes(path: Path, limit: int | None = None) -> bytes:
    fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read() if limit is None else f.read(limit)


def load_state(run_id: str) -> dict:
    path = state_path(run_id)
    confine(path)
    if not path.exists():
        raise FileNotFoundError(f"run が見つかりません: {path} (先に init を実行)")
    return json.loads(read_bytes(path).decode("utf-8"))


def save_state(run_id: str, state: dict) -> None:
    """run ディレクトリの中の一時ファイルへ書いてから置き換える。"""
    path = state_path(run_id)
    make_dir(path.parent)
    confine(path)
    tmp = path.parent / f".{STATE_NAME}.tmp"
    confine(tmp)
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def find_stop_file(run_id: str) -> Path | None:
    """STOP ファイルを探す。run 配下とリポジトリ直下の両方を見る。

    リポジトリ直下も見るのは、ユーザが run_id を知らなくても
    ``touch STOP`` だけで止められるようにするため。
    """
    candidates = [run_dir(run_id) / name for name in STOP_NAMES]
    candidates += [Path(name) for name in STOP_NAMES]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def new_run_id(base: dt.datetime) -> str:
    return base.strftime("%Y%m%d-%H%M%S")


def parse_future_deadline(text: str, base: dt.datetime) -> dt.datetime:
    """期限を読み、現在より後であることも確かめる。違えば ValueError (メッセージは利用者向け)。"""
    deadline = parse_deadline(text, base)
    if deadline <= base:
        raise ValueError(f"期限が現在時刻より前です: {deadline.isoformat()}")
    return deadline


def create_run(
    run_id: str,
    goal: str,
    deadline: dt.datetime,
    max_cycles: int,
    base: dt.datetime,
    extra: dict | None = None,
) -> None:
    """run の state.json と cycles/・work/ を作る。init と prepare で共有する。"""
    state = {
        "run_id": run_id,
        "goal": goal,
        "started_at": base.isoformat(timespec="seconds"),
        "deadline": deadline.isoformat(timespec="seconds"),
        "max_cycles": max_cycles,
        "cycle": 0,
        "stopped": None,
        **(extra or {}),
    }
    save_state(run_id, state)
    make_dir(run_dir(run_id) / "cycles")
    # 試行錯誤の作業場。ここだけは消してよい。cycles/ と state.json、
    # report.md は証跡なので消さない
    make_dir(run_dir(run_id) / "work")


def cmd_init(args: argparse.Namespace) -> int:
    base = now()
    run_id = args.run_id if args.run_id is not None else new_run_id(base)
    path = state_path(validate_run_id(run_id))
    confine(path)
    if path.exists():
        state = load_state(run_id)
        print(f"既存の run を再利用します: {run_id}")
        print(f"  期限: {state['deadline']}")
        print(f"  目標: {state['goal']}")
        return EXIT_CONTINUE

    try:
        deadline = parse_future_deadline(args.deadline, base)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    create_run(run_id, args.goal, deadline, args.max_cycles, base)
    print(f"run_id: {run_id}")
    print(f"作業ディレクトリ: {run_dir(run_id) / 'work'}")
    print(f"証跡ディレクトリ: {run_dir(run_id)} (消さない)")
    print(f"期限: {deadline.isoformat(timespec='seconds')}")
    print(f"最大サイクル: {args.max_cycles}")
    print(f"停止するには: touch {run_dir(run_id) / 'STOP'}  または  touch STOP")
    return EXIT_CONTINUE


# ─── prepare (専用 worktree) ───────────────────────────────────────────────


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """git を実行する (リスト形式・タイムアウトつき)。git が無い・時間切れは Refused。"""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"git を実行できません: {type(exc).__name__}: {exc}") from None


def git_text(args: list[str]) -> str:
    """git の標準出力を返す。失敗したら Refused。"""
    result = run_git(args)
    if result.returncode != 0:
        raise Refused(f"git {' '.join(args)} が失敗: {result.stderr.strip()[:200]}")
    return result.stdout


def child_brief_path() -> Path:
    """子への指示のひな形。ソースの配置と配備先の両方で scripts/ の隣の references/ にある。"""
    return Path(__file__).resolve().parent.parent / "references" / "child-brief.md"


def render_child_brief(template: str, values: dict[str, str]) -> str:
    """先頭の HTML コメントとその直後の空行を除き、{名前} を置き換える。

    goal は利用者の文字列なので最後に置き換える (他の名前の置き換えに巻き込まない)。
    """
    if template.startswith("<!--"):
        end = template.find("-->")
        if end != -1:
            template = template[end + len("-->"):].lstrip("\r\n")
    for name in PREPARE_BRIEF_PLACEHOLDERS:
        template = template.replace("{" + name + "}", values[name])
    return template


def cmd_prepare(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    top = run_git(["rev-parse", "--show-toplevel"])
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != cwd:
        print(f"git リポジトリの根で実行してください (いま: {cwd})", file=sys.stderr)
        return EXIT_USAGE

    base_time = now()
    try:
        deadline = parse_future_deadline(args.deadline, base_time)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    run_id = new_run_id(base_time)
    branch = f"feature/away-{run_id}"
    worktree = cwd / ".tmp" / "worktrees" / f"away-{run_id}"
    base_sha = git_text(["rev-parse", "HEAD"]).strip()
    dirty = git_text(["status", "--short"]).strip()

    added = run_git(["worktree", "add", "-b", branch, str(worktree), "HEAD"])
    if added.returncode != 0:
        print(f"worktree を作れませんでした (run は作っていません): {added.stderr.strip()}", file=sys.stderr)
        return EXIT_USAGE

    create_run(
        run_id,
        args.goal,
        deadline,
        args.max_cycles,
        base_time,
        extra={"worktree": str(worktree), "branch": branch, "base": base_sha, "repo": str(cwd)},
    )

    template_path = child_brief_path()
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"子への指示のひな形を読めません: {template_path} ({exc})\n"
            f"作った worktree は消していません: {worktree} (枝 {branch}、run {run_id})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    brief = render_child_brief(
        template,
        {
            "worktree": str(worktree),
            "repo": str(cwd),
            "branch": branch,
            "goal": args.goal,
            "run_id": run_id,
            "deadline": deadline.isoformat(timespec="seconds"),
        },
    )
    handoff = worktree / ".tmp" / "away"
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff / "brief-common.md").write_text(brief, encoding="utf-8")

    print(f"run_id: {run_id}")
    print(f"worktree: {worktree}")
    print(f"branch: {branch}")
    print(f"base: {base_sha[:8]}")
    print(f"期限: {deadline.isoformat(timespec='seconds')}")
    print(f"引き継ぎ: {handoff}/")
    if dirty:
        print("警告: 本体の作業ツリーに未コミットの変更がある。worktree には含まれない")
    print(f"次: check {run_id} で CHILD_TIMEOUT_MS を得て、cwd を worktree にした子を起動する")
    print("  依頼文には「brief-common.md と cycle-<N>-task.md を読む」とだけ書く")
    print(f"  終わったら audit {run_id} --kill --write で本体が無傷かと残りプロセスを確かめる")
    return EXIT_CONTINUE


def cmd_check(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    if state.get("stopped"):
        print(f"STOP: 停止済みの run です ({state['stopped']})")
        return EXIT_STOP

    current = now()
    deadline = dt.datetime.fromisoformat(state["deadline"])

    stop_file = find_stop_file(args.run_id)
    if stop_file is not None:
        state["stopped"] = f"stop-file:{stop_file}"
        save_state(args.run_id, state)
        print(f"STOP: 停止ファイルがあります ({stop_file})")
        return EXIT_STOP

    if current >= deadline:
        state["stopped"] = "deadline"
        save_state(args.run_id, state)
        print(f"STOP: 期限に達しました ({state['deadline']})")
        return EXIT_STOP

    remaining = deadline - current
    remaining_min = int(remaining.total_seconds() // 60)
    if remaining_min < args.reserve_minutes:
        state["stopped"] = "reserve"
        save_state(args.run_id, state)
        print(
            f"STOP: 残り {remaining_min} 分で、レポート用の予備 "
            f"{args.reserve_minutes} 分を下回りました"
        )
        return EXIT_STOP

    if state["cycle"] >= state["max_cycles"]:
        state["stopped"] = "max-cycles"
        save_state(args.run_id, state)
        print(f"STOP: 最大サイクル数に達しました ({state['max_cycles']})")
        return EXIT_STOP

    child_timeout_ms = min(CHILD_MAX_MINUTES * 60000, (remaining_min - args.reserve_minutes) * 60000)
    if "worktree" in state and child_timeout_ms < CHILD_MIN_TIMEOUT_MS:
        state["stopped"] = "child-time"
        save_state(args.run_id, state)
        print(
            f"STOP: 子に割り当てられる時間が {child_timeout_ms // 1000} 秒で、"
            f"{CHILD_MIN_TIMEOUT_MS // 1000} 秒に届かない (残り {remaining_min} 分、予備 {args.reserve_minutes} 分)"
        )
        return EXIT_STOP

    state["cycle"] += 1
    save_state(args.run_id, state)
    remaining_cycles = max(1, state["max_cycles"] - state["cycle"])
    # 次のサイクルまでどれだけ空けるか。無人実行では 1 サイクルが数分で
    # 終わってしまい、離席時間を使い切れずに手が空く。残り時間を残り
    # サイクル数で割って、復帰時刻まで均等に配分する
    usable_min = max(0, remaining_min - args.reserve_minutes)
    pace_min = min(usable_min // remaining_cycles, args.max_wake_minutes)
    print(f"CONTINUE: cycle {state['cycle']}/{state['max_cycles']}")
    print(f"  残り: {remaining_min} 分 (期限 {state['deadline']})")
    print(f"  目標: {state['goal']}")
    print(f"NEXT_WAKE_SECONDS: {max(60, pace_min * 60)}")
    if "worktree" in state:
        print(f"WORKTREE: {state['worktree']}")
        print(f"CHILD_TIMEOUT_MS: {child_timeout_ms}")
        print(f"CHILD_CHECKPOINT_MS: {min(CHILD_CHECKPOINT_MAX_MS, child_timeout_ms // 3)}")
    return EXIT_CONTINUE


def read_note(run_id: str, name: str) -> str:
    """<run ディレクトリ>/work/<name> の通常ファイルを UTF-8 で読む。"""
    if (
        not name
        or "/" in name
        or "\\" in name
        or "\0" in name
        or name.startswith(".")
        or ":" in name
    ):
        raise Refused(f"--note-file の名前が不正です: {name!r} (work/ 直下の 1 要素。先頭 . 不可)")
    path = run_dir(run_id) / "work" / name
    confine(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise Refused(f"--note-file が見つかりません: {path}") from None
    if not stat.S_ISREG(info.st_mode):
        raise Refused(f"{path} は通常ファイルではありません")
    if info.st_nlink > 1:
        raise Refused(f"{path} がハードリンク")
    if info.st_size > NOTE_MAX_BYTES:
        raise Refused(f"{path} が {NOTE_MAX_BYTES} バイトを超える")
    try:
        data = read_bytes(path, NOTE_MAX_BYTES + 1)
        if len(data) > NOTE_MAX_BYTES:
            raise Refused(f"{path} が {NOTE_MAX_BYTES} バイトを超える")
        return data.decode("utf-8")
    except OSError as exc:
        raise Refused(f"{path} を読めません: {exc}") from None
    except UnicodeDecodeError:
        raise Refused(f"{path} が UTF-8 ではありません") from None


def cmd_log(args: argparse.Namespace) -> int:
    if args.text is not None and args.note_file is not None:
        raise Refused("--text と --note-file は同時に指定できません")
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    cycle = args.cycle if args.cycle is not None else state["cycle"]
    if cycle < 0:
        raise Refused(f"--cycle が負です: {cycle}")
    path = run_dir(args.run_id) / "cycles" / f"cycle-{cycle:03d}.md"
    if args.note_file is not None:
        body = read_note(args.run_id, args.note_file)
    elif args.text is not None:
        body = args.text
    else:
        body = sys.stdin.read()
    make_dir(path.parent)
    stamp = now().isoformat(timespec="seconds")
    append_text(path, f"\n## {stamp}\n\n{body.rstrip()}\n")
    print(f"追記しました: {path}")
    return EXIT_CONTINUE


def cmd_status(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    deadline = dt.datetime.fromisoformat(state["deadline"])
    remaining = int((deadline - now()).total_seconds() // 60)
    print(json.dumps({**state, "remaining_minutes": remaining}, ensure_ascii=False, indent=2))
    return EXIT_CONTINUE


def cmd_sleep(args: argparse.Namespace) -> int:
    time.sleep(args.seconds)
    if args.note:
        # bg_run の完了通知は、起動したコマンドと出力の最後の数行を運ぶ。再開時にコンテクストが残らないので、
        # run_id と「手順 3 から再開する」旨をここに載せる (1 行・上限つき。制御文字は空白にする)
        print(" ".join(args.note.split())[:NOTE_MAX_CHARS])
    return EXIT_CONTINUE


# ─── snapshot ──────────────────────────────────────────────────────────────

# 秘密になりうるものは、作業コピーへ持ち込まない。持ち込むと read の deny を迂回して読めてしまうので、
# 正本は ``[file] read_deny_globs``（判定器と同じ command_policy 経由。ここに複製を持たない）。読めないときは拒否する
SNAPSHOT_DEFAULT_MAX_MB = 200
SNAPSHOT_DEFAULT_MAX_FILES = 20000


def _agents_config_dir() -> Path:
    override = os.environ.get("AGENTS_CONFIG_DIR")
    if override:
        return Path(override)
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "agents"


def _load_read_deny():
    """(判定関数, ) を返す: パスを渡すと当たった read_deny の glob を返し、無ければ None。

    一覧が読めない・空のときは Refused (fail closed)。
    """
    import importlib.util

    agents = _agents_config_dir()
    module_path = agents / "command_policy.py"
    common = agents / "common.toml"
    if not module_path.is_file() or not common.is_file():
        raise Refused(f"保護対象の一覧が読めません: {agents} (command_policy.py / common.toml)")
    try:
        spec = importlib.util.spec_from_file_location("_away_command_policy", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        globs = module.load_file_globs("read_deny_globs", str(common))
        exceptions = module.load_read_deny_exceptions(str(common))
    except Exception as exc:
        raise Refused(f"保護対象の一覧を読めません: {type(exc).__name__}: {exc}") from None
    if not globs:
        raise Refused("read_deny_globs が空です (保護対象を確かめられない)")
    return lambda candidate: module.matches_read_deny(candidate, globs, exceptions)


def _git(args: list[str]) -> bytes:
    """読み取り専用の git。fsmonitor を切り、任意のロックを取らない。"""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise Refused(
            f"git {' '.join(args)} が失敗: {result.stderr.decode('utf-8', 'replace')[:200]}"
        )
    return result.stdout


def cmd_snapshot(args: argparse.Namespace) -> int:
    """追跡と、ignored でない未追跡のファイルを <run>/work/src へコピーする。

    コピー先は Git リポジトリではない (.git を持ち込まない)。コピー内で git を使うと
    親をたどって本体の .git を見るので、差分は ``git diff --no-index`` で取る。
    ignored の生成物・ローカル設定・シンボリックリンク・サブモジュール・秘密の疑いは
    コピーせず、何を除いたかを出す (レポートの「入力に含まれないもの」に書く)。
    """
    try:
        load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    cwd = Path.cwd().resolve()
    top = Path(_git(["rev-parse", "--show-toplevel"]).decode("utf-8").strip()).resolve()
    if top != cwd:
        raise Refused(f"リポジトリの根で実行してください (根: {top}、いま: {cwd})")
    head = _git(["rev-parse", "HEAD"]).decode("utf-8").strip()
    protected = _load_read_deny()

    dest = run_dir(args.run_id) / "work" / "src"
    confine(dest)
    if dest.exists():
        if not args.replace:
            raise Refused(f"{dest} が既にあります (作り直すなら --replace。work/ の中だけを消す)")
        shutil.rmtree(dest)

    listed = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    rels = sorted({p for p in listed.decode("utf-8", "surrogateescape").split("\0") if p})

    skipped: dict[str, list[str]] = {
        "self": [], "protected": [], "symlink": [], "not-regular": [], "missing": [],
        "outside": [], "too-large": [],
    }  # fmt: skip
    todo: list[tuple[str, int]] = []
    total = 0
    per_file_max = args.max_file_mb * 1024 * 1024
    for rel in rels:
        if rel in (".tmp", ".git") or rel.startswith((".tmp/", ".git/")):
            skipped["self"].append(rel)
            continue
        if protected(rel) or protected(str(cwd / rel)):
            skipped["protected"].append(rel)
            continue
        src = cwd / rel
        try:
            info = src.lstat()
        except OSError:
            skipped["missing"].append(rel)
            continue
        if stat.S_ISLNK(info.st_mode):
            skipped["symlink"].append(rel)
            continue
        if not stat.S_ISREG(info.st_mode):
            skipped["not-regular"].append(rel)  # サブモジュールの gitlink など
            continue
        if cwd not in Path(os.path.realpath(src)).parents:
            skipped["outside"].append(rel)  # 途中がリンクでリポジトリの外を指す
            continue
        if info.st_size > per_file_max:
            skipped["too-large"].append(rel)
            continue
        todo.append((rel, info.st_size))
        total += info.st_size

    if len(todo) > args.max_files:
        raise Refused(f"ファイル数が上限を超える: {len(todo)} > {args.max_files} (--max-files)")
    if total > args.max_mb * 1024 * 1024:
        raise Refused(
            f"合計容量が上限を超える: {total // (1024 * 1024)} MB > {args.max_mb} MB (--max-mb)"
        )

    make_dir(dest)
    for rel, _size in todo:
        target = dest / rel
        make_dir(target.parent)
        confine(target)
        shutil.copyfile(cwd / rel, target, follow_symlinks=False)
        shutil.copymode(cwd / rel, target, follow_symlinks=False)

    print(f"作業コピー: {dest}")
    print(f"  起点: HEAD {head[:12]} + 未コミットの変更・未追跡 (ignored を除く)")
    print(f"  コピー: {len(todo)} ファイル、{total // 1024} KiB")
    for reason, items in skipped.items():
        if items:
            shown = ", ".join(items[:5]) + (" ほか" if len(items) > 5 else "")
            print(f"  除外 ({reason}): {len(items)} 件 {shown}")
    print("  ignored の生成物・ローカル設定は含まれない (必要な入力が欠けないかを確かめる)")
    print("注意: これは作業用のコピーで、隔離ではない。")
    print("  - コピーは Git リポジトリではない。コピーの中で git を使わない (本体の .git を見る)")
    print(f"  - 差分は `git diff --no-index -- <本体のパス> {dest}/<同じパス>`")
    print("  - 実行は cwd をコピーにし、本体のパスを絶対パスで渡さない")
    return EXIT_CONTINUE


# ─── audit (worktree の run の事後検査) ────────────────────────────────────


def _short(sha: str) -> str:
    return sha[:8]


def _ancestor_pids() -> set[int]:
    """自分自身と、親をたどった祖先の pid。audit --kill が自分の親を止めないための除外。"""
    pids = {os.getpid()}
    pid = os.getppid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        pid = _parent_pid(pid)
    return pids


def _parent_pid(pid: int) -> int:
    try:
        data = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    # コマンド名に空白や ) が入りうるので、最後の ) の後ろを数える (状態, 親 pid, ...)
    fields = data.rsplit(")", 1)[-1].split()
    return int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0


def _cwd_is_inside(cwd: str, worktree: str) -> bool:
    return cwd == worktree or cwd.startswith(worktree + os.sep)


def find_worktree_processes(worktree: str) -> list[tuple[int, str]]:
    """cwd が worktree の中にあるプロセス (pid, コマンドの先頭) を返す。自分と祖先は除く。"""
    resolved = os.path.realpath(worktree)
    excluded = _ancestor_pids()
    found = []
    for entry in sorted(Path("/proc").iterdir(), key=lambda p: p.name):
        if not entry.name.isdigit() or int(entry.name) in excluded:
            continue
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            continue  # 他ユーザのプロセス・終了済みのプロセス
        if not _cwd_is_inside(cwd, resolved):
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            command = ""
        found.append((int(entry.name), (command or "(コマンド不明)")[:AUDIT_COMMAND_MAX_CHARS]))
    return found


def _kill_worktree_processes(worktree: str, found: list[tuple[int, str]]) -> tuple[list[int], list[int]]:
    """SIGTERM → 2 秒待ち → 残りに SIGKILL。(止めた pid, 止まらなかった pid) を返す。"""

    def send(sig: int, pids: list[int]) -> None:
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)

    def alive() -> list[int]:
        wanted = {pid for pid, _ in found}
        return [pid for pid, _ in find_worktree_processes(worktree) if pid in wanted]

    send(signal.SIGTERM, [pid for pid, _ in found])
    deadline = time.monotonic() + KILL_WAIT_SECONDS
    remaining = alive()
    while remaining and time.monotonic() < deadline:
        time.sleep(0.1)
        remaining = alive()
    if remaining:
        send(signal.SIGKILL, remaining)
        time.sleep(0.2)
        remaining = alive()
    survivors = set(remaining)
    stopped = [pid for pid, _ in found if pid not in survivors]
    return stopped, sorted(survivors)


def write_audit_report(run_id: str, text: str) -> Path:
    """audit の結果を <run>/audit.md へ書く。work/ の外に書く唯一のファイル。"""
    path = run_dir(run_id) / "audit.md"
    confine(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def cmd_audit(args: argparse.Namespace) -> int:
    try:
        state = load_state(args.run_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if "worktree" not in state:
        print(f"worktree を使う run ではありません: {args.run_id} (prepare で作った run だけ audit できる)", file=sys.stderr)
        return EXIT_USAGE

    repo, worktree, branch, base = state["repo"], state["worktree"], state["branch"], state["base"]
    lines: list[str] = []
    violations: list[str] = []

    head = git_text(["-C", repo, "rev-parse", "HEAD"]).strip()
    same = head == base
    lines.append(f"本体 HEAD: {_short(head)} (開始時 {_short(base)}) {'同じ' if same else '違う'}")
    if not same:
        violations.append("本体の HEAD が開始時から動いている")

    main_status = git_text(["-C", repo, "status", "--short"]).splitlines()
    lines.append(f"本体 git status: {len(main_status)} 件")
    lines += [f"  {row}" for row in main_status[:AUDIT_STATUS_MAX_LINES]]
    if main_status:
        violations.append("本体の作業ツリーに変更がある")

    commits = git_text(["-C", repo, "log", "--oneline", f"{base}..{branch}"]).splitlines()
    shortstat = git_text(["-C", repo, "diff", "--shortstat", f"{base}..{branch}"]).strip()
    lines.append(f"枝: {branch}")
    lines.append(f"コミット: {len(commits)} 件")
    lines += [f"  {row}" for row in commits[:AUDIT_LOG_MAX_LINES]]
    lines.append(f"差分: {shortstat or 'なし'}")

    wt_status = git_text(["-C", worktree, "status", "--short"]).splitlines()
    lines.append(f"worktree の未コミット: {len(wt_status)} 件 (違反ではない)")
    lines += [f"  {row}" for row in wt_status[:AUDIT_STATUS_MAX_LINES]]

    if not os.path.isdir("/proc/self"):
        lines.append("残っているプロセス: プロセスの確認は Linux だけ (この環境では飛ばした)")
    else:
        found = find_worktree_processes(worktree)
        lines.append(f"残っているプロセス: {len(found)} 件 (cwd が worktree の中)")
        lines += [f"  {pid} {command}" for pid, command in found]
        if found and args.kill:
            stopped, survivors = _kill_worktree_processes(worktree, found)
            lines.append(f"  止めた pid: {' '.join(map(str, stopped)) or 'なし'}")
            lines.append(f"  止まらなかった pid: {' '.join(map(str, survivors)) or 'なし'}")

    lines.append("違反: " + ("; ".join(violations) if violations else "なし"))
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.write:
        path = write_audit_report(args.run_id, f"# audit {args.run_id}\n\n" + text)
        print(f"書き出しました: {path}")
    return EXIT_AUDIT_VIOLATION if violations else EXIT_CONTINUE


def _sleep_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"整数の秒数ではありません: {value!r}") from None
    if not 1 <= seconds <= SLEEP_MAX_SECONDS:
        raise argparse.ArgumentTypeError(f"秒数は 1〜{SLEEP_MAX_SECONDS}: {seconds}")
    return seconds


def _wake_minutes(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"整数の分ではありません: {value!r}") from None
    if not 1 <= minutes <= WAKE_MAX_MINUTES:
        raise argparse.ArgumentTypeError(f"分は 1〜{WAKE_MAX_MINUTES}: {minutes}")
    return minutes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="run を作る")
    p_init.add_argument("--goal", required=True, help="達成したいこと (1 行)")
    p_init.add_argument(
        "--deadline",
        required=True,
        help="停止時刻。HH:MM / YYYY-MM-DD HH:MM / 8h / 90m",
    )
    p_init.add_argument("--run-id", help="省略時は開始時刻から作る")
    p_init.add_argument("--max-cycles", type=int, default=20)
    p_init.set_defaults(func=cmd_init)

    p_prepare = sub.add_parser("prepare", help="専用 worktree と run と子への指示を作る")
    p_prepare.add_argument("--goal", required=True, help="達成したいこと (1 行)")
    p_prepare.add_argument("--deadline", required=True, help="停止時刻。HH:MM / YYYY-MM-DD HH:MM / 8h / 90m")
    p_prepare.add_argument("--max-cycles", type=int, default=20)
    p_prepare.set_defaults(func=cmd_prepare)

    p_check = sub.add_parser("check", help="停止条件を判定する (継続 0 / 停止 3)")
    p_check.add_argument("run_id")
    p_check.add_argument(
        "--reserve-minutes",
        type=int,
        default=15,
        help="レポート作成用に残す時間。既定 15 分",
    )
    p_check.add_argument(
        "--max-wake-minutes",
        type=_wake_minutes,
        default=60,
        help=("NEXT_WAKE_SECONDS の上限 (分)。manage_schedule の wakeup は 1 時間で頭打ちになる"),
    )
    p_check.set_defaults(func=cmd_check)

    p_audit = sub.add_parser("audit", help="worktree の run を事後検査する (違反 4)")
    p_audit.add_argument("run_id")
    p_audit.add_argument("--kill", action="store_true", help="cwd が worktree の中のプロセスを止める")
    p_audit.add_argument("--write", action="store_true", help="結果を <run>/audit.md へ書く")
    p_audit.set_defaults(func=cmd_audit)

    p_log = sub.add_parser("log", help="サイクルの記録を追記する")
    p_log.add_argument("run_id")
    p_log.add_argument("--cycle", type=int)
    p_log.add_argument("--text", help="省略時は標準入力から読む")
    p_log.add_argument(
        "--note-file", help="<run>/work/ 直下のファイル名。--text と排他 (64 KiB 以内)"
    )
    p_log.set_defaults(func=cmd_log)

    p_status = sub.add_parser("status", help="現在の状態を出す")
    p_status.add_argument("run_id")
    p_status.set_defaults(func=cmd_status)

    p_sleep = sub.add_parser("sleep", help="上限つきで待つ (1〜7200 秒)")
    p_sleep.add_argument("seconds", type=_sleep_seconds)
    p_sleep.add_argument("--note", default="", help="待ち終えたあとに出す 1 行 (run_id と再開手順)")
    p_sleep.set_defaults(func=cmd_sleep)

    p_snap = sub.add_parser("snapshot", help="作業用のコピーを work/src に作る (隔離ではない)")
    p_snap.add_argument("run_id")
    p_snap.add_argument("--replace", action="store_true", help="既存の work/src を消して作り直す")
    p_snap.add_argument(
        "--max-mb", type=int, default=SNAPSHOT_DEFAULT_MAX_MB, help="合計容量の上限"
    )
    p_snap.add_argument(
        "--max-file-mb", type=int, default=10, help="1 ファイルの上限 (超えるものは除外)"
    )
    p_snap.add_argument("--max-files", type=int, default=SNAPSHOT_DEFAULT_MAX_FILES)
    p_snap.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "run_id", None) is not None:
            validate_run_id(args.run_id)
        return args.func(args)
    except Refused as exc:
        print(f"拒否: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
