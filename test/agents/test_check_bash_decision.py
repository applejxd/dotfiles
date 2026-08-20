"""Tests for the deny/ask decisions made by check_bash.py.

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_bash.py"
COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"

sys.path.insert(0, str(ROOT / "home" / "dot_config" / "agents"))
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import critical_deny as cd  # noqa: E402
import generate as gen  # noqa: E402


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()


def load_hook_module():
    """Import the hook by path (its filename has the chezmoi executable_ prefix)."""
    spec = importlib.util.spec_from_file_location("check_bash_under_test", HOOK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = load_hook_module()


def run_hook(command: str, *, cwd: str | None = None) -> tuple[str | None, str]:
    """Run the hook as a subprocess and return (decision, reason).

    decision is None when the hook stayed silent (the command is allowed).
    AGENTS_CONFIG_DIR points the hook at the repository copy of the agents
    config so the result does not depend on what is currently deployed to
    ~/.config.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd or str(ROOT),
    }
    env = {**os.environ, "AGENTS_CONFIG_DIR": str(COMMON_PATH.parent)}
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    out = proc.stdout.strip()
    if not out:
        # hook が沈黙 (= 許可) か、クラッシュか区別できるように stderr を返す
        return None, proc.stderr.strip()
    data = json.loads(out)
    # Copilot 形式と Claude 形式の両方に同じ決定が入っているはず
    assert data["permissionDecision"] == data["hookSpecificOutput"]["permissionDecision"]
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    return data["permissionDecision"], data.get("permissionDecisionReason", "")


# ---------------------------------------------------------------------------
# common.toml の整合性
# ---------------------------------------------------------------------------

def test_critical_ask_list_exists():
    assert COMMON["bash"]["critical_ask"], "[bash.critical_ask] が空"


def test_critical_ask_and_deny_do_not_overlap():
    overlap = set(COMMON["bash"]["critical_ask"]) & set(COMMON["bash"]["critical_deny"])
    assert not overlap, f"critical_ask と critical_deny が重複: {overlap}"


def test_critical_ask_entries_are_not_in_bash_deny():
    """deny は hook より優先されるので、ask させたいものを deny に書いてはいけない."""
    deny_heads = {d.split(":", 1)[0] for d in COMMON["bash"]["deny"]}
    for pattern in COMMON["bash"]["critical_ask"]:
        head = pattern.split()[0]
        assert head not in deny_heads, (
            f"'{pattern}' を ask させたいが [bash.deny] に '{head}' がある。"
            " deny が hook より優先されるためプロンプトが出ない"
        )


def test_loader_reads_critical_ask():
    patterns = cd.load_critical_ask(str(COMMON_PATH))
    assert "rm -rf" in patterns


def test_loader_reads_critical_deny():
    patterns = cd.load_critical_deny(str(COMMON_PATH))
    assert "rm -rf" not in patterns
    assert "git push" in patterns


# ---------------------------------------------------------------------------
# 生成される permission リスト
# ---------------------------------------------------------------------------

def test_generated_permissions_put_rm_in_ask_not_deny():
    perms = gen.build_claude_permissions(COMMON)
    assert not [r for r in perms["deny"] if r.startswith("Bash(rm:")], (
        "Bash(rm:*) が deny に残っていると hook の ask が無効化される"
    )
    assert "Bash(rm:*)" in perms["ask"]
    assert "Bash(rm -rf:*)" in perms["ask"]


def test_generated_permissions_keep_critical_deny_in_deny():
    perms = gen.build_claude_permissions(COMMON)
    assert "Bash(sudo:*)" in perms["deny"]
    assert "Bash(git push:*)" in perms["deny"]


# ---------------------------------------------------------------------------
# ask になるべきケース
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./.tmp",
        "rm -rf build/",
        "rm -rf ./foo/bar",
        "cd /home/user/project && rm -rf ./node_modules",
        "rm -rf .venv && echo done",
    ],
)
def test_project_scoped_rm_asks(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.pyc' -delete",
        "find ./build -type f -exec rm {} +",
    ],
)
def test_find_deletion_asks(command):
    decision, reason = run_hook(command)
    assert decision == "ask", f"{command!r} -> {decision} ({reason})"


def test_cwd_scoped_rm_glob_asks():
    # プロジェクト内の一括削除はユーザー承認に委ねる (root guard の対象外)
    decision, _ = run_hook("rm -rf ./*")
    assert decision == "ask"


# ---------------------------------------------------------------------------
# deny のままであるべきケース (root guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf ~/",
        "rm -rf $HOME",
        "rm -rf ${HOME}",
        "rm -rf ..",
        "rm -rf /etc",
        "rm -rf /usr/*",
        "rm -rf /var",
        "rm -rf /home/someone",
        "rm -rf --no-preserve-root /tmp/x",
        "rm -fr /",
    ],
)
def test_catastrophic_rm_targets_are_denied(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


def test_root_guard_survives_cd_bypass():
    decision, _ = run_hook("cd /elsewhere && rm -rf /")
    assert decision == "deny"


def test_root_guard_survives_compound_bypass():
    decision, _ = run_hook("echo ok; rm -rf ~")
    assert decision == "deny"


# ---------------------------------------------------------------------------
# 既存の防御が壊れていないこと (回帰)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "grep -n token ~/.ssh/id_rsa",
        "env",
        "printenv",
        "sudo apt install foo",
        "git push origin main",
        "cd /elsewhere && git push",
        "git reset --hard HEAD~1",
        "git -C /somewhere config user.name x",
    ],
)
def test_existing_denies_are_unchanged(command):
    decision, reason = run_hook(command)
    assert decision == "deny", f"{command!r} -> {decision} ({reason})"


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "ls -la",
        "echo hello",
        "grep -rn foo src/",
    ],
)
def test_safe_commands_pass_through(command):
    decision, _ = run_hook(command)
    assert decision is None, f"{command!r} が不要にブロックされた"


# ---------------------------------------------------------------------------
# ヘルパ単体
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("/", True),
        ("/*", True),
        ("/etc/", True),
        ("/etc/*", True),
        ("~", True),
        ("$HOME", True),
        ("..", True),
        ("/home/bob", True),
        ("/Users/bob", True),
        ("./foo", False),
        ("build", False),
        ("~/projects/foo", False),
        ("/home/bob/projects", False),
        ("../sibling", False),
    ],
)
def test_is_catastrophic_rm_target(token, expected):
    assert HOOK._is_catastrophic_rm_target(token) is expected
