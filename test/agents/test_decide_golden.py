"""判定 API の正解データ (``golden/decide_golden.jsonl``) が、いまの Python 版と一致していること。

TS へ移植した判定器との差分試験 (``pi/judge_golden.mjs``) の正解として使うので、
規則 (``common.toml``) や判定器を変えたら、
``scripts/agents/export_decide_golden.py`` で書き出し直す。
全件の再生成は約 1 分かかるので、ここでは一定間隔の標本だけを突き合わせる
(全件は ``export_decide_golden.py --check``)。

see docs/spec/pi-decide.md
"""

from __future__ import annotations

import importlib.util
import json

from agents_common import ROOT

SCRIPT = ROOT / "scripts" / "agents" / "export_decide_golden.py"
GOLDEN = ROOT / "test" / "agents" / "golden" / "decide_golden.jsonl"
SAMPLE_EVERY = 29


def _exporter():
    spec = importlib.util.spec_from_file_location("export_decide_golden", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_golden_matches_the_python_judge_on_a_sample():
    exporter = _exporter()
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 5000, "正解データが小さすぎる (書き出し直す)"
    mismatches = []
    for index, line in enumerate(lines):
        if index % SAMPLE_EVERY:
            continue
        item = json.loads(line)
        got = exporter._tokenize(exporter.decide(exporter._expand(item["request"])))
        if got != item["response"]:
            mismatches.append((index, item["request"], item["response"], got))
    assert not mismatches, (
        "正解データが古い。`python scripts/agents/export_decide_golden.py` で書き出し直す: "
        f"{mismatches[:3]}"
    )


def test_golden_covers_every_decision_and_source():
    pairs = set()
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        response = json.loads(line)["response"]
        pairs.add((response["decision"], response["source"]))
    assert {
        ("allow", "default"),
        ("allow", "rule"),
        ("ask", "check"),
        ("deny", "check"),
        ("deny", "rule"),
        ("deny", "error"),
    } <= pairs
