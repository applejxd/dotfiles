"""Tests for the /tmp read/write decisions made by redirect-tmp.py.

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "home" / "dot_claude" / "hooks" / "executable_redirect-tmp.py"
COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"


def run_hook(tool_name: str, tool_input: dict) -> str | None:
    """Run the hook as a subprocess and return the permissionDecision.

    Returns None when the hook stayed silent (= allowed). AGENTS_CONFIG_DIR
    points the hook at the repository copy of command_policy.py so the result
    does not depend on what is currently deployed to ~/.config.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(ROOT),
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
        assert proc.returncode == 0, proc.stderr
        return None
    data = json.loads(out)
    assert data["permissionDecision"] == data["hookSpecificOutput"]["permissionDecision"]
    return data["permissionDecision"]


def run_bash(command: str) -> str | None:
    return run_hook("Bash", {"command": command})


def run_path(tool_name: str, path: str) -> str | None:
    return run_hook(tool_name, {"path": path, "file_path": path})


# ---------------------------------------------------------------------------
# view (Read) は常に許可
# ---------------------------------------------------------------------------

def test_view_tmp_path_allowed():
    assert run_path("Read", "/tmp/secret.txt") is None
    assert run_path("view", "/tmp/secret.txt") is None


# ---------------------------------------------------------------------------
# create / edit は従来通り常に block (回帰確認)
# ---------------------------------------------------------------------------

def test_create_tmp_path_denied():
    assert run_path("Write", "/tmp/out.json") == "deny"
    assert run_path("create", "/tmp/out.json") == "deny"


def test_edit_tmp_path_denied():
    assert run_path("Edit", "/tmp/out.json") == "deny"
    assert run_path("edit", "/tmp/out.json") == "deny"


def test_edit_non_tmp_path_allowed():
    assert run_path("Edit", "./.tmp/out.json") is None


# ---------------------------------------------------------------------------
# bash: read-only コマンドは /tmp でも許可
# ---------------------------------------------------------------------------

def test_bash_read_only_commands_allowed():
    for command in (
        "cat /tmp/x",
        "ls /tmp/",
        "ls -la /tmp/sub",
        "df /tmp/",
        "grep foo /tmp/x",
        "head -n 5 /tmp/x",
        "wc -l /tmp/x",
        "stat /tmp/x",
        "sed 's/a/b/' /tmp/x",
        "find /tmp/ -name '*.log'",
        "sort /tmp/x",
    ):
        assert run_bash(command) is None, command


# ---------------------------------------------------------------------------
# bash: 書き込みコマンドは block
# ---------------------------------------------------------------------------

def test_bash_write_commands_denied():
    for command in (
        "echo hi > /tmp/x",
        "echo hi >> /tmp/x",
        "cp a.txt /tmp/x",
        "mv a.txt /tmp/x",
        "mkdir -p /tmp/x",
        "touch /tmp/x",
        "tee /tmp/x",
        "rm -rf /tmp/x",
        "sed -i 's/a/b/' /tmp/x",
        "mktemp /tmp/foo.XXXXXX",
        "find /tmp/ -name '*.log' -delete",
        "curl -o /tmp/out https://example.com",
        "wget -O /tmp/out https://example.com",
        "sort -o /tmp/out /tmp/in",
    ):
        assert run_bash(command) == "deny", command


# ---------------------------------------------------------------------------
# bash: /tmp からの読み出しは block しない
#
# Copilot CLI は大きいツール出力を /tmp/<epoch>-copilot-tool-output-*.txt に
# 保存する。これをリポジトリへ取り込む操作まで「/tmp への書き込み」と
# 判定すると作業が止まるため、転送先だけを見て判定する。
# ---------------------------------------------------------------------------

def test_bash_copy_out_of_tmp_allowed():
    for command in (
        "cp /tmp/1234-copilot-tool-output-ab.txt ./.tmp/out.md",
        "cp -r /tmp/src ./dest",
        "mv /tmp/x.txt ./docs/x.txt",
        "rsync -a /tmp/src/ ./dest/",
        "install -m 644 /tmp/x.conf ./etc/x.conf",
    ):
        assert run_bash(command) is None, command


def test_bash_copy_into_tmp_still_denied():
    """転送先が /tmp なら従来どおり block する."""
    for command in (
        "cp ./a.txt /tmp/x",
        "cp /tmp/a.txt /tmp/b.txt",
        "mv ./a.txt /tmp/x",
        "rsync -a ./src/ /tmp/dest/",
        "ln -s ./a.txt /tmp/link",
    ):
        assert run_bash(command) == "deny", command


def test_bash_compound_command_with_write_segment_denied():    # 前半は read-only でも後半が書き込みなら全体を block する
    assert run_bash("cat /tmp/x && echo hi > /tmp/y") == "deny"


def test_bash_unknown_command_defaults_to_denied():
    # 未知のコマンドは fail-safe で block する
    assert run_bash("some-unknown-tool /tmp/x") == "deny"


# ---------------------------------------------------------------------------
# allowlist (/tmp/claude-*/) は read/write 双方で維持
# ---------------------------------------------------------------------------

def test_claude_tmp_allowlist_still_allowed():
    assert run_bash("cat /tmp/claude-abc123/log") is None
    assert run_bash("echo hi > /tmp/claude-abc123/log") is None
    assert run_path("Write", "/tmp/claude-abc123/log") is None


# ---------------------------------------------------------------------------
# $TMPDIR/$TEMP/$TMP は展開先不明のため read/write 問わず block (回帰確認)
# ---------------------------------------------------------------------------

def test_tmpdir_env_var_denied():
    assert run_bash("cat $TMPDIR/x") == "deny"
    assert run_bash('echo "$TMP/x"') == "deny"


def test_non_tmp_bash_allowed():
    assert run_bash("cat ./.tmp/x") is None
    assert run_bash("git status") is None
