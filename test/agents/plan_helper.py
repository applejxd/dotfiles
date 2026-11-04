"""judge/plan.ts (解析結果 Plan) の試験で共有する小さな道具。

``plan_driver.mjs`` に、ケースの配列を 1 回の node 起動でまとめて渡す (1 ケースごとに起動すると mvdan-sh の評価で遅い)。

see docs/spec/guard/pi-decide.md#解析結果-plan-と-literal-の定義表
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

DRIVER = ROOT / "test" / "agents" / "pi" / "plan_driver.mjs"
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"
VENDOR = HARNESS / "vendor" / "mvdan-sh"


def run_cases(cases: list[dict]) -> list[dict]:
    """ケースを 1 回の node 起動で解析し、結果 (入力と同じ順) を返す。"""
    node = _node()
    assert node is not None
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "cases.json"
        path.write_text(json.dumps(cases), encoding="utf-8")
        proc = subprocess.run(
            [node, str(DRIVER), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=300,
            check=False,
        )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def tok(word: dict) -> str:
    """比較に使う文字列。lit は値、それ以外は原文。"""
    return word["v"] if word["k"] == "lit" else word["raw"]


def argv_of(site: dict) -> list[str]:
    return [tok(w) for w in site["argv"]]


def cwd_of(site: dict) -> str:
    """cwd の要約: ``caller`` / ``unknown`` / ``chain:..,sibling`` (steps の値をコンマでつなぐ)。"""
    cwd = site["cwd"]
    if cwd["k"] == "chain":
        return "chain:" + ",".join(tok(w) if w["k"] == "lit" else w["raw"] for w in cwd["steps"])
    return cwd["k"]
