"""pi-subagents (stock の pi) の設定の描画を検証する。

~/.pi/agent/extensions/subagent/config.json の modify_ スクリプト・settings の subagents.agentOverrides・
permission の方針・custom で配らないことを、chezmoi execute-template で描画して確かめる。
実機の chezmoi apply は行わない。
see docs/spec/agent-config-generation.md#pi-subagents-の設定stock
"""

from __future__ import annotations

import json
import os
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


def render(template: str, home: Path, *, profile_env: str | None = "custom") -> str:
    # 引数なしは custom (custom の試験の意味を保つ)。リポジトリの既定は stock (2026-11-10)
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = {
        "chezmoi": {
            "os": "linux",
            "username": "tester",
            "kernel": {"osrelease": "Linux"},
            "homeDir": str(home),
            "workingTree": str(ROOT),
        }
    }
    wrapped = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}" + template + "{{ end }}"
    )
    env = dict(os.environ)
    env.pop("CHEZMOI_PI_PROFILE", None)
    if profile_env is not None:
        env["CHEZMOI_PI_PROFILE"] = profile_env
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


def script(src: Path, tmp_path: Path, name: str) -> Path:
    out = tmp_path / name
    out.write_text(
        render(src.read_text(encoding="utf-8"), tmp_path, profile_env="stock"), encoding="utf-8"
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
    assert out["parallel"] == {"maxTasks": 12}
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


def test_config_is_idempotent_and_leaves_broken_json(config_script):
    first = run(config_script, '{"x": 1}')
    assert run(config_script, first) == first
    assert run(config_script, "{broken") == "{broken"
    assert run(config_script, "[1]") == "[1]"


# --- profile ごとの配備 -------------------------------------------------


def lines(text: str) -> set[str]:
    return {x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")}


def test_custom_ignores_subagent_config(tmp_path):
    rendered = lines(
        render((HOME_SRC / ".chezmoiignore.tmpl").read_text(encoding="utf-8"), tmp_path)
    )
    assert SUBAGENT_DIR in rendered
    assert f"{SUBAGENT_DIR}/**" in rendered
    # 凍結した自作拡張 (複数形) は別物。この設定で除外しない
    assert (
        ".pi/agent/extensions/subagents" not in rendered
        or SUBAGENT_DIR != ".pi/agent/extensions/subagents"
    )


def test_stock_ignore_keeps_subagent_config(tmp_path):
    rendered = lines(
        render(
            (HOME_SRC / ".chezmoiignore.tmpl").read_text(encoding="utf-8"),
            tmp_path,
            profile_env="stock",
        )
    )
    assert SUBAGENT_DIR not in rendered
    assert f"{SUBAGENT_DIR}/**" not in rendered
    assert not any(e.startswith(f"{SUBAGENT_DIR}/") for e in rendered)


def test_custom_settings_modify_has_no_agent_overrides(tmp_path):
    """custom の settings.json は生成器が作る。agentOverrides は stock の変換にだけある。"""
    custom = render(SETTINGS_MODIFY.read_text(encoding="utf-8"), tmp_path)
    assert "agentOverrides" not in custom
    assert "AGENT_TOOL_OVERRIDES" not in custom


# --- settings の subagents.agentOverrides -------------------------------


def test_settings_overrides_scout_and_oracle_read_only(settings_script):
    out = json.loads(run(settings_script, "{}"))
    overrides = out["subagents"]["agentOverrides"]
    assert set(overrides) == {"scout", "oracle"}  # reviewer・worker は変えない
    for name in ("scout", "oracle"):
        tools = set(overrides[name]["tools"])
        assert not tools & WRITE_TOOLS, name
        assert tools <= READ_ONLY, name
    assert overrides["oracle"]["tools"] == ["read", "grep", "find", "ls"]
    assert "contact_supervisor" in overrides["scout"]["tools"]  # 親への問い合わせは残す


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


def test_settings_assigns_models_by_role_for_copilot(settings_script):
    out = json.loads(run(settings_script, json.dumps({"defaultProvider": "github-copilot"})))
    models = {n: e["model"] for n, e in out["subagents"]["agentOverrides"].items()}
    assert models["worker"] == "github-copilot/claude-sonnet-5.5:medium"
    assert models["scout"] == "github-copilot/claude-sonnet-5.5:low"
    assert models["oracle"] == "github-copilot/claude-sonnet-5.5:xhigh"  # deep
    # 実装と監査は系統を分ける (worker は Claude、reviewer は GPT)
    assert models["reviewer"] == "github-copilot/gpt-6.1-sol:high"
    assert models["evidence-auditor"] == models["reviewer"]
    assert not any("haiku" in m for m in models.values())  # Haiku は使わない (利用者の方針)


def test_settings_assigns_models_by_role_for_bedrock(settings_script):
    out = json.loads(run(settings_script, json.dumps({"defaultProvider": "amazon-bedrock"})))
    models = {n: e["model"] for n, e in out["subagents"]["agentOverrides"].items()}
    assert models["worker"] == "amazon-bedrock/us.anthropic.claude-sonnet-5-5:medium"
    assert models["oracle"] == "amazon-bedrock/us.anthropic.claude-opus-5-5:high"
    assert models["reviewer"].startswith("amazon-bedrock/us.openai.gpt-6.1-sol")
    assert all(m.startswith("amazon-bedrock/us.") for m in models.values())  # global. は使わない


def test_settings_does_not_assign_models_for_an_unknown_provider(settings_script):
    for existing in ({}, {"defaultProvider": "other"}):
        out = json.loads(run(settings_script, json.dumps(existing)))
        assert all("model" not in e for e in out["subagents"]["agentOverrides"].values())


def test_settings_keeps_a_users_model_for_a_role(settings_script):
    existing = {
        "defaultProvider": "github-copilot",
        "subagents": {"agentOverrides": {"worker": {"model": "x/y"}, "reviewer": {"thinking": "low"}}},
    }
    out = json.loads(run(settings_script, json.dumps(existing)))
    overrides = out["subagents"]["agentOverrides"]
    assert overrides["worker"]["model"] == "x/y"  # 利用者の model を保つ
    assert overrides["reviewer"]["thinking"] == "low"
    assert overrides["reviewer"]["model"] == "github-copilot/gpt-6.1-sol:high"  # 無いものは補う


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
COPIED_AGENTS = ("worker", "reviewer", "scout", "oracle")
BUILTIN_AGENTS = Path.home() / ".pi" / "agent" / "npm" / "node_modules" / "pi-subagents" / "agents"


def split_agent(text: str) -> tuple[dict, str]:
    yaml = pytest.importorskip("yaml")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5 :]


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


def test_custom_ignores_the_agent_files_and_stock_keeps_them(tmp_path):
    template = (HOME_SRC / ".chezmoiignore.tmpl").read_text(encoding="utf-8")
    assert ".pi/agent/agents" in lines(render(template, tmp_path))
    assert ".pi/agent/agents/**" in lines(render(template, tmp_path))
    stock = lines(render(template, tmp_path, profile_env="stock"))
    assert ".pi/agent/agents" not in stock and ".pi/agent/agents/**" not in stock


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
    # 承認が要る操作は任せない
    assert "`push`" in text and "`chezmoi apply`" in text
