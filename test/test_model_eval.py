"""scripts/model-eval の採点 (grade.py) が、模範解答で合格し元の課題で落ちることを確かめる。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "model-eval" / "worker"


def test_grade_selftest(tmp_path: Path) -> None:
    # 課題の作業リポジトリの git に、利用者の hook や設定を効かせない
    env = {**os.environ, "TMPDIR": str(tmp_path), "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1"}
    r = subprocess.run(
        [sys.executable, str(WORKER / "selftest.py"), "--python", sys.executable],
        cwd=WORKER, capture_output=True, text=True, encoding="utf-8", env=env,
        check=False, timeout=600,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("模範解答") == 7, r.stdout
