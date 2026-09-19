"""圧縮直後の復帰待ちを示す「印」の読み書き。

``checkpoint_core`` から切り出してある。**理由は速度**である。

この印を読むのは Copilot の ``PostToolUse`` で、全てのツール呼び出しごとに
発火する。``checkpoint_core`` は ``subprocess`` / ``importlib.util`` /
``datetime`` を読み込むので、import するだけで 1 回あたり 25ms 前後かかる。
印が無いときに払う必要の無いコストなので、ここには標準の軽い import だけを置く。

実測 (WSL / Ubuntu, Python 3.12):

| 構成 | 1 回あたり |
| --- | --- |
| python3 の素の起動 | 17ms |
| このモジュールだけ | 33ms |
| ``checkpoint_core`` まで読む | 48ms |

``checkpoint_core`` はここから再 export しているので、利用側はどちらを
import してもよい。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# 印の既定の置き場。
#
# ★リポジトリ内ではなくホーム直下に置く。リポジトリ内だと在処を知るのに
#   ``git rev-parse`` が要り、その subprocess を毎ツール払うことになる。
#   ホーム固定なら印の有無は stat 1 回で判る。
DEFAULT_PENDING_DIR = Path.home() / ".cache" / "checkpoint-hooks"

# 置き場を差し替える環境変数。テストが実ホームを汚さないために要る。
PENDING_DIR_ENV = "CHECKPOINT_PENDING_DIR"

# 印に載せる checkpoint 本文の上限 (バイト)。
#
# ★Copilot の ``additionalContext`` は 10 KB で切られる。複数 hook の出力は
#   2 行空けて連結されてから切られるので、余裕を見て 9 KB に収める。
#   出典: https://docs.github.com/en/copilot/reference/hooks-reference
MAX_CONTEXT_BYTES = 9000


def read_input() -> dict[str, Any]:
    """stdin の JSON を読む。壊れていても落とさない。"""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def session_id_of(data: dict[str, Any]) -> str:
    """hook 入力からセッション ID を取り出す。

    PascalCase で登録しているので snake_case が来る (記録 E3)。将来 camelCase
    で来る経路もありうるので両方見る。
    """
    for key in ("session_id", "sessionId"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def pending_dir() -> Path:
    """印の置き場。環境変数があればそちらを使う。"""
    override = os.environ.get(PENDING_DIR_ENV)
    return Path(override) if override else DEFAULT_PENDING_DIR


def truncate_for_context(text: str, limit: int = MAX_CONTEXT_BYTES) -> str:
    """``additionalContext`` の上限に収まるよう末尾を落とす。

    日本語は 1 文字 3 バイトなので、文字数ではなくバイト数で測る。切ったときは
    その事実を明記する。黙って切ると、モデルが「記録はここで終わり」と誤解する。
    """
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text

    notice = "\n\n(上限に達したため以降を省略しました。全文は上記のファイルにあります)"
    budget = limit - len(notice.encode("utf-8"))
    # 多バイト文字の途中で切れた分は捨てる。
    return raw[:budget].decode("utf-8", errors="ignore") + notice


def _pending_path(session: str) -> Path | None:
    """復帰待ちの印の場所。セッション ID が空なら None。"""
    key = re.sub(r"[^0-9A-Za-z]", "", session)
    if not key:
        return None
    return pending_dir() / f"{key}.pending"


def mark_restore_pending(data: dict[str, Any], checkpoint: Path) -> bool:
    """「次の機会に checkpoint を戻すこと」を印として残す。

    圧縮直後へ割り込めるイベントを持たない CLI (Copilot) 向け。印の中身は
    checkpoint の絶対パス 1 行だけで、本文は複製しない。複製すると、圧縮の後に
    更新された内容を取りこぼす。
    """
    marker = _pending_path(session_id_of(data))
    if marker is None:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(checkpoint), encoding="utf-8")
    except OSError:
        return False
    return True


def clear_restore_pending(data: dict[str, Any]) -> None:
    """印を消す。圧縮直後に割り込めた CLI (Claude) 側の後始末。"""
    marker = _pending_path(session_id_of(data))
    if marker is None:
        return
    with contextlib.suppress(OSError):
        marker.unlink(missing_ok=True)


def take_restore_pending(data: dict[str, Any]) -> str | None:
    """印が立っていれば checkpoint 本文を返し、印を消す。

    ★印は読めたかどうかに関わらず消す。消さないと、読めないファイルを相手に
      ツール呼び出しのたび再試行して回り続ける。

    ★読むのは印に書かれたパスだけで、しかも ``checkpoint-*.md`` という自分の
      命名に一致するものに限る。他セッションのファイルは読まない。
    """
    marker = _pending_path(session_id_of(data))
    if marker is None:
        return None

    try:
        raw = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    finally:
        with contextlib.suppress(OSError):
            marker.unlink(missing_ok=True)

    if not raw:
        return None

    target = Path(raw)
    if not target.name.startswith("checkpoint-") or target.suffix != ".md":
        return None
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return None


def debug_log(name: str, payload: dict[str, Any]) -> None:
    """デバッグ用の記録。環境変数が立っているときだけ書く。

    hook は静かに失敗しがちなので、追跡できる口を残しておく。
    """
    if not os.environ.get("CHECKPOINT_HOOK_DEBUG"):
        return
    with contextlib.suppress(Exception):  # pragma: no cover
        sys.stderr.write(json.dumps({"hook": name, **payload}, ensure_ascii=False) + "\n")
