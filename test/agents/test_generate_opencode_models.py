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
    assert generated(WORK)["model"] == "amazon-bedrock/global.anthropic.claude-sonnet-5-5"


TIER_NAMES = {"default", "routine", "worker", "deep", "second_opinion"}


def test_copilot_tiers_pick_effort_by_variant():
    tiers = PERSONAL["opencode"]["model"]["tier"]["github-copilot"]
    assert tiers["worker"] == "claude-sonnet-5.5#medium"
    assert tiers["deep"] == "claude-opus-5.5#xhigh"
    assert tiers["second_opinion"] == "gpt-6-astra"


def test_every_provider_defines_the_same_tiers():
    """階層名だけで割り当てるので、どの PC でも同じ階層が引けること。"""
    tiers = PERSONAL["opencode"]["model"]["tier"]
    names = {provider: set(models) for provider, models in tiers.items()}
    assert set(map(frozenset, names.values())) == {frozenset(TIER_NAMES)}, names


@pytest.mark.parametrize("common", [PERSONAL, WORK], ids=["personal", "work"])
def test_tiers_are_named_by_purpose(common):
    """改名前の大小の名前 (light / standard / heavy) を定義にも割り当てにも残さない。"""
    model = common["opencode"]["model"]
    old = {"light", "standard", "heavy"}
    for provider, tiers in model["tier"].items():
        assert not old & set(tiers), provider
    assert not old & set(model["agents"].values())


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

def test_declared_subagents_get_their_tier_models():
    agents = generated(PERSONAL)["agents"]
    assert agents["commit"]["model"] == "github-copilot/claude-sonnet-5.5#medium"
    assert agents["review"]["model"] == "github-copilot/gpt-6-astra"
    work = generated(WORK)["agents"]
    assert work["commit"]["model"] == "amazon-bedrock/global.anthropic.claude-sonnet-5-5#low"
    assert work["review"]["model"] == "amazon-bedrock/global.openai.gpt-6-sol"


@pytest.mark.parametrize(
    ("common", "commit", "worker"),
    [
        (
            PERSONAL,
            "github-copilot/claude-sonnet-5.5#medium",
            "github-copilot/claude-sonnet-5.5#medium",
        ),
        (
            WORK,
            "amazon-bedrock/global.anthropic.claude-sonnet-5-5#low",
            "amazon-bedrock/global.anthropic.claude-sonnet-5-5#medium",
        ),
    ],
    ids=["personal", "work"],
)
def test_commit_and_fleet_worker_use_sonnet(common, commit, worker):
    """commit は haiku では書式が崩れる (commit-review-agents 記録 E4-E6)。
    fleet-worker は haiku では難しめの課題を落とし、opus と sonnet 5.5 は差が無い
    (docs/research/opencode/tier-models.md)。
    """
    assert common["opencode"]["model"]["agents"]["commit"] == "routine"
    assert common["opencode"]["model"]["agents"]["fleet-worker"] == "worker"
    agents = generated(common)["agents"]
    assert agents["commit"]["model"] == commit
    assert agents["fleet-worker"]["model"] == worker


def test_assigned_agents_are_subagents():
    """★主エージェントは選んでもモデルが変わらない (実測)。割り当ては子エージェントに限る。"""
    agents = generated(PERSONAL)["agents"]
    for name in PERSONAL["opencode"]["model"]["agents"]:
        assert agents[name].get("mode") == "subagent", name


# ---------------------------------------------------------------------------
# V2 形式のエージェント定義 ([opencode.agents])
# ---------------------------------------------------------------------------

def rules_of(agent: str) -> list[dict]:
    return generated(PERSONAL)["agents"][agent]["permissions"]


def test_review_agent_only_reads():
    """★git diff / git status も外部コマンドを実行しうるので shell は丸ごと塞ぐ。"""
    rules = rules_of("review")
    for action in ("edit", "shell", "subagent"):
        assert {"action": action, "resource": "*", "effect": "deny"} in rules


def test_v2_agents_do_not_leak_into_the_v1_key():
    config = generated(PERSONAL)
    assert not {"commit", "review"} & set(config["agent"])


def test_v2_agent_definitions_keep_unmanaged_keys():
    existing = {
        "agents": {"review": {"color": "#123456", "system": "old"}, "mine": {"mode": "all"}}
    }
    out = generated(PERSONAL, existing)["agents"]
    assert out["review"]["color"] == "#123456"
    assert out["review"]["system"] != "old", "宣言したキーは差し替える"
    assert out["mine"] == {"mode": "all"}
    assert generated(PERSONAL, generated(PERSONAL)) == generated(PERSONAL), "冪等"


def test_system_prompt_is_trimmed():
    system = generated(PERSONAL)["agents"]["commit"]["system"]
    assert system == system.strip()


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"model": "x/y"}, "model"),
        ({"permission": "allow"}, "permission"),
        ({"description": ""}, "description"),
        ({"permissions": [{"action": "shell", "resource": "*"}]}, "effect"),
        ({"permissions": [{"action": "shell", "resource": "*", "effect": "block"}]}, "effect"),
    ],
    ids=["model", "v1-key", "no-description", "missing-effect", "bad-effect"],
)
def test_invalid_v2_agent_stops_apply(patch, message):
    common = copy.deepcopy(PERSONAL)
    common["opencode"]["agents"]["review"].update(patch)
    with pytest.raises(ValueError) as excinfo:
        generated(common)
    assert message in str(excinfo.value)


def test_v2_agent_cannot_shadow_a_v1_agent():
    common = copy.deepcopy(PERSONAL)
    common["opencode"]["agents"]["bypass"] = {"description": "x"}
    with pytest.raises(ValueError, match="重複"):
        generated(common)


# ---------------------------------------------------------------------------
# 並列作業 (/fleet)
# ---------------------------------------------------------------------------

