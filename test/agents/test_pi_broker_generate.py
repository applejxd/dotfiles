"""``[pis.broker]`` (common.toml) から rules.json の ``broker`` を生成する。

see docs/spec/opencode-sandbox.md#copilot-ブローカーモードpis_copilot_brokerpis-のみ
"""

from __future__ import annotations

import sys

import pytest
from agents_common import ROOT, load_common

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen


def _with_broker(section):
    common = load_common()
    common["pis"] = {} if section is None else {"broker": section}
    return common


def test_rules_json_carries_the_broker_setting_from_common_toml():
    common = load_common()
    provider = common["opencode"]["model"]["provider"]
    expected = "auto" if provider == "github-copilot" else "off"
    assert gen.build_pi_harness({}, common)["broker"] == {"copilot": expected}


def test_broker_defaults_to_off_without_the_table():
    common = load_common()
    common.pop("pis", None)
    assert gen.build_pi_harness({}, common)["broker"] == {"copilot": "off"}
    assert gen.build_pi_harness({}, _with_broker(None))["broker"] == {"copilot": "off"}


@pytest.mark.parametrize("value", ["off", "auto", "http://127.0.0.1:18080"])
def test_broker_accepts_the_documented_values(value):
    rules = gen.build_pi_harness({}, _with_broker({"copilot": value}))
    assert rules["broker"] == {"copilot": value}


@pytest.mark.parametrize(
    "value", ["on", "AUTO", "", "127.0.0.1:18080", "https://127.0.0.1:1", 1, True]
)
def test_broker_rejects_other_values(value):
    with pytest.raises(SystemExit, match="copilot"):
        gen.build_pi_harness({}, _with_broker({"copilot": value}))


def test_broker_rejects_unknown_keys():
    with pytest.raises(ValueError, match=r"pis\.broker"):
        gen.build_pi_harness({}, _with_broker({"copilot": "off", "coplot": "auto"}))


def test_broker_rejects_a_non_table():
    with pytest.raises(SystemExit, match=r"pis\.broker"):
        gen.build_pi_harness({}, _with_broker("auto"))
