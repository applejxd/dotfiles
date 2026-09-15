"""Check post-mise DeepWiki setup without touching the real home."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "home/.chezmoiscripts/400_unix/run_once_after_410_claude_mcp.sh"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix MCP setup script")


@pytest.fixture
def environment(tmp_path):
    home = tmp_path / "home with spaces"
    bin_dir = home / ".local/bin"
    managed = home / ".local/share/mise/installs/agents/latest"
    managed.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    stub = textwrap.dedent("""
        import json
        import os
        import sys
        from pathlib import Path

        tool = Path(sys.argv[0]).name
        args = sys.argv[1:]
        with open(os.environ["COMMAND_LOG"], "a") as stream:
            stream.write(json.dumps([tool, *args]) + "\\n")
        stage = args[2] if tool == "mise" else args[0]
        if os.environ.get("FAIL_STAGE") == stage:
            sys.exit("failed " + stage)
        if tool == "mise":
            assert args[2:] == ["which", "claude"]
            print(str(Path(os.environ["MANAGED_BIN"]) / args[3]))
        elif tool == "claude" and stage == "mcp":
            assert args == ["mcp", "add", "-s", "user", "-t", "http",
                            "deepwiki", "https://mcp.deepwiki.com/mcp"]
            path = Path.home() / ".claude.json"
            config = json.loads(path.read_text()) if path.exists() else {}
            config.setdefault("mcpServers", {})["deepwiki"] = {
                "type": "http", "url": "https://mcp.deepwiki.com/mcp"}
            path.write_text(json.dumps(config))
        else:
            sys.exit("unexpected command: " + tool + " " + repr(args))
        """)
    for executable in (bin_dir / "mise", managed / "claude"):
        executable.write_text(f"#!{sys.executable}\n" + stub)
        executable.chmod(0o755)
    legacy = bin_dir / "claude"
    legacy.write_text("#!/bin/sh\nexit 99\n")
    legacy.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "MANAGED_BIN": str(managed),
        "COMMAND_LOG": str(tmp_path / "commands.jsonl"),
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
    }
    return home, env


def run_setup(env):
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def commands(env):
    log = Path(env["COMMAND_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_managed_claude_is_used_and_mcp_setup_is_idempotent(environment):
    home, env = environment
    for _ in range(2):
        result = run_setup(env)
        assert result.returncode == 0, result.stderr
    calls = commands(env)
    assert calls.count(["mise", "-C", str(home), "which", "claude"]) == 1
    assert sum(call[:2] == ["claude", "mcp"] for call in calls) == 1
    config = json.loads((home / ".claude.json").read_text())
    assert config["mcpServers"]["deepwiki"]["url"] == "https://mcp.deepwiki.com/mcp"


def test_existing_custom_mcp_configuration_is_preserved(environment):
    home, env = environment
    path = home / ".claude.json"
    existing = {"mcpServers": {"deepwiki": {"command": "custom"}, "other": {}}, "keep": True}
    path.write_text(json.dumps(existing))
    result = run_setup(env)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text()) == existing
    assert all(call[:2] != ["claude", "mcp"] for call in commands(env))


def test_malformed_claude_config_fails_without_overwriting_it(environment):
    home, env = environment
    path = home / ".claude.json"
    path.write_text("{invalid")
    result = run_setup(env)
    assert result.returncode != 0
    assert "JSONDecodeError" in result.stderr
    assert path.read_text() == "{invalid"
    assert all(call[:2] != ["claude", "mcp"] for call in commands(env))


@pytest.mark.parametrize("stage", ["which", "mcp"])
def test_failed_mcp_registration_can_be_retried(environment, stage):
    home, env = environment
    result = run_setup({**env, "FAIL_STAGE": stage})
    assert result.returncode != 0
    assert f"failed {stage}" in result.stderr
    assert not (home / ".claude.json").exists()
    retry = run_setup(env)
    assert retry.returncode == 0, retry.stderr
    assert (home / ".claude.json").exists()


def test_mise_on_path_is_supported_without_a_local_launcher(environment):
    home, env = environment
    alternate = home / "brew/bin"
    alternate.mkdir(parents=True)
    (home / ".local/bin/mise").rename(alternate / "mise")
    env["PATH"] = str(alternate) + os.pathsep + env["PATH"]
    result = run_setup(env)
    assert result.returncode == 0, result.stderr