def test_fleet_worker_is_a_subagent():
    assert generated(PERSONAL)["agents"]["fleet-worker"]["mode"] == "subagent"


def test_fleet_worker_keeps_the_global_shell_rules():
    """★承認制のまま。shell を丸ごと allow にする規則を持たない。"""
    rules = rules_of("fleet-worker")
    allows = [r for r in rules if r["action"] in ("shell", "edit", "*") and r["effect"] == "allow"]
    assert not allows


def test_fleet_worker_system_covers_callers_scratch_files_and_reads():
    """呼び出し元への影響・一時ファイルの置き場・道具での読み書きを指示し、報告に含めさせる。

    see docs/research/opencode/fleet-worker-instructions.md
    """
    system = generated(PERSONAL)["agents"]["fleet-worker"]["system"]
    assert system == system.strip()
    flat = "".join(line.strip() for line in system.splitlines())
    assert "呼び出し元を探して読み" in flat
    assert "- 呼び出し元への影響" in system, "報告の項目"
    assert "作業ツリーの .tmp/ の下" in flat
    assert "作業ツリーの外" in flat
    assert "read / glob / grep ツール" in flat
    assert "渡された形のまま単独で実行する" in flat


def test_fleet_command_acts_on_reported_caller_impact():
    template = generated(PERSONAL)["commands"]["fleet"]["template"]
    assert "呼び出し元への影響" in template


@pytest.mark.parametrize("command", ["add", "commit", "stash", "checkout", "restore", "reset"])
def test_fleet_worker_cannot_touch_the_shared_git_state(command):
    """作業ツリーをほかの作業役と共有しているので、git の状態を変えさせない。"""
    rules = rules_of("fleet-worker")
    assert {"action": "shell", "resource": f"git {command} *", "effect": "deny"} in rules


def test_fleet_command_runs_in_the_current_session():
    """★子エージェントは子を起動できない。取りまとめ役は今のセッションで動かす。"""
    fleet = generated(PERSONAL)["commands"]["fleet"]
    assert fleet["subagent"] is False
    assert "$ARGUMENTS" in fleet["template"]
    assert "fleet-worker" in fleet["template"]


def test_fleet_command_names_only_defined_agents():
    template = generated(PERSONAL)["commands"]["fleet"]["template"]
    agents = set(generated(PERSONAL)["agents"]) | {"explore", "general", "build", "plan"}
    for name in ("fleet-worker", "explore", "review"):
        if name in template:
            assert name in agents, name


def test_unmanaged_commands_survive():
    existing = {"commands": {"mine": {"template": "x"}, "fleet": {"model": "p/m"}}}
    out = generated(PERSONAL, existing)["commands"]
    assert out["mine"] == {"template": "x"}
    assert out["fleet"]["model"] == "p/m", "宣言していないキーは残す"
    assert generated(PERSONAL, generated(PERSONAL)) == generated(PERSONAL), "冪等"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"template": "Review:\n!`git diff`"}, "シェル"),
        ({"template": ""}, "template"),
        ({"model": "p/m"}, "model"),
        ({"subagent": "yes"}, "subagent"),
    ],
    ids=["shell-block", "empty", "model", "subagent-type"],
)
def test_invalid_command_stops_apply(patch, message):
    common = copy.deepcopy(PERSONAL)
    common["opencode"]["commands"]["fleet"].update(patch)
    with pytest.raises(ValueError) as excinfo:
        generated(common)
    assert message in str(excinfo.value)


def test_assignment_goes_to_v2_agents_with_variant():
    """★V1 の agent キーでは #variant 付きの指定が黙って無視される (実測)。"""
    out = generated(with_agents(WORK, {"explore": "worker", "plan": "deep"}))
    agents = out["agents"]
    sonnet = "amazon-bedrock/global.anthropic.claude-sonnet-5-5#medium"
    assert agents["explore"] == {"model": sonnet}
    assert agents["plan"] == {"model": "amazon-bedrock/global.anthropic.claude-opus-5-5#high"}
    assert "explore" not in out["agent"] and "plan" not in out["agent"]


def test_unassigning_removes_only_managed_models():
    assigned = generated(with_agents(PERSONAL, {"explore": "worker", "plan": "deep"}))
    assigned["agents"]["plan"]["color"] = "#ff6b6b"
    assigned["agents"]["mine"] = {"model": "github-copilot/gpt-5-mini"}
    out = generated(PERSONAL, assigned)["agents"]
    assert "explore" not in out, "model しか無いエントリは消す"
    assert out["plan"] == {"color": "#ff6b6b"}
    assert out["mine"] == {"model": "github-copilot/gpt-5-mini"}, "手で書いたモデルは残す"


def test_switching_provider_rewrites_assigned_models():
    personal = generated(with_agents(PERSONAL, {"explore": "worker"}))
    work = generated(with_agents(WORK, {"explore": "worker"}), personal)
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
        (lambda c: c["opencode"]["model"].update(agents={"bypass": "deep"}), "bypass"),
        (lambda c: c["opencode"]["model"]["agents"].update(commit="standard"), "standard"),
        (lambda c: c["opencode"]["model"]["agents"].update({"fleet-worker": "light"}), "light"),
        (lambda c: c["opencode"]["model"].update(agents={"explore": "heavy"}), "heavy"),
    ],
    ids=[
        "unknown-tier",
        "unknown-provider",
        "default-variant",
        "v1-agent",
        "old-standard",
        "old-light",
        "old-heavy",
    ],
)
def test_invalid_model_config_stops_apply(mutate, message):
    common = copy.deepcopy(PERSONAL)
    mutate(common)
    with pytest.raises(SystemExit) as excinfo:
        generated(common)
    assert message in str(excinfo.value)
