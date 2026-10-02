"""Tests for enabledPlugins generation in scripts/agents/generate.py.

anthropic-agent-skills の document-skills と example-skills は中身が同一で、
両方有効にすると 17 スキルが二重登録される。common.toml でどちらを残すかを
宣言し、それ以外のプラグインはユーザーの設定を壊さないことを固定する。

Run with: ``uv run --with pytest --no-project pytest test/agents/``
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

COMMON = load_common()


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


# merge_copilot_settings が書き換えてよいキー。これ以外は CLI や他の経路が
# 書いた値として温存する。増やすときは生成処理とこの一覧を一緒に直す。
COPILOT_MANAGED = {
    "allowedUrls",
    "autoUpdate",
    "deniedUrls",
    "defaultPermissionMode",
    "enabledPlugins",
    "experimental",
    "includeCoAuthoredBy",
    "model",
    "sandbox",
    "trustedFolders",
}

FULL_COPILOT_COMMON = {
    "web": {"allow_domains": ["example.com"], "deny_domains": ["evil.test"]},
    "copilot": {
        "auto_update": False,
        "model": "m",
        "trusted_folders": ["/work"],
        "include_co_authored_by": False,
        "default_permission_mode": "assisted",
        "experimental": True,
        "enabled_plugins": {"a@m": True},
    },
}


def test_copilot_settings_touch_only_the_managed_keys():
    """全部宣言しても、書き換わるのは管理キーだけ。"""
    existing = {key: {"sentinel": True} for key in COPILOT_MANAGED}
    existing.update({"theme": "dark", "loggedInUsers": []})
    merged = gen.merge_copilot_settings(existing, FULL_COPILOT_COMMON)
    changed = {k for k in set(existing) | set(merged) if existing.get(k) != merged.get(k)}
    assert changed == COPILOT_MANAGED


def test_copilot_settings_generate_only_the_managed_keys():
    assert set(gen.merge_copilot_settings({}, FULL_COPILOT_COMMON)) == COPILOT_MANAGED


def test_copilot_model_without_declaration_keeps_existing():
    merged = gen.merge_copilot_settings({"model": "x"}, {"copilot": {}})
    assert merged["model"] == "x"
