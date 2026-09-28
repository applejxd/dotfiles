"""ocs の各部が共有する定数と失敗の扱い。"""

from __future__ import annotations

import sys
from pathlib import Path

HOME = Path.home()
OPENCODE = HOME / ".opencode/bin/opencode"
# ocs の状態 (境界の定義・Fence の TMPDIR・退避・目印)。境界の内側から見えない。
STATE = HOME / ".local/state/opencode-sandbox"


def die(message: str, hint: str = "") -> None:
    """失敗して止める。境界を張れないなら起動しない。"""
    print(f"境界を張れないので起動しない: {message}", file=sys.stderr)
    if hint:
        print(f"  {hint}", file=sys.stderr)
    raise SystemExit(1)


def _now() -> str:
    from datetime import datetime, timezone

    # datetime.UTC は 3.11 から。3.10 の python3 でも起動できるよう残す
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017
