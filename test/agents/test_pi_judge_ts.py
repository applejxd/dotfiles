"""TS 版の判定器 (``home/dot_config/pi/harness/judge/``) が、正解データと一致すること。

正解は Python 版の判定結果 (``golden/decide_golden.jsonl``)。
移植の範囲 (bash 以外) は全件一致を必須にする。bash は移植の途中なので、いまは数だけを報告する
(``node test/agents/pi/judge_golden.mjs --bash`` で全件を必須にできる)。
移植が済んだら、ここを ``--bash`` に切り替える。

node の型除去 (strip-types) を使う。22.18 未満の node では実行できないので飛ばす。

see docs/spec/pi-decide.md#ts-版への移植
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from agents_common import ROOT

RUNNER = ROOT / "test" / "agents" / "pi" / "judge_golden.mjs"


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return node if (major, minor) >= (22, 18) else None


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_judge_matches_the_python_golden_outside_bash():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    # 移植済みの区分が空でないこと (正解データの読み込みの失敗を見逃さない)
    assert "file " in proc.stdout and "invalid" in proc.stdout
