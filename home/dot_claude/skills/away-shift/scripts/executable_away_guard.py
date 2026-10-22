#!/usr/bin/env python3
"""away-shift skill の停止判定と実行記録を扱うガード。

無人実行では「止まるべきときに止まる」ことが最優先になる。停止条件の判定を
エージェントの記憶に任せると、サイクルが長引いたときに期限を跨いでしまう。
判定をこのスクリプトに寄せて、サイクルの先頭で必ず呼ぶ運用にする。

書き込み先はカレントディレクトリの ``.tmp/away-shift/`` の中に閉じる
(run_id の検査、シンボリックリンク・ハードリンクの拒否)。根は環境変数では変えられない。

サブコマンド:

    init   実行ディレクトリと期限を作る。既存の run があれば再利用する。
           やり直すときは run_id を省略して新しい run を作る
    check  停止条件を判定する。継続なら exit 0、停止なら exit 3。
           停止済み (stopped が埋まっている) の run は確定状態で、状態を変えずに exit 3
    log    サイクルの記録を追記する (--text / --note-file / 標準入力)。停止済みの run でも使える
    status 現在の run の要約を出す。停止済みの run でも使える
    sleep  <秒> (整数 1〜7200) だけ待つ。何も読み書きしない。pi の bg_run で再開を予約する用

exit code:

    0  継続してよい
    3  停止条件に当たった (stdout に理由)
    2  引数や状態の誤り・閉じ込めの違反

依存は標準ライブラリのみ。``uv run --no-project python`` で動く。
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

STATE_NAME = "state.json"
# ユーザが手で置いて止めるためのファイル。run 側とリポジトリ直下の両方を見る
STOP_NAMES = ("STOP", "stop")

EXIT_CONTINUE = 0
EXIT_STOP = 3
EXIT_USAGE = 2

# check の NEXT_WAKE_SECONDS は既定で 3600 まで (--max-wake-minutes 120 までは収まる)
SLEEP_MAX_SECONDS = 7200
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


def cmd_init(args: argparse.Namespace) -> int:
    base = now()
    run_id = args.run_id if args.run_id is not None else base.strftime("%Y%m%d-%H%M%S")
    path = state_path(validate_run_id(run_id))
    confine(path)
    if path.exists():
        state = load_state(run_id)
        print(f"既存の run を再利用します: {run_id}")
        print(f"  期限: {state['deadline']}")
        print(f"  目標: {state['goal']}")
        return EXIT_CONTINUE

    try:
        deadline = parse_deadline(args.deadline, base)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if deadline <= base:
        print(f"期限が現在時刻より前です: {deadline.isoformat()}", file=sys.stderr)
        return EXIT_USAGE

    state = {
        "run_id": run_id,
        "goal": args.goal,
        "started_at": base.isoformat(timespec="seconds"),
        "deadline": deadline.isoformat(timespec="seconds"),
        "max_cycles": args.max_cycles,
        "cycle": 0,
        "stopped": None,
    }
    save_state(run_id, state)
    make_dir(run_dir(run_id) / "cycles")
    # 試行錯誤の作業場。ここだけは消してよい。cycles/ と state.json、
    # report.md は証跡なので消さない
    make_dir(run_dir(run_id) / "work")
    print(f"run_id: {run_id}")
    print(f"作業ディレクトリ: {run_dir(run_id) / 'work'}")
    print(f"証跡ディレクトリ: {run_dir(run_id)} (消さない)")
    print(f"期限: {deadline.isoformat(timespec='seconds')}")
    print(f"最大サイクル: {args.max_cycles}")
    print(f"停止するには: touch {run_dir(run_id) / 'STOP'}  または  touch STOP")
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
    return EXIT_CONTINUE


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
    p_sleep.set_defaults(func=cmd_sleep)

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
