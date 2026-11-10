#!/usr/bin/env python3
# 転送。本体は home/dot_agents/skills/feature-orchestration/scripts/parallel_check.py
"""本体へ引数・終了コード・標準入出力・環境変数をそのまま渡す転送。"""

import os
import subprocess
import sys
from pathlib import Path

SKILL = (
    Path(__file__).resolve().parent.parent / "home/dot_agents/skills/feature-orchestration/scripts"
)
BODY = SKILL / "parallel_check.py"

# POSIX は execv で同じ pid のまま置き換える（wt_owner の pid 検出が祖先をたどるため、中間の python を残さない）。
# Windows の execv は終了コードを返さないので subprocess で動かす。
if __name__ == "__main__":
    if os.name == "nt":
        sys.exit(subprocess.run([sys.executable, str(BODY), *sys.argv[1:]], check=False).returncode)
    os.execv(sys.executable, [sys.executable, str(BODY), *sys.argv[1:]])
