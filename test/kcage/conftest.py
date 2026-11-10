"""箱の試験の共通設定。scripts/ を import の根にする（パッケージ名 kcage。独立リポジトリへ切り出しやすいように）。"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
