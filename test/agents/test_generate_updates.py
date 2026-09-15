"""Regression tests for mise-owned CLI updates."""

import copy
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

COMMON = tomllib.loads(
    (ROOT / "home/dot_config/agents/common.toml").read_text(encoding="utf-8")
)


def test_common_disables_native_auto_updates():
    assert COMMON["claude"]["auto_update"] is False
    assert COMMON["copilot"]["auto_update"] is False
    assert "autoUpdate" in gen.COPILOT_MANAGED_KEYS
    assert gen.merge_claude_settings({}, COMMON)["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert gen.merge_copilot_settings({}, COMMON)["autoUpdate"] is False


@pytest.mark.parametrize("enabled", [False, True])
def test_claude_update_setting_preserves_foreign_env_and_input(enabled):
    existing = {"env": {"KEEP": "value", "DISABLE_AUTOUPDATER": "old"}, "theme": "dark"}
    before = copy.deepcopy(existing)
    common = {"claude": {"auto_update": enabled}}
    merged = gen.merge_claude_settings(existing, common)
    assert merged["env"] == {"KEEP": "value", "DISABLE_AUTOUPDATER": "0" if enabled else "1"}
    assert merged["theme"] == "dark"
    assert existing == before
    assert gen.merge_claude_settings(merged, common) == merged


@pytest.mark.parametrize("enabled", [False, True])
def test_copilot_update_setting_preserves_other_settings(enabled):
    existing = {"autoUpdate": not enabled, "theme": "dark", "loggedInUsers": []}
    before = copy.deepcopy(existing)
    common = {"copilot": {"auto_update": enabled}}
    merged = gen.merge_copilot_settings(existing, common)
    assert merged["autoUpdate"] is enabled
    assert merged["theme"] == "dark"
    assert merged["loggedInUsers"] == []
    assert existing == before
    assert gen.merge_copilot_settings(merged, common) == merged


@pytest.mark.parametrize(
    "merger,existing",
    [
        (gen.merge_claude_settings, {"env": {"DISABLE_AUTOUPDATER": "custom"}}),
        (gen.merge_copilot_settings, {"autoUpdate": True}),
    ],
)
def test_undeclared_update_policy_leaves_existing_setting_untouched(merger, existing):
    merged = merger(existing, {})
    for key, value in existing.items():
        assert merged[key] == value
    empty = merger({}, {})
    assert "env" not in empty
    assert "autoUpdate" not in empty
