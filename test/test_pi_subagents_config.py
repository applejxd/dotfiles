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


def render(template: str, home: Path, *, profile_env: str | None = None) -> str:
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
        "maxActiveAsyncRunsPerSession": 4,
        "maxSubagentDepth": 1,
        "maxSubagentSpawnsPerRun": 32,
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
    assert out["maxSubagentDepth"] == 1  # 無かったものは補う


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
