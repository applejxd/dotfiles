"""Tests for enabledPlugins generation in scripts/agents/generate.py.

anthropic-agent-skills の document-skills と example-skills は中身が同一で、
両方有効にすると 17 スキルが二重登録される。common.toml でどちらを残すかを
宣言し、それ以外のプラグインはユーザーの設定を壊さないことを固定する。

Run with: ``uv run --with pytest --no-project pytest test/agents/``
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"

with COMMON_PATH.open("rb") as f:
    COMMON = tomllib.load(f)


def test_common_toml_declares_enabled_plugins():
    plugins = COMMON["copilot"]["enabled_plugins"]
    assert plugins["document-skills@anthropic-agent-skills"] is True
    assert plugins["example-skills@anthropic-agent-skills"] is False


def test_duplicate_skill_plugin_is_disabled():
    # 同一内容の 2 プラグインが両方 true になっていないこと。
    plugins = COMMON["copilot"]["enabled_plugins"]
    duplicates = [
        "document-skills@anthropic-agent-skills",
        "example-skills@anthropic-agent-skills",
    ]
    enabled = [name for name in duplicates if plugins.get(name)]
    assert len(enabled) == 1, f"重複プラグインが {len(enabled)} 個有効: {enabled}"


def test_merge_copilot_settings_applies_declared_plugins():
    merged = gen.merge_copilot_settings({}, COMMON)
    assert merged["enabledPlugins"]["example-skills@anthropic-agent-skills"] is False
    assert merged["enabledPlugins"]["document-skills@anthropic-agent-skills"] is True


def test_merge_copilot_settings_preserves_unlisted_plugins():
    # ユーザーが別途入れたプラグインを消さない。
    existing = {
        "enabledPlugins": {
            "some-other-plugin@marketplace": True,
            "example-skills@anthropic-agent-skills": True,
        }
    }
    merged = gen.merge_copilot_settings(existing, COMMON)
    assert merged["enabledPlugins"]["some-other-plugin@marketplace"] is True
    # 宣言したものは上書きされる
    assert merged["enabledPlugins"]["example-skills@anthropic-agent-skills"] is False


def test_merge_copilot_settings_without_declaration_leaves_key_untouched():
    existing = {"enabledPlugins": {"keep@me": True}}
    merged = gen.merge_copilot_settings(existing, {"copilot": {}})
    assert merged["enabledPlugins"] == {"keep@me": True}


def test_enabled_plugins_is_declared_managed():
    assert "enabledPlugins" in gen.COPILOT_MANAGED_KEYS
