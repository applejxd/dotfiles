"""plan 役 (CHG-0044 段 3) の試験。

- 設定: `[pi.agents.plan]` が reader (bash なし)・deep 階層・30 分・条件の検査つきで出る。他の役は 15 分のまま。検査は不正な値を拒否する
- 守る条件の検査 (audit.ts): 依頼の番号が、返答の「守る条件の突き合わせ」の節に全部あるか (C1 と C10 を取り違えない)
- 1 往復の上限 (children.ts): 役割の timeout_minutes (省略 15 分)。試験の環境変数が優先
``test/agents/pi/plan_role_driver.mjs`` が純粋な関数を動かし、結果を JSON で出す。
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import load_common
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen  # noqa: E402

DRIVER = HERE / "pi" / "plan_role_driver.mjs"
PERSONAL = load_common("applejxd")
WORK = load_common("worker")
needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


# ─── 設定 ───


@pytest.mark.parametrize("common", [PERSONAL, WORK], ids=["personal", "work"])
def test_plan_role_is_read_only_deep_and_gets_a_longer_limit(common) -> None:
    rules = gen.build_pi_harness({}, common)
    plan = rules["agents"]["plan"]
    assert plan["profile"] == "reader"
    assert set(rules["profile_tools"]["reader"]) == {
        "read",
        "grep",
        "find",
        "ls",
    }  # bash を持たない
    assert plan["timeout_minutes"] == 30
    assert plan["check_conditions"] is True
    assert plan["inherit_bypass"] is False  # 読むだけ。bypass を引き継がない
    assert plan["model"].split(":")[-1] in {"xhigh", "high"}  # deep の推論の強さ付き
    others = {n: a for n, a in rules["agents"].items() if n != "plan"}
    assert others and all(
        a["timeout_minutes"] == 15 and a["check_conditions"] is False for a in others.values()
    )


def test_plan_uses_the_deep_tier_of_the_active_provider() -> None:
    assert (
        gen.build_pi_harness({}, PERSONAL)["agents"]["plan"]["model"]
        == "github-copilot/claude-sonnet-5.5:xhigh"
    )
    assert (
        gen.build_pi_harness({}, WORK)["agents"]["plan"]["model"]
        == "amazon-bedrock/us.anthropic.claude-opus-5-5:high"
    )


def _with(plan_change) -> dict:
    c = copy.deepcopy(PERSONAL)
    plan_change(c["pi"]["agents"]["plan"])
    return c


@pytest.mark.parametrize("bad", [0, 121, -5, True, "15", 1.5, None])
def test_a_bad_timeout_is_rejected(bad) -> None:
    with pytest.raises(SystemExit, match="timeout_minutes"):
        gen.pi_agents(_with(lambda a: a.update(timeout_minutes=bad)))


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_a_non_boolean_check_conditions_is_rejected(bad) -> None:
    with pytest.raises(SystemExit, match="check_conditions"):
        gen.pi_agents(_with(lambda a: a.update(check_conditions=bad)))


def test_omitted_values_default_to_15_minutes_and_no_check() -> None:
    agents = gen.pi_agents(_with(lambda a: (a.pop("timeout_minutes"), a.pop("check_conditions"))))
    assert agents["plan"]["timeout_minutes"] == 15 and agents["plan"]["check_conditions"] is False


def test_the_plan_role_is_also_declared_for_plain_windows_pi() -> None:
    # reader は read / grep / find / ls だけなので、フルガード無しの Windows にも、そのまま出る
    subagents = gen.build_pi_subagents({}, PERSONAL)
    assert "plan" in subagents["agents"]
    assert (
        subagents["agents"]["plan"]["description"].strip()
        and subagents["agents"]["plan"]["system"].strip()
    )


# ─── 守る条件の検査 / 往復の上限 ───


@pytest.fixture(scope="module")
def d() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)], capture_output=True, text=True, encoding="utf-8", timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_the_requested_ids_are_read_from_line_starts_once_each(d) -> None:
    assert d["requested"] == ["C1", "C2", "C3", "C10"]  # 行頭だけ。重複と「説明の C9:」は数えない
    assert d["none"] is None  # 依頼に番号が無ければ検査しない


@needs_node
def test_a_full_matching_section_passes_and_a_partial_one_is_reported(d) -> None:
    assert d["full"] == {"requested": ["C1", "C2", "C3", "C10"], "noSection": False, "missing": []}
    # 節の外 (リスクの節) で触れただけの番号は、突き合わせたことにならない
    assert d["partial"]["missing"] == ["C2", "C10"] and d["partial"]["noSection"] is False


@needs_node
def test_a_missing_section_and_prefix_ids_are_handled(d) -> None:
    assert d["noSection"]["noSection"] is True and d["noSection"]["missing"] == [
        "C1",
        "C2",
        "C3",
        "C10",
    ]
    assert d["prefix"]["missing"] == ["C1"]  # C10 の C1 を C1 とみなさない
    assert (
        d["numbered"]["missing"] == [] and d["numbered"]["noSection"] is False
    )  # 「4. 守る条件…」の見出しの形


@needs_node
def test_round_timeout_is_per_role_with_a_test_override(d) -> None:
    t = d["timeouts"]
    assert t["plan"] == 30 * 60 * 1000 and t["explore"] == 15 * 60 * 1000
    assert (
        t["odd"] == 15 * 60 * 1000 and t["unknown"] == 15 * 60 * 1000 and t["default_minutes"] == 15
    )  # 不正・不明は既定
    assert d["test_override"] == 1234
