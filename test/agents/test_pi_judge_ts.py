"""TS 版の判定器 (``home/dot_config/pi/harness/judge/``) が、正解データと一致すること。

正解は Python 版の判定結果 (``golden/decide_golden.jsonl``)。
bash を含む全件の一致を必須にする (``node test/agents/pi/judge_golden.mjs --bash``)。

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
POLICY_RUNNER = ROOT / "test" / "agents" / "pi" / "policy_golden.mjs"
CHECKS_RUNNER = ROOT / "test" / "agents" / "pi" / "checks_golden.mjs"


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return node if (major, minor) >= (22, 18) else None


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_judge_matches_the_python_golden():
    proc = subprocess.run(
        [_node(), str(RUNNER), "--bash"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    # 区分が空でないこと (正解データの読み込みの失敗を見逃さない)
    assert "bash " in proc.stdout and "file " in proc.stdout and "invalid" in proc.stdout


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_policy_parts_match_the_python_golden():
    """shlex・分割・正規化・置換と関数の抽出・find_match が、Python 版と全件一致する。"""
    proc = subprocess.run(
        [_node(), str(POLICY_RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    assert "normalize" in proc.stdout and "shlex" in proc.stdout


@pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
def test_ts_bashrules_parts_match_the_python_golden():
    """heredoc の分離・cd 展開・コマンドの分割・書き込み先と、移植済みの検査関数が全件一致する。"""
    proc = subprocess.run(
        [_node(), str(CHECKS_RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]
    assert "heredoc" in proc.stdout and "commands" in proc.stdout
