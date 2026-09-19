"""checkpoint hook の共通処理。

段 5 (圧縮直前の機械記録と圧縮直後の復帰) に必要な範囲だけを持つ。

**保存先の解決・アトミック書き込み・検査は再実装しない。** それらは
``~/.claude/skills/checkpoint/scripts/checkpoint.py`` が持っていて、スキルと
hook が同じ結果を得られるように 1 箇所へ寄せてある。ここはその利用側になる。

状態機械と使用率の推定は**ここに置かない**。あれは Tier 2 (閾値監視) の都合で
あり、段 5 の機械記録には要らない。Copilot では ``PostToolUse`` の入力に
``transcript_path`` が無く使用率を推定できないことも実測済みなので、その依存を
機械記録へ持ち込まない。

参照:

- docs/research/compaction-hooks.md (記録 E3 / E4)
- docs/adr/0009-save-before-documenting.md
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

# 印まわりは速度の都合で別モジュールにしてある (checkpoint_pending の冒頭参照)。
# 利用側がどちらを import しても同じものを得られるよう、ここから再 export する。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checkpoint_pending import (
    DEFAULT_PENDING_DIR,
    MAX_CONTEXT_BYTES,
    PENDING_DIR_ENV,
    clear_restore_pending,
    debug_log,
    mark_restore_pending,
    pending_dir,
    read_input,
    session_id_of,
    take_restore_pending,
    truncate_for_context,
)

# 前半は checkpoint_pending からの再 export。後半はこのモジュール自身のもの。
__all__ = [
    "DEFAULT_PENDING_DIR",
    "GIT_TIMEOUT_SEC",
    "MACHINE_MARKER",
    "MAX_CONTEXT_BYTES",
    "MAX_LISTED_FILES",
    "PENDING_DIR_ENV",
    "clear_restore_pending",
    "collect_snapshot",
    "debug_log",
    "load_skill_module",
    "mark_restore_pending",
    "pending_dir",
    "read_checkpoint",
    "read_input",
    "replace_machine_section",
    "session_id_of",
    "skeleton",
    "take_restore_pending",
    "trigger_of",
    "truncate_for_context",
    "write_snapshot",
]

# スキル側の実装を単一ソースとして読み込む。配備先は chezmoi が決めるので、
# 実行時に解決する。
_SKILL_SCRIPT = Path.home() / ".claude" / "skills" / "checkpoint" / "scripts" / "checkpoint.py"

# 機械節の開始位置。ここから下は毎回まるごと差し替える。
MACHINE_MARKER = "<!-- machine:"

# 記録するファイル一覧の上限。長い status で checkpoint を膨らませない。
MAX_LISTED_FILES = 20

# git コマンドの制限時間。hook は速く終わる必要がある。
GIT_TIMEOUT_SEC = 5


def load_skill_module(path: Path | None = None) -> Any | None:
    """スキル側の checkpoint.py を読み込む。無ければ None。

    スキルが未配備でも hook を落とさない。
    """
    script = path or _SKILL_SCRIPT
    if not script.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("checkpoint_cli", script)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # pragma: no cover - 壊れた配備でも hook を落とさない
        return None


def trigger_of(data: dict[str, Any]) -> str:
    """compaction の契機 (manual / auto) を取り出す。"""
    value = data.get("trigger")
    return value if isinstance(value, str) else ""


def _git(args: list[str], cwd: Path) -> str:
    """git を実行して stdout を返す。失敗したら空文字。"""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _porcelain_path(line: str) -> str:
    """``git status --porcelain=v1`` の 1 行からパスを取り出す。

    行頭は 2 文字の状態コードで、3 文字目以降がパス。ただし ``R old -> new``
    のようにリネームは矢印を挟むので、その場合は新しい側を返す。
    """
    path = line[2:].lstrip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def collect_snapshot(root: Path, trigger: str) -> str:
    """機械的な事実だけを集める。

    集めるのは「誰が見ても同じ答えになるもの」に限る。意味内容はモデルが書く
    ので、ここでは触らない。
    """
    now = dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")

    head = _git(["rev-parse", "--short", "HEAD"], root) or "(不明)"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "(不明)"

    status = _git(["status", "--porcelain=v1"], root)
    status_lines = [line for line in status.splitlines() if line.strip()]

    # 生の diff は長くなりすぎる。要約だけを載せる。
    shortstat = _git(["diff", "--shortstat"], root) or "(差分なし)"

    # ★porcelain=v1 の行頭は「2 文字の状態 + 空白」。
    #   ただし ` M path` のように状態が 1 文字ぶん空白のこともあるので、
    #   固定長で切ると先頭 1 文字を食う。空白で区切って取り直す。
    listed = [_porcelain_path(line) for line in status_lines[:MAX_LISTED_FILES]]
    overflow = len(status_lines) - len(listed)

    parts = [
        f"{MACHINE_MARKER} ここから下は PreCompact が上書きする。"
        "意味内容の予算に含めない -->",
        "## Snapshot",
        "",
        f"- snapshot_at: {now}",
        f"- trigger: {trigger or '(不明)'}",
        f"- head: {head} ({branch})",
        f"- status: {len(status_lines)} 件",
        f"- diff: {shortstat}",
    ]
    if listed:
        parts.append("- changed:")
        parts.extend(f"  - {name}" for name in listed)
        if overflow > 0:
            parts.append(f"  - …ほか {overflow} 件")
    return "\n".join(parts) + "\n"


def skeleton(session: str) -> str:
    """checkpoint が無いときに作る骨格。

    空よりはマシ、という位置づけ。意味内容は埋まっていないので、これだけで
    復帰できるとは考えない。
    """
    return (
        f"<!-- checkpoint: v1\n"
        f"     session: {session}\n"
        f"     updated_at: (未記入)\n"
        f"     covered_through: (未記入)\n"
        f"-->\n"
        "# Checkpoint — (未記入)\n\n"
        "## Goal\n\n"
        "(未記入。圧縮前に `checkpoint` スキルが実行されなかった)\n\n"
        "## Constraints\n\n(未記入)\n\n"
        "## State\n\n(未記入)\n\n"
        "## Evidence\n\n(未記入)\n\n"
        "## Next\n\n(未記入)\n\n"
        "## Refs\n\n(未記入)\n"
    )


def replace_machine_section(text: str, snapshot: str) -> str:
    """機械節だけを差し替える。

    ★意味内容には触れない。``updated_at`` と ``covered_through`` も動かさない。
    ここを動かすと、古い内容が「新鮮」に見えてしまう。
    """
    index = text.find(MACHINE_MARKER)
    body = text if index == -1 else text[:index]
    body = body.rstrip("\n") + "\n"
    return f"{body}\n{snapshot}"


def write_snapshot(data: dict[str, Any], module: Any | None = None) -> dict[str, Any]:
    """機械節を書く。結果を辞書で返す (呼び出し側がログに使う)。"""
    module = module or load_skill_module()
    if module is None:
        return {"ok": False, "reason": "checkpoint skill not deployed"}

    session = session_id_of(data)
    if not session:
        return {"ok": False, "reason": "no session id"}

    cwd = data.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()

    try:
        paths = module.resolve_paths(session, start)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}

    target = Path(paths["checkpoint"])
    root = Path(paths["root"])

    # 圧縮直後へ割り込めない CLI のために、ここで印を残す。
    # ★書き込みの成否より前に置く。機械節の更新に失敗しても、既にある
    #   checkpoint は戻す価値があるため。
    pending = mark_restore_pending(data, target)

    existed = target.exists()
    text = target.read_text(encoding="utf-8") if existed else skeleton(session)
    updated = replace_machine_section(text, collect_snapshot(root, trigger_of(data)))

    try:
        module.atomic_write(target, updated)
    except OSError as exc:
        return {"ok": False, "reason": str(exc), "pending": pending}

    return {"ok": True, "created": not existed, "path": str(target), "pending": pending}


def read_checkpoint(data: dict[str, Any], module: Any | None = None) -> str | None:
    """自分のセッションの checkpoint を読む。

    ★他セッションのファイルは決して読まない。``resolve_paths`` が返した自分の
    パスだけを見る。無ければ None。
    """
    module = module or load_skill_module()
    if module is None:
        return None

    session = session_id_of(data)
    if not session:
        return None

    cwd = data.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()

    try:
        paths = module.resolve_paths(session, start)
    except ValueError:
        return None

    target = Path(paths["checkpoint"])
    if not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None
