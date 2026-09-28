"""OpenCode のモデルとプロバイダの生成 (``[opencode.model]``) の test.

PC ごとのプロバイダは ``.chezmoitemplates/llm-provider`` が決める。
see docs/spec/agent-config-generation.md#モデルの割り当て

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

PERSONAL = load_common("applejxd")
WORK = load_common("worker")


def generated(common: dict, existing: dict | None = None) -> dict:
    return gen.merge_opencode_config(existing or {}, common)


def with_agents(common: dict, agents: dict) -> dict:
    out = copy.deepcopy(common)
    out["opencode"]["model"]["agents"] = agents
    return out


def render_provider(context: dict) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    literal = json.dumps(json.dumps(context))
    include = '{{ includeTemplate "llm-provider" . }}'
    template = f"{{{{ with {literal} | fromJson }}}}{include}{{{{ end }}}}"
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", template],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


# ---------------------------------------------------------------------------
# プロバイダの判定
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("username", "provider"),
    [
        ("applejxd", "github-copilot"),
        ("APPLEJXD", "github-copilot"),
        ("DESKTOP-1\\applejxd", "github-copilot"),
        ("worker", "amazon-bedrock"),
        ("applejxd2", "amazon-bedrock"),
    ],
)
def test_provider_follows_the_username(username, provider):
    assert render_provider({"chezmoi": {"username": username}}) == provider


def test_data_overrides_the_username():
    context = {"chezmoi": {"username": "worker"}, "llm_provider": "github-copilot"}
    assert render_provider(context) == "github-copilot"


def test_common_toml_carries_the_detected_provider():
    assert PERSONAL["opencode"]["model"]["provider"] == "github-copilot"
    assert WORK["opencode"]["model"]["provider"] == "amazon-bedrock"


# ---------------------------------------------------------------------------
# 既定モデルと接続設定
# ---------------------------------------------------------------------------

def test_default_model_on_each_provider():
    assert generated(PERSONAL)["model"] == "github-copilot/claude-opus-5.5"
    assert generated(WORK)["model"] == "amazon-bedrock/global.anthropic.claude-sonnet-5"


def test_copilot_tiers_share_one_model_by_variant():
    tiers = PERSONAL["opencode"]["model"]["tier"]["github-copilot"]
    assert tiers["light"] == "claude-opus-5.5#medium"
    assert tiers["heavy"] == "claude-opus-5.5#xhigh"
    assert tiers["second_opinion"] == "gpt-6-astra"


def test_every_provider_defines_the_same_tiers():
    """階層名だけで割り当てるので、どの PC でも同じ階層が引けること。"""
    tiers = PERSONAL["opencode"]["model"]["tier"]
    names = {provider: set(models) for provider, models in tiers.items()}
    assert len(set(map(frozenset, names.values()))) == 1, names
    assert {"default", "light", "heavy"} <= next(iter(names.values()))


def test_bedrock_gets_profile_and_region():
    """★profile が無いと ~/.aws があっても Bedrock が有効にならない。"""
    settings = generated(WORK)["providers"]["amazon-bedrock"]["settings"]
    assert settings == {"profile": "default", "region": "us-east-1"}


def test_bedrock_network_allow_matches_the_region():
    provider = WORK["provider"]["amazon-bedrock"]
    assert provider["network_allow"] == [f"bedrock-runtime.{provider['region']}.amazonaws.com"]


def test_copilot_writes_no_provider_settings():
    assert "providers" not in generated(PERSONAL)


def test_unmanaged_provider_settings_survive():
    existing = {"providers": {"amazon-bedrock": {"settings": {"baseURL": "https://vpce"}}, "x": {}}}
    out = generated(WORK, existing)["providers"]
    assert out["amazon-bedrock"]["settings"]["baseURL"] == "https://vpce"
    assert out["amazon-bedrock"]["settings"]["profile"] == "default"
    assert "x" in out


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("common", [PERSONAL, WORK], ids=["personal", "work"])
def test_only_the_detected_provider_is_usable(common):
    provider = common["opencode"]["model"]["provider"]
    policies = generated(common)["experimental"]["policies"]
    assert policies[-2:] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": provider, "effect": "allow"},
    ], "後勝ちなので allow が最後に来ること"


def test_other_policies_and_experimental_keys_survive():
    other = {"action": "permission", "resource": "shell:git push *", "effect": "deny"}
    stale = {"action": "provider.use", "resource": "openai", "effect": "allow"}
    existing = {"experimental": {"policies": [other, stale], "flag": True}}
    out = generated(PERSONAL, existing)
    experimental = out["experimental"]
    assert experimental["flag"] is True
    assert other in experimental["policies"]
    assert stale not in experimental["policies"], "古い provider.use を残さない"
    assert generated(PERSONAL, out) == out, "冪等"


# ---------------------------------------------------------------------------
# エージェントごとの割り当て
# ---------------------------------------------------------------------------

def test_no_agent_models_until_assigned():
    assert "agents" not in generated(PERSONAL)


def test_assignment_goes_to_v2_agents_with_variant():
    """★V1 の agent キーでは #variant 付きの指定が黙って無視される (実測)。"""
    out = generated(with_agents(WORK, {"explore": "light", "plan": "heavy"}))
    assert out["agents"] == {
        "explore": {"model": "amazon-bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"},
        "plan": {"model": "amazon-bedrock/global.anthropic.claude-opus-5-5#high"},
    }
    assert "explore" not in out["agent"] and "plan" not in out["agent"]


def test_unassigning_removes_only_managed_models():
    assigned = generated(with_agents(PERSONAL, {"explore": "light", "plan": "heavy"}))
    assigned["agents"]["plan"]["color"] = "#ff6b6b"
    assigned["agents"]["mine"] = {"model": "github-copilot/gpt-5-mini"}
    out = generated(PERSONAL, assigned)["agents"]
    assert "explore" not in out, "model しか無いエントリは消す"
    assert out["plan"] == {"color": "#ff6b6b"}
    assert out["mine"] == {"model": "github-copilot/gpt-5-mini"}, "手で書いたモデルは残す"


def test_switching_provider_rewrites_assigned_models():
    personal = generated(with_agents(PERSONAL, {"explore": "light"}))
    work = generated(with_agents(WORK, {"explore": "light"}), personal)
    assert work["agents"]["explore"]["model"].startswith("amazon-bedrock/")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c["opencode"]["model"].update(agents={"explore": "tiny"}), "tiny"),
        (lambda c: c["opencode"]["model"].update(provider="openai"), "openai"),
        (
            lambda c: c["opencode"]["model"]["tier"]["github-copilot"].update(
                default="claude-opus-5.5#high"
            ),
            "#variant",
        ),
        (lambda c: c["opencode"]["model"].update(agents={"bypass": "heavy"}), "bypass"),
    ],
    ids=["unknown-tier", "unknown-provider", "default-variant", "v1-agent"],
)
def test_invalid_model_config_stops_apply(mutate, message):
    common = copy.deepcopy(PERSONAL)
    mutate(common)
    with pytest.raises(SystemExit) as excinfo:
        generated(common)
    assert message in str(excinfo.value)
