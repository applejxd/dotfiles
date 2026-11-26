"""pi-subagents (stock の pi) の設定の描画を検証する。

~/.pi/agent/extensions/subagent/config.json の modify_ スクリプト・settings の subagents.agentOverrides・
permission の方針を、chezmoi execute-template で描画して確かめる。
実機の chezmoi apply は行わない。
see docs/spec/agent-config-generation.md#pi-subagents-の設定
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_SRC = ROOT / "home"
SUBAGENT_DIR = ".pi/agent/extensions/subagent"
CONFIG_MODIFY = (
    HOME_SRC / "dot_pi" / "agent" / "extensions" / "subagent" / "modify_config.json.py.tmpl"
)
SETTINGS_MODIFY = HOME_SRC / "dot_pi" / "agent" / "modify_settings.json.py.tmpl"
POLICY = HOME_SRC / ".chezmoitemplates" / "pi-permission-policy.json"
READ_ONLY = {"read", "grep", "find", "ls", "contact_supervisor"}
WRITE_TOOLS = {"bash", "write", "edit"}


def render(template: str, home: Path, *, username: str = "tester", data: dict | None = None) -> str:
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = {
        "chezmoi": {
            "os": "linux",
            "username": username,
            "kernel": {"osrelease": "Linux"},
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    context.update(data or {})
    wrapped = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + template + "{{ end }}"
    )
    env = dict(os.environ)
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=wrapped,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def script(src: Path, tmp_path: Path, name: str, username: str = "tester", *, data=None) -> Path:
    # tester は会社 PC (is-work)、applejxd は家の機
    out = tmp_path / name
    out.write_text(
        render(src.read_text(encoding="utf-8"), tmp_path, username=username, data=data),
        encoding="utf-8",
    )
    return out


def run(path: Path, stdin: str) -> str:
    result = subprocess.run(
        [sys.executable, str(path)],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


@pytest.fixture
def config_script(tmp_path: Path) -> Path:
    return script(CONFIG_MODIFY, tmp_path, "modify_subagent_config.py")


@pytest.fixture
def settings_script(tmp_path: Path) -> Path:
    return script(SETTINGS_MODIFY, tmp_path, "modify_settings.py")


@pytest.fixture
def work_copilot_settings_script(tmp_path: Path) -> Path:
    return script(SETTINGS_MODIFY, tmp_path, "modify_work_copilot.py", data={"work_pi_profile": "copilot"})


@pytest.fixture
def home_settings_script(tmp_path: Path) -> Path:
    return script(SETTINGS_MODIFY, tmp_path, "modify_settings_home.py", "applejxd")


# --- config.json --------------------------------------------------------


def test_config_from_empty_input(config_script):
    out = json.loads(run(config_script, ""))
    assert out == {
        "forceTopLevelAsync": True,
        "worktreeProvider": "native",
        "maxActiveAsyncRunsPerSession": 0,  # 0 = 無制限
        "maxSubagentDepth": 8,
        "maxSubagentSpawnsPerRun": 10000,
        "globalConcurrencyLimit": 1000,
        "maxSubagentSpawnsPerSession": 0,  # 0 = 無制限
        "parallel": {"maxTasks": 64, "concurrency": 16},  # tasks / chain の並列グループ (既定は 8・4)
    }


def test_config_forces_top_level_async_and_keeps_user_values(config_script):
    existing = {
        "forceTopLevelAsync": False,
        "worktreeProvider": "auto",
        "maxActiveAsyncRunsPerSession": 2,
        "timeoutMs": 3600000,
        "parallel": {"maxTasks": 12},
    }
    out = json.loads(run(config_script, json.dumps(existing)))
    assert out["forceTopLevelAsync"] is True  # 強制 (false にしても戻る)
    assert out["worktreeProvider"] == "auto"  # 無いときだけ補う
    assert out["maxActiveAsyncRunsPerSession"] == 2
    assert out["timeoutMs"] == 3600000  # 利用者のキーは保つ
    assert out["parallel"] == {"maxTasks": 12, "concurrency": 16}  # 利用者の値は保ち、無いキーだけ補う
    assert out["maxSubagentDepth"] == 8  # 無かったものは補う


def test_config_moves_the_old_default_limits_to_the_new_ones(config_script):
    """前の既定 (4・1・32) のままなら、利用者が選んだ値ではないので、上限を外した値へ移す。"""
    old = {"maxActiveAsyncRunsPerSession": 4, "maxSubagentDepth": 1, "maxSubagentSpawnsPerRun": 32}
    out = json.loads(run(config_script, json.dumps(old)))
    assert out["maxActiveAsyncRunsPerSession"] == 0
    assert out["maxSubagentDepth"] == 8
    assert out["maxSubagentSpawnsPerRun"] == 10000


def test_config_keeps_limits_the_user_chose(config_script):
    chosen = {"maxActiveAsyncRunsPerSession": 2, "maxSubagentDepth": 3, "maxSubagentSpawnsPerRun": 50}
    out = json.loads(run(config_script, json.dumps(chosen)))
    assert {k: out[k] for k in chosen} == chosen


def test_config_limits_are_valid_for_pi_subagents(config_script):
    """pi-subagents の設定の検証 (docs/configuration.md): 正の整数 (0 が許されるのは同時数と累計だけ)。"""
    out = json.loads(run(config_script, ""))
    for key in ("maxSubagentSpawnsPerRun", "globalConcurrencyLimit"):
        assert isinstance(out[key], int) and out[key] > 0, key  # 0 は使えない (読み込みが失敗・無視される)
    for key in ("maxActiveAsyncRunsPerSession", "maxSubagentSpawnsPerSession", "maxSubagentDepth"):
        assert isinstance(out[key], int) and out[key] >= 0, key


def test_config_fills_parallel_limits_key_by_key(config_script):
    out = json.loads(run(config_script, json.dumps({"parallel": {"maxTasks": 12}})))
    assert out["parallel"] == {"maxTasks": 12, "concurrency": 16}  # 利用者の値は保ち、無いキーだけ補う
    out = json.loads(run(config_script, json.dumps({"parallel": "x"})))
    assert out["parallel"] == "x"  # 壊れた値には触らない


def test_config_is_idempotent_and_leaves_broken_json(config_script):
    first = run(config_script, '{"x": 1}')
    assert run(config_script, first) == first
    assert run(config_script, "{broken") == "{broken"
    assert run(config_script, "[1]") == "[1]"


# --- profile ごとの配備 -------------------------------------------------


def lines(text: str) -> set[str]:
    return {x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")}




def test_stock_ignore_keeps_subagent_config(tmp_path):
    rendered = lines(
        render(
            (HOME_SRC / ".chezmoiignore.tmpl").read_text(encoding="utf-8"),
            tmp_path,
        )
    )
    assert SUBAGENT_DIR not in rendered
    assert f"{SUBAGENT_DIR}/**" not in rendered
    assert not any(e.startswith(f"{SUBAGENT_DIR}/") for e in rendered)




# --- settings の subagents.agentOverrides -------------------------------


def test_settings_overrides_scout_and_oracle_read_only(settings_script):
    out = json.loads(run(settings_script, "{}"))
    overrides = out["subagents"]["agentOverrides"]
    # reviewer・worker は変えない。researcher・evidence-auditor は検索の MCP を足す (下の試験)
    assert set(overrides) == {"scout", "oracle", "researcher", "evidence-auditor"}
    for name in ("scout", "oracle"):
        tools = set(overrides[name]["tools"])
        assert not tools & WRITE_TOOLS, name
        assert tools <= READ_ONLY, name
    assert overrides["oracle"]["tools"] == ["read", "grep", "find", "ls"]
    assert "contact_supervisor" in overrides["scout"]["tools"]  # 親への問い合わせは残す


@pytest.mark.parametrize(
    ("username", "servers"),
    [("tester", ["agentcore-websearch", "webfetch"]), ("applejxd", ["websearch"])],
)
def test_settings_gives_search_agents_the_machines_search_mcp(tmp_path, username, servers):
    """検索の子は、機の検索・取得の MCP を mcp: で受け取る。組み込みの web_search 系 (pi-web-access) は入れない。"""
    path = script(SETTINGS_MODIFY, tmp_path, "modify_settings.py", username)
    overrides = json.loads(run(path, "{}"))["subagents"]["agentOverrides"]
    mcp = [f"mcp:{server}" for server in servers]
    assert overrides["researcher"]["tools"] == ["read", "write", *mcp]
    assert overrides["evidence-auditor"]["tools"] == ["read", *mcp]
    for name in ("researcher", "evidence-auditor"):
        assert not {"web_search", "fetch_content", "source_check"} & set(overrides[name]["tools"])
        assert not {"bash", "edit"} & set(overrides[name]["tools"]), name


# 組み込みの prompt が勧める pi-web-access のツール。stock の pi には無い
MISSING_TOOLS = ("fetch_content", "get_search_content", "queries", "workflow")


@pytest.mark.parametrize("username", ["tester", "applejxd"])
@pytest.mark.parametrize("name", ["researcher", "evidence-auditor"])
def test_settings_replaces_the_search_agent_prompt_with_the_machines_tool_names(
    tmp_path, username, name
):
    """組み込みの prompt は存在しないツール (fetch_content など) を勧める。機のツールに合わせた文面で置き換える。"""
    path = script(SETTINGS_MODIFY, tmp_path, "modify_settings.py", username)
    prompt = json.loads(run(path, "{}"))["subagents"]["agentOverrides"][name]["systemPrompt"]
    assert "{{" not in prompt and "}}" not in prompt  # 描画されている
    for missing in MISSING_TOOLS:
        assert missing not in prompt, missing
    # source_check は「無い」と書く 1 か所だけ (使えと言わない)
    assert prompt.count("source_check") == 1 and "no `source_check` tool" in prompt
    if username == "applejxd":
        assert "`mcp__websearch__web_search`" in prompt
        assert "`mcp__websearch__fetch_page`" in prompt
        assert "webfetch" not in prompt
    else:
        # 会社 PC も pi 組み込みの MCP の登録名 (mcp__<server>__<tool>) で指す
        assert "`mcp__webfetch__fetch`" in prompt
        assert "`mcp__agentcore_websearch__web_search_tool__WebSearch`" in prompt
        assert "mcp__websearch__" not in prompt
        assert "adapter" not in prompt.lower()
    # 成果物の様式は組み込みと同じ (researcher)
    if name == "researcher":
        assert "# Research: [topic]" in prompt


LEGACY_WORK_TOOLS = {
    "researcher": ["read", "write", "mcp:agentcore-websearch"],
    "evidence-auditor": ["read", "mcp:agentcore-websearch"],
}


def _overrides(output: str) -> dict:
    return json.loads(output)["subagents"]["agentOverrides"]


@pytest.mark.parametrize("name", ["researcher", "evidence-auditor"])
def test_settings_moves_the_old_default_tools_to_the_new_default_on_the_work_pc(tmp_path, name):
    """取得の MCP を足す前に apply 済みの会社 PC でも、子に webfetch が渡る。旧既定のままなら新既定へ移す (再適用しても同じ)。"""
    path = script(SETTINGS_MODIFY, tmp_path, "modify_settings.py", "tester")
    existing = {"subagents": {"agentOverrides": {name: {"tools": list(LEGACY_WORK_TOOLS[name])}}}}
    first = run(path, json.dumps(existing))
    assert "mcp:webfetch" in _overrides(first)[name]["tools"]
    assert _overrides(first)[name]["tools"] == _overrides(run(path, "{}"))[name]["tools"]
    assert run(path, first) == first


@pytest.mark.parametrize("name", ["researcher", "evidence-auditor"])
def test_settings_keeps_tools_the_user_changed_and_does_not_migrate_the_home_machine(tmp_path, name):
    work = script(SETTINGS_MODIFY, tmp_path, "modify_settings_work.py", "tester")
    custom = [*LEGACY_WORK_TOOLS[name], "grep"]  # 旧既定と違う配列は利用者の選択として保つ
    existing = {"subagents": {"agentOverrides": {name: {"tools": custom}}}}
    assert _overrides(run(work, json.dumps(existing)))[name]["tools"] == custom
    # 家の機の既定は変わっていない。会社 PC の旧既定と同じ配列があっても、家では移さない
    home = script(SETTINGS_MODIFY, tmp_path, "modify_settings_home.py", "applejxd")
    legacy = {"subagents": {"agentOverrides": {name: {"tools": list(LEGACY_WORK_TOOLS[name])}}}}
    assert _overrides(run(home, json.dumps(legacy)))[name]["tools"] == LEGACY_WORK_TOOLS[name]


def test_settings_manages_the_search_agent_prompt_but_keeps_other_user_keys(tmp_path):
    """systemPrompt はこの repo が管理する (古い文面を残さない)。同じ役の他のキー (model など) は保つ。"""
    path = script(SETTINGS_MODIFY, tmp_path, "modify_settings.py", "applejxd")
    existing = {
        "subagents": {
            "agentOverrides": {"researcher": {"systemPrompt": "old", "model": "a/b", "tools": ["read"]}}
        }
    }
    first = run(path, json.dumps(existing))
    researcher = json.loads(first)["subagents"]["agentOverrides"]["researcher"]
    assert researcher["systemPrompt"] != "old" and "research subagent" in researcher["systemPrompt"]
    assert researcher["model"] == "a/b" and researcher["tools"] == ["read"]
    assert run(path, first) == first


def test_settings_keeps_user_overrides(settings_script):
    existing = {
        "theme": "dark",
        "subagents": {
            "defaultModel": "x/y",
            "agentOverrides": {
                "reviewer": {"description": "mine"},
                "scout": {"tools": ["read"], "model": "a/b"},
                "oracle": {"thinking": "high"},
            },
        },
    }
    out = json.loads(run(settings_script, json.dumps(existing)))
    sub = out["subagents"]
    assert out["theme"] == "dark"
    assert sub["defaultModel"] == "x/y"
    assert sub["agentOverrides"]["reviewer"] == {"description": "mine"}
    assert sub["agentOverrides"]["scout"] == {
        "tools": ["read"],
        "model": "a/b",
    }  # 利用者の tools を保つ
    assert sub["agentOverrides"]["oracle"] == {
        "thinking": "high",
        "tools": ["read", "grep", "find", "ls"],
    }


def by_provider(out: dict) -> dict:
    return out["subagents"]["agentOverridesByProvider"]


def test_home_settings_assigns_models_by_role_for_copilot(home_settings_script):
    out = json.loads(run(home_settings_script, "{}"))
    models = {n: e["model"] for n, e in by_provider(out)["github-copilot"].items()}
    # 実装は Sonnet、レビュー・証拠監査は Sol、調査・delegate は Neon、判定は Carbon (すべて Copilot 経由)
    assert models == {
        "scout": "github-copilot/gemini-4-neon:medium",
        "researcher": "github-copilot/gemini-4-neon:xhigh",
        "worker": "github-copilot/claude-sonnet-5.5:high",
        "reviewer": "github-copilot/gpt-6.2-sol:high",
        "evidence-auditor": "github-copilot/gpt-6.2-sol:high",
        "oracle": "github-copilot/gemini-4-carbon:high",
        "delegate": "github-copilot/gemini-4-neon:high",
    }
    assert "advisor" not in models  # advisor は oracle の別名。設定は正規名の oracle に書く
    assert all(m.startswith("github-copilot/") for m in models.values())


def test_work_settings_assigns_models_by_role_for_copilot(work_copilot_settings_script):
    first = run(work_copilot_settings_script, "{}")
    models = {n: e["model"] for n, e in by_provider(json.loads(first))["github-copilot"].items()}
    assert models == {
        "scout": "github-copilot/claude-sonnet-5.5:low",
        "researcher": "github-copilot/claude-sonnet-5.5:medium",
        "worker": "github-copilot/claude-sonnet-5.5:medium",
        "reviewer": "github-copilot/gpt-6.2-sol:high",
        "evidence-auditor": "github-copilot/gpt-6.2-sol:high",
        "oracle": "github-copilot/gpt-6.2-sol:high",
    }
    assert run(work_copilot_settings_script, first) == first


def test_settings_assigns_models_by_role_for_bedrock(settings_script):
    out = json.loads(run(settings_script, "{}"))
    models = {n: e["model"] for n, e in by_provider(out)["amazon-bedrock"].items()}
    assert models["worker"] == "amazon-bedrock/us.anthropic.claude-sonnet-5-5:medium"
    assert models["scout"] == "amazon-bedrock/us.anthropic.claude-sonnet-5-5:low"
    assert models["researcher"] == "amazon-bedrock/us.anthropic.claude-sonnet-5-5:medium"
    assert models["reviewer"] == "amazon-bedrock/us.openai.gpt-6.2-sol:high"
    assert models["evidence-auditor"] == models["reviewer"]
    # Opus は高価でカタログでは plan 役の既定。指示なしに自律で起動する oracle には使わない
    assert "opus" not in models["oracle"]
    assert models["oracle"] == models["reviewer"]
    assert all(m.startswith("amazon-bedrock/us.") for m in models.values())  # global. は使わない
    assert set(models) == {"scout", "researcher", "worker", "reviewer", "evidence-auditor", "oracle"}  # delegate は親を継ぐ


def test_home_settings_keeps_both_provider_layers(home_settings_script):
    out = json.loads(run(home_settings_script, "{}"))
    assert set(by_provider(out)) == {"github-copilot", "amazon-bedrock"}
    assert all("model" not in e for e in out["subagents"]["agentOverrides"].values())


@pytest.mark.parametrize("value", ["", "Bedrock", "other", True, ["bedrock"]])
def test_work_settings_rejects_unknown_profile(tmp_path, value):
    with pytest.raises(AssertionError, match="work_pi_profile は bedrock または copilot"):
        script(SETTINGS_MODIFY, tmp_path, "invalid.py", data={"work_pi_profile": value})


def test_work_settings_switches_profiles_without_leaving_inactive_defaults(settings_script, work_copilot_settings_script):
    bedrock = run(settings_script, "{}")
    switched = run(work_copilot_settings_script, bedrock)
    out = json.loads(switched)
    assert out["defaultProvider"] == "github-copilot"
    assert out["defaultModel"] == "claude-sonnet-5.5"
    assert out["defaultThinkingLevel"] == "medium"
    assert out["enabledModels"] == ["github-copilot/claude-sonnet-5.5", "github-copilot/*"]
    assert set(by_provider(out)) == {"github-copilot"}
    assert run(work_copilot_settings_script, switched) == switched
    restored = run(settings_script, switched)
    restored_data = json.loads(restored)
    assert set(restored_data.pop("dotfilesWorkPiModels")) == {"github-copilot"}
    assert restored_data == json.loads(bedrock)
    assert run(settings_script, restored) == restored


def test_work_settings_restores_custom_parent_and_candidates_on_round_trip(settings_script, work_copilot_settings_script):
    copilot_models = ["github-copilot/claude-opus-5.5:low", "github-copilot/gpt-6.2-sol"]
    existing = {
        "defaultProvider": "github-copilot",
        "defaultModel": "claude-opus-5.5",
        "defaultThinkingLevel": "low",
        "enabledModels": [*copilot_models, "openrouter/*"],
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {"delegate": {"model": "github-copilot/gemini-4-neon:high"}},
            },
        },
    }
    bedrock = run(settings_script, json.dumps(existing))
    out = json.loads(bedrock)
    assert all(p.startswith("amazon-bedrock/") for p in out["enabledModels"])
    assert out["dotfilesWorkPiModels"]["unscopedEnabledModels"] == ["openrouter/*"]
    assert out["dotfilesWorkPiModels"]["github-copilot"]["enabledModels"] == copilot_models
    assert by_provider(out)["github-copilot"] == existing["subagents"]["agentOverridesByProvider"]["github-copilot"]
    restored = run(work_copilot_settings_script, bedrock)
    out = json.loads(restored)
    assert out["enabledModels"] == copilot_models
    for key in ("defaultProvider", "defaultModel", "defaultThinkingLevel"):
        assert out[key] == existing[key]
    assert by_provider(out)["github-copilot"]["delegate"]["model"] == "github-copilot/gemini-4-neon:high"
    assert run(work_copilot_settings_script, restored) == restored


def test_work_settings_keeps_thinking_without_a_saved_model(settings_script, work_copilot_settings_script):
    existing = json.dumps({"defaultProvider": "amazon-bedrock", "defaultThinkingLevel": "high"})
    switched = run(work_copilot_settings_script, existing)
    for source in (existing, switched):
        out = json.loads(run(settings_script, source))
        assert out["defaultModel"] == "us.anthropic.claude-sonnet-5-5"
        assert out["defaultThinkingLevel"] == "high"


def test_work_settings_keeps_active_choices_and_inactive_custom_roles(work_copilot_settings_script):
    existing = {
        "defaultProvider": "github-copilot",
        "defaultModel": "claude-opus-5.5",
        "defaultThinkingLevel": "low",
        "enabledModels": ["amazon-bedrock/*", "github-copilot/claude-opus-5.5:low", "*", "github-copilot/*"],
        "subagents": {"agentOverridesByProvider": {"amazon-bedrock": {
            "oracle": {"model": "amazon-bedrock/us.openai.gpt-6.1-sol:medium"},
            "reviewer": {"model": "amazon-bedrock/us.openai.gpt-6.1-sol:high", "description": "mine"},
        }}},
    }
    out = json.loads(run(work_copilot_settings_script, json.dumps(existing)))
    assert out["defaultModel"] == "claude-opus-5.5"
    assert out["defaultThinkingLevel"] == "low"
    assert out["enabledModels"] == ["github-copilot/claude-opus-5.5:low", "github-copilot/*"]
    assert by_provider(out)["amazon-bedrock"] == {
        "oracle": {"model": "amazon-bedrock/us.openai.gpt-6.1-sol:medium"},
        "reviewer": {"description": "mine"},
    }


def test_settings_moves_the_old_oracle_default_but_keeps_a_users_choice(home_settings_script):
    """前の既定 (Sonnet の xhigh) は Carbon の high へ移す。利用者が別のモデルにしていれば保つ。"""
    old = {
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {"oracle": {"model": "github-copilot/claude-sonnet-5.5:xhigh"}},
                "amazon-bedrock": {"oracle": {"model": "amazon-bedrock/us.anthropic.claude-opus-5-5:high"}},
            }
        }
    }
    out = json.loads(run(home_settings_script, json.dumps(old)))
    assert by_provider(out)["github-copilot"]["oracle"]["model"] == "github-copilot/gemini-4-carbon:high"
    assert by_provider(out)["amazon-bedrock"]["oracle"]["model"] == "amazon-bedrock/us.anthropic.claude-opus-5-5:high"


def test_settings_moves_the_previous_copilot_gpt_default_and_keeps_custom_bedrock(work_copilot_settings_script):
    """Copilot の 6.1 Sol は役ごとの既定へ移し、Bedrock の個別設定は保つ。"""
    old = {
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {
                    "reviewer": {"model": "github-copilot/gpt-6.1-sol:high"},
                    "evidence-auditor": {"model": "github-copilot/gpt-6.1-sol:high"},
                    "oracle": {"model": "github-copilot/gpt-6.1-sol:xhigh"},  # 利用者が思考の深さを変えた
                },
                "amazon-bedrock": {"reviewer": {"model": "amazon-bedrock/us.openai.gpt-6.1-sol:medium"}},
            }
        }
    }
    out = json.loads(run(work_copilot_settings_script, json.dumps(old)))
    copilot = by_provider(out)["github-copilot"]
    assert copilot["reviewer"]["model"] == "github-copilot/gpt-6.2-sol:high"
    assert copilot["evidence-auditor"]["model"] == "github-copilot/gpt-6.2-sol:high"
    assert copilot["oracle"]["model"] == "github-copilot/gpt-6.1-sol:xhigh"  # 利用者の選択を保つ
    assert by_provider(out)["amazon-bedrock"]["reviewer"]["model"] == "amazon-bedrock/us.openai.gpt-6.1-sol:medium"


@pytest.mark.parametrize("role", ["reviewer", "evidence-auditor", "oracle"])
def test_settings_migrates_only_the_work_bedrock_sol_default(settings_script, home_settings_script, role):
    for model, expected in (
        ("amazon-bedrock/us.openai.gpt-6.1-sol:high", "amazon-bedrock/us.openai.gpt-6.2-sol:high"),
        ("amazon-bedrock/us.openai.gpt-6.1-sol:medium", "amazon-bedrock/us.openai.gpt-6.1-sol:medium"),
        ("amazon-bedrock/global.openai.gpt-6.1-sol:high", "amazon-bedrock/global.openai.gpt-6.1-sol:high"),
    ):
        existing = {
            "subagents": {
                "agentOverridesByProvider": {
                    "amazon-bedrock": {role: {"model": model, "description": "mine"}},
                }
            }
        }
        first = run(settings_script, json.dumps(existing))
        assert by_provider(json.loads(first))["amazon-bedrock"][role] == {"model": expected, "description": "mine"}
        assert run(settings_script, first) == first
        home = json.loads(run(home_settings_script, json.dumps(existing)))
        assert by_provider(home)["amazon-bedrock"][role] == {"model": model, "description": "mine"}


@pytest.mark.parametrize(
    "role, expected",
    [("evidence-auditor", "github-copilot/gpt-6.2-sol:high"), ("oracle", "github-copilot/gemini-4-carbon:high")],
)
@pytest.mark.parametrize("version", ["6.1", "6.2"])
def test_home_settings_moves_gpt_audit_defaults_to_the_new_default(home_settings_script, role, expected, version):
    """登録済みの旧既定だけ移し、同じ役の他のキーと Bedrock の値は保つ。再適用でも変わらない。"""
    bedrock = {
        name: {"model": "amazon-bedrock/us.openai.gpt-6.1-sol:medium"}
        for name in ("reviewer", "evidence-auditor", "oracle")
    }
    old = {
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {
                    role: {"model": f"github-copilot/gpt-{version}-sol:high", "description": "mine"},
                },
                "amazon-bedrock": bedrock,
            }
        }
    }
    first = run(home_settings_script, json.dumps(old))
    layers = by_provider(json.loads(first))
    assert layers["github-copilot"][role] == {"model": expected, "description": "mine"}
    for name, entry in bedrock.items():
        assert layers["amazon-bedrock"][name] == entry
    assert run(home_settings_script, first) == first


def test_home_settings_moves_the_previous_copilot_assignment_to_neon_and_sol(home_settings_script):
    """前の既定 (Sonnet の low・medium、証拠監査の Carbon medium) は、役ごとの新既定へ移す。他の値は保つ。"""
    old = {
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {
                    "scout": {"model": "github-copilot/claude-sonnet-5.5:low"},
                    "researcher": {"model": "github-copilot/claude-sonnet-5.5:medium"},
                    "worker": {"model": "github-copilot/claude-sonnet-5.5:medium", "thinking": "low"},
                    "evidence-auditor": {"model": "github-copilot/gemini-4-carbon:medium"},
                    "oracle": {"model": "github-copilot/gemini-4-carbon:high"},
                },
            }
        }
    }
    first = run(home_settings_script, json.dumps(old))
    copilot = by_provider(json.loads(first))["github-copilot"]
    assert copilot["scout"]["model"] == "github-copilot/gemini-4-neon:medium"
    assert copilot["researcher"]["model"] == "github-copilot/gemini-4-neon:xhigh"
    assert copilot["worker"] == {"model": "github-copilot/claude-sonnet-5.5:high", "thinking": "low"}
    assert copilot["evidence-auditor"]["model"] == "github-copilot/gpt-6.2-sol:high"
    assert copilot["oracle"]["model"] == "github-copilot/gemini-4-carbon:high"
    assert copilot["delegate"]["model"] == "github-copilot/gemini-4-neon:high"  # 無かったものは補う
    assert run(home_settings_script, first) == first


def test_home_settings_keeps_a_users_choice_for_neon_roles(home_settings_script):
    chosen = {
        "scout": {"model": "github-copilot/claude-sonnet-5.5:medium"},
        "researcher": {"model": "github-copilot/gemini-4-neon:high"},
        "worker": {"model": "github-copilot/claude-sonnet-5.5:xhigh"},
        "delegate": {"model": "github-copilot/gpt-6.2-sol:high"},
    }
    existing = {"subagents": {"agentOverridesByProvider": {"github-copilot": chosen}}}
    layer = by_provider(json.loads(run(home_settings_script, json.dumps(existing))))["github-copilot"]
    for name, entry in chosen.items():
        assert layer[name] == entry


@pytest.mark.parametrize("model", ["inherit", "github-copilot/gpt-6.2-sol:medium"])
def test_home_delegate_default_keeps_an_explicit_common_model(home_settings_script, model):
    existing = {"subagents": {"agentOverrides": {"delegate": {"model": model}}}}
    out = json.loads(run(home_settings_script, json.dumps(existing)))
    assert out["subagents"]["agentOverrides"]["delegate"] == {"model": model}
    assert "delegate" not in by_provider(out)["github-copilot"]


@pytest.mark.parametrize("role", ["evidence-auditor", "oracle"])
@pytest.mark.parametrize("model", ["github-copilot/gpt-6.2-sol:medium", "github-copilot/gemini-4-carbon:low", "other/model:high"])
def test_settings_keeps_user_audit_models(work_copilot_settings_script, role, model):
    """モデルや思考の深さを独自に選んだ値は旧既定とみなさない。"""
    existing = {
        "subagents": {
            "agentOverridesByProvider": {"github-copilot": {role: {"model": model}}},
        }
    }
    first = run(work_copilot_settings_script, json.dumps(existing))
    assert by_provider(json.loads(first))["github-copilot"][role]["model"] == model
    assert run(work_copilot_settings_script, first) == first


def test_settings_keeps_a_users_model_and_other_providers(work_copilot_settings_script):
    existing = {
        "subagents": {
            "agentOverridesByProvider": {
                "github-copilot": {"worker": {"model": "x/y"}, "reviewer": {"thinking": "low"}},
                "openrouter": {"worker": {"model": "z/w"}},
            }
        },
    }
    out = json.loads(run(work_copilot_settings_script, json.dumps(existing)))
    layer = by_provider(out)["github-copilot"]
    assert layer["worker"]["model"] == "x/y"  # 利用者の model を保つ
    assert layer["reviewer"]["thinking"] == "low"
    assert layer["reviewer"]["model"] == "github-copilot/gpt-6.2-sol:high"  # 無いものは補う
    assert by_provider(out)["openrouter"] == {"worker": {"model": "z/w"}}  # 知らないプロバイダの層は触らない


HOME_PARENT = {"defaultProvider": "github-copilot", "defaultModel": "gpt-6.2-sol", "defaultThinkingLevel": "high"}
PREVIOUS_PARENT = {"defaultProvider": "github-copilot", "defaultModel": "claude-sonnet-5.5", "defaultThinkingLevel": "xhigh"}


def _parent(out: dict) -> dict:
    return {k: out.get(k) for k in HOME_PARENT}


def test_home_parent_default_is_sol_high_when_unset_or_previous_default(tmp_path):
    """家の機: 親の既定が無いときと、前の既定 (Sonnet・xhigh) のままのときだけ、Sol・high にする。"""
    home = script(SETTINGS_MODIFY, tmp_path, "modify_settings_home.py", "applejxd")
    assert _parent(json.loads(run(home, "{}"))) == HOME_PARENT
    first = run(home, json.dumps(PREVIOUS_PARENT))
    assert _parent(json.loads(first)) == HOME_PARENT
    assert run(home, first) == first


@pytest.mark.parametrize(
    "chosen",
    [
        {**PREVIOUS_PARENT, "defaultThinkingLevel": "high"},  # 思考の深さだけ違う = 利用者の選択
        {**PREVIOUS_PARENT, "defaultModel": "claude-opus-5.5"},
        {"defaultProvider": "github-copilot"},  # 一部だけ書いてある
        {"defaultModel": None},  # 明示の null と未指定を区別する
    ],
)
def test_home_parent_default_keeps_a_users_choice(tmp_path, chosen):
    home = script(SETTINGS_MODIFY, tmp_path, "modify_settings_home.py", "applejxd")
    out = json.loads(run(home, json.dumps(chosen)))
    assert {k: out[k] for k in HOME_PARENT if k in out} == chosen


def test_home_ignores_work_profile(home_settings_script, tmp_path):
    home = script(SETTINGS_MODIFY, tmp_path, "modify_settings_home_profile.py", "applejxd", data={"work_pi_profile": "copilot"})
    assert run(home, "{}") == run(home_settings_script, "{}")


def test_explicit_work_bedrock_matches_the_unset_profile(settings_script, tmp_path):
    explicit = script(SETTINGS_MODIFY, tmp_path, "modify_settings_explicit.py", data={"work_pi_profile": "bedrock"})
    assert run(explicit, "{}") == run(settings_script, "{}")


def test_home_only_enables_copilot_models(tmp_path):
    """家の機は Copilot、会社 PC の既定は Bedrock の候補を出す。"""
    home = script(SETTINGS_MODIFY, tmp_path, "modify_settings_home.py", "applejxd")
    work = script(SETTINGS_MODIFY, tmp_path, "modify_settings_work.py", "tester")
    assert json.loads(run(home, "{}"))["enabledModels"] == ["github-copilot/*"]
    work_settings = json.loads(run(work, "{}"))
    assert work_settings["defaultProvider"] == "amazon-bedrock"
    assert work_settings["defaultModel"] == "us.anthropic.claude-sonnet-5-5"
    assert work_settings["defaultThinkingLevel"] == "medium"
    assert work_settings["enabledModels"] == ["amazon-bedrock/us.anthropic.claude-sonnet-5-5", "amazon-bedrock/*"]


def test_neon_compaction_default_only_applies_at_home(home_settings_script, settings_script):
    neon = "github-copilot/gemini-4-neon"
    work = json.loads(run(settings_script, "{}"))["compaction"]["modelOverrides"]
    home = json.loads(run(home_settings_script, "{}"))["compaction"]["modelOverrides"]
    assert neon not in work
    assert home[neon] == {"reserveTokens": 300000}


def test_assigned_models_never_use_haiku():
    """割り当てるモデル (PROVIDER_AGENT_MODELS) は、Haiku を使わない。"""
    source = (HOME_SRC / ".chezmoitemplates" / "modify_pi_stock_settings.py.tmpl").read_text(encoding="utf-8")
    models = re.findall(r'"((?:github-copilot|amazon-bedrock)/[^"]+)"', source[source.index("PROVIDER_AGENT_MODELS") :])
    assert len(models) >= 12
    for model in models:
        assert "haiku" not in model


def test_settings_is_idempotent(settings_script):
    first = run(settings_script, "{}")
    assert run(settings_script, first) == first


# --- permission の方針 --------------------------------------------------


def test_permission_policy_for_subagents():
    permission = json.loads(POLICY.read_text(encoding="utf-8"))["permission"]
    assert permission["subagent_supervisor"] == "allow"
    assert permission["subagent_launch"] == "allow"  # workflow の子の起動。当面は許可 (ask へ戻せば、子ごとに内容を見られる)
    for name in ("subagent", "subagents_enable", "bg_wait"):
        assert permission[name] == "allow"


# --- agent 定義 (組み込みの写し + permission) --------------------------------

AGENTS_DIR = HOME_SRC / "dot_pi" / "agent" / "agents"
COPIED_AGENTS = ("worker", "reviewer", "scout", "oracle", "researcher", "evidence-auditor")
BUILTIN_AGENTS = Path.home() / ".pi" / "agent" / "npm" / "node_modules" / "pi-subagents" / "agents"


def split_agent(text: str) -> tuple[dict, str]:
    """frontmatter (key: value の行と、インデントした入れ子 1 段) と本文に分ける。yaml に依らない (skip させない)。"""
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    meta: dict = {}
    current = None
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            key, _, value = line.strip().partition(":")
            meta[current][key.strip()] = value.strip()
            continue
        key, _, value = line.partition(":")
        current = key.strip()
        meta[current] = value.strip() if value.strip() else {}
    return meta, text[end + 5 :]


@pytest.mark.parametrize("name", COPIED_AGENTS)
def test_agent_files_deny_outside_the_working_directory(name):
    """作業ツリーの外は、確認 (誰も答えず 5 分止まる) ではなく拒否にする。"""
    meta, _ = split_agent((AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    assert meta["name"] == name
    assert meta["permission"] == {"external_directory": "deny"}


@pytest.mark.parametrize("name", COPIED_AGENTS)
def test_agent_permission_is_valid_for_pi_subagents(name):
    """pi-subagents は permission の値に allow / ask / deny の単一の値だけを許す (入れ子の map は agent 定義が無効になる。
    bash のルールも不可)。実機で確認 (2026-11-10): 入れ子の external_directory は Invalid agent definitions になった。"""
    meta, _ = split_agent((AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    for tool, value in meta["permission"].items():
        assert value in ("allow", "ask", "deny"), (tool, value)
        assert tool != "bash"


@pytest.mark.skipif(not BUILTIN_AGENTS.is_dir(), reason="pi-subagents が入っていない (写しの食い違いは未検査)")
@pytest.mark.parametrize("name", COPIED_AGENTS)
def test_agent_files_match_the_builtin_except_permission(name):
    """組み込みの agent の写しである。permission 以外は無改変 (パッケージの版を上げたら、写し直す)。"""
    ours_meta, ours_body = split_agent((AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    builtin_meta, builtin_body = split_agent((BUILTIN_AGENTS / f"{name}.md").read_text(encoding="utf-8"))
    ours_meta.pop("permission")
    assert ours_meta == builtin_meta
    assert ours_body == builtin_body




# --- 常設の委譲の指示 ---------------------------------------------------------

INSTRUCTIONS = HOME_SRC / ".chezmoitemplates" / "agent-instructions-stock.md"


def test_standing_delegation_instruction_authorizes_the_subagent_roles():
    """pi-subagents は「利用者の指示で委譲を求められたときだけ」子を起動する。常設の指示がその指示に当たる。"""
    text = INSTRUCTIONS.read_text(encoding="utf-8")
    assert "## 委譲（サブエージェント）" in text
    assert "利用者があらかじめ出している指示" in text
    for role in ("scout", "researcher", "reviewer", "worker", "oracle"):
        assert f"`{role}`" in text, role
    assert "`async: true`" in text
    assert "自己申告を信じない" in text
    # 小さな作業は委譲しない (閾値が低くて過剰に委譲しないように、先頭の近くで除外する)。利用者の「委譲しないで」に従う
    assert text.index("小さな作業は委譲しない") < text.index("委譲してよい場面")
    assert "委譲しないで" in text
    # 承認が要る操作は任せない
    assert "`push`" in text and "`chezmoi apply`" in text
