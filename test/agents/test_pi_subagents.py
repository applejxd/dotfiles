"""素の pi (Windows) 用の子エージェント宣言。see docs/spec/pi-harness.md#windows-の子エージェント"""

from __future__ import annotations

import sys

from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen


def test_only_read_only_agents_are_declared():
    agents = gen.build_pi_subagents({}, load_common())["agents"]

    # shell・編集を持つ役割 (commit / worker) は判定器が無いので出さない
    assert set(agents) == {"explore", "review"}
    for agent in agents.values():
        assert set(agent) == {"description", "system", "model"}


def test_pi_tier_override_beats_the_opencode_tier():
    common = load_common()
    provider = common["opencode"]["model"]["provider"]
    override = (common["pi"].get("model", {}).get("tier", {}).get(provider) or {}).get("second_opinion")
    if override:
        assert gen.pi_model_ref(common, "second_opinion").endswith(override)
