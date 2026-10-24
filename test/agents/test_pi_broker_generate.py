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
    broker = gen.build_pi_harness({}, common)["broker"]
    assert broker["copilot"] == expected
    # GitHub ブローカーは機を問わず auto (出どころ無しなら pis が縮退する)
    assert broker["github"] == "auto"
    assert broker["github_token_file"] == "~/.config/pis/github-token"
    assert "github_token_command" not in broker


def test_broker_defaults_to_off_without_the_table():
    common = load_common()
    common.pop("pis", None)
    assert gen.build_pi_harness({}, common)["broker"] == {"copilot": "off", "github": "off"}
    assert gen.build_pi_harness({}, _with_broker(None))["broker"] == {
        "copilot": "off",
        "github": "off",
    }


def test_github_defaults_to_off_when_only_copilot_is_given():
    rules = gen.build_pi_harness({}, _with_broker({"copilot": "auto"}))
    assert rules["broker"] == {"copilot": "auto", "github": "off"}


@pytest.mark.parametrize("value", ["off", "auto", "http://127.0.0.1:18080"])
def test_broker_accepts_the_documented_values(value):
    rules = gen.build_pi_harness({}, _with_broker({"copilot": value}))
    assert rules["broker"]["copilot"] == value


@pytest.mark.parametrize("value", ["off", "auto"])
def test_github_accepts_off_and_auto(value):
    rules = gen.build_pi_harness({}, _with_broker({"github": value}))
    assert rules["broker"]["github"] == value


@pytest.mark.parametrize("value", ["on", "AUTO", "", "http://127.0.0.1:1", 1, True, ["auto"]])
def test_github_rejects_other_values(value):
    with pytest.raises(SystemExit, match="github"):
        gen.build_pi_harness({}, _with_broker({"github": value}))


def test_github_token_file_is_passed_through():
    section = {"github": "auto", "github_token_file": "~/.config/pis/github-token"}
    broker = gen.build_pi_harness({}, _with_broker(section))["broker"]
    assert broker["github_token_file"] == "~/.config/pis/github-token"
    assert "github_token_command" not in broker


def test_github_token_command_is_passed_through_as_argv():
    section = {"github": "auto", "github_token_command": ["bw", "get", "password", "gh-pat"]}
    broker = gen.build_pi_harness({}, _with_broker(section))["broker"]
    assert broker["github_token_command"] == ["bw", "get", "password", "gh-pat"]
    assert "github_token_file" not in broker


def test_github_rejects_both_token_sources():
    section = {
        "github": "auto",
        "github_token_file": "~/t",
        "github_token_command": ["cat", "/x"],
    }
    with pytest.raises(SystemExit, match=r"github_token_file.*github_token_command"):
        gen.build_pi_harness({}, _with_broker(section))


@pytest.mark.parametrize("value", ["", "  ", 1, ["a"], None, "a\0b"])
def test_github_token_file_rejects_bad_values(value):
    with pytest.raises(SystemExit, match="github_token_file"):
        gen.build_pi_harness({}, _with_broker({"github_token_file": value}))


@pytest.mark.parametrize(
    "value", ["bw get", [], [""], [" "], ["a", 1], [["a"]], ["a\0b"], {"a": 1}, 1]
)
def test_github_token_command_rejects_bad_values(value):
    with pytest.raises(SystemExit, match="github_token_command"):
        gen.build_pi_harness({}, _with_broker({"github_token_command": value}))


@pytest.mark.parametrize(
    "value", ["on", "AUTO", "", "127.0.0.1:18080", "https://127.0.0.1:1", 1, True]
)
def test_broker_rejects_other_values(value):
    with pytest.raises(SystemExit, match="copilot"):
        gen.build_pi_harness({}, _with_broker({"copilot": value}))


def test_broker_rejects_unknown_keys():
    with pytest.raises(ValueError, match=r"pis\.broker"):
        gen.build_pi_harness({}, _with_broker({"copilot": "off", "coplot": "auto"}))
    with pytest.raises(ValueError, match=r"pis\.broker"):
        gen.build_pi_harness({}, _with_broker({"github_token": "x"}))


def test_broker_rejects_a_non_table():
    with pytest.raises(SystemExit, match=r"pis\.broker"):
        gen.build_pi_harness({}, _with_broker("auto"))
