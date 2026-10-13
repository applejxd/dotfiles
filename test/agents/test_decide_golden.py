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


def _exporter(name="export_decide_golden"):
    script = (
        ROOT / "scripts" / "agents" / f"{name}.py" if name != "export_decide_golden" else SCRIPT
    )
    spec = importlib.util.spec_from_file_location(name, script)
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


def test_policy_golden_matches_the_python_parts_on_a_sample():
    """部品ごとの正解データ (``policy_golden.jsonl``) が、いまの Python 版と一致している (標本)。"""
    import shlex

    exporter = _exporter("export_policy_golden")  # hooks/lib を import のパスに足す
    from bashrules import _shared

    policy = exporter.policy
    path = ROOT / "test" / "agents" / "golden" / "policy_golden.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 5000, "正解データが小さすぎる (書き出し直す)"
    patterns = exporter._patterns()
    mismatches = []
    for index, line in enumerate(lines):
        if index % SAMPLE_EVERY:
            continue
        entry = json.loads(line)
        _shared._LITERAL_HEREDOC_BODIES.clear()
        arg = entry["arg"]
        if entry["fn"] == "shlex":
            try:
                got = {"tokens": shlex.split(arg)}
            except ValueError as exc:
                got = {"error": str(exc)}
        elif entry["fn"] == "split":
            got = policy.split_command_segments(arg)
        elif entry["fn"] == "normalize":
            got = policy.normalize(arg)
        elif entry["fn"] == "subst":
            got = policy.extract_command_substitutions(arg)
        elif entry["fn"] == "funcs":
            got = policy.extract_function_bodies(arg)
        else:
            got = policy.find_match(arg, patterns[entry["list"]])
        if got != entry["out"]:
            mismatches.append((index, entry["fn"], arg, entry["out"], got))
    assert not mismatches, (
        "部品の正解データが古い。`python scripts/agents/export_policy_golden.py` で書き出し直す: "
        f"{mismatches[:3]}"
    )
