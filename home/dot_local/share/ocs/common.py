"""ocs の各部が共有する定数と失敗の扱い。"""

from __future__ import annotations

import sys
from pathlib import Path

HOME = Path.home()
OPENCODE = HOME / ".opencode/bin/opencode"


def die(message: str, hint: str = "") -> None:
    fail("境界を張れないので起動しない", message, hint)


def fail(context: str, message: str, hint: str = "") -> None:
    """失敗して止める。``context`` で**何ができなかったか**を言い分ける。

    ★管理用の操作 (``--handoff`` など) は境界を張らない。そこで
      「起動しない」と言うと、利用者が原因を取り違える。
    """
    print(f"{context}: {message}", file=sys.stderr)
    if hint:
        print(f"  {hint}", file=sys.stderr)
    raise SystemExit(1)


def _now() -> str:
    from datetime import datetime, timezone

    # datetime.UTC は 3.11 から。3.10 の python3 でも起動できるよう残す
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017
