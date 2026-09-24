"""Check post-mise MCP registration for Claude without touching the real home."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
from agents_common import load_common  # noqa: E402

SCRIPT = ROOT / "home/.chezmoiscripts/400_unix/run_onchange_after_410_claude_mcp.sh.tmpl"
# applejxd では除外されるサーバがあるので、両方のユーザで確かめる
USERS = ["applejxd", "tester"]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix MCP setup script")


def render_script(username):
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = json.dumps(json.dumps({"chezmoi": {"username": username}}))
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=f"{{{{ with {context} | fromJson }}}}\n"
        + SCRIPT.read_text(encoding="utf-8")
        + "\n{{ end }}",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def expected_servers(username):
    """generate.py (Copilot 側) と同じ結果になるはず、を Claude の形で表す。"""
    return {
        name: (
            {"type": "http", "url": server["url"]}
            if server["transport"] == "http"
            else {"command": server["command"], "args": server["args"]}
        )
        for name, server in gen.mcp_servers(load_common(username))
    }


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
            # `claude mcp add-json -s user <name> <json>`
            assert args[:4] == ["mcp", "add-json", "-s", "user"]
            name, spec = args[4:]
            path = Path.home() / ".claude.json"
            config = json.loads(path.read_text()) if path.exists() else {}
            config.setdefault("mcpServers", {})[name] = json.loads(spec)
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


def run_setup(script, env):
    return subprocess.run(
        ["bash"], input=script, env=env, capture_output=True, text=True, check=False
    )


def commands(env):
    log = Path(env["COMMAND_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_nothing_to_register_does_not_need_claude(tmp_path):
    """★登録対象が 0 件なら claude を探さないこと。

    `clis` で絞った結果 0 件になることがある。そこで mise に claude を
    要求すると、使っていない CLI のために apply 全体が落ちる (実際に
    "claude is a mise bin however it is not currently active" で止まった)。
    """
    script = render_script("applejxd")
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "commands.jsonl"
    # bash と python3 だけの PATH。mise も claude も無いので、見に行ったら落ちる。
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "python3"):
        found = shutil.which(tool)
        if not found:
            pytest.skip(f"{tool} が無い")
        (bin_dir / tool).symlink_to(found)
    env = {
        **os.environ,
        "HOME": str(home),
        "COMMAND_LOG": str(log),
        "PATH": str(bin_dir),
    }
    result = subprocess.run(
        [str(bin_dir / "bash")],
        input=script,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not log.exists()


@pytest.mark.parametrize("username", USERS)
def test_servers_for_this_user_are_registered_once(environment, username):
    home, env = environment
    script = render_script(username)
    expected = expected_servers(username)
    for _ in range(2):
        result = run_setup(script, env)
        assert result.returncode == 0, result.stderr

    # applejxd は登録対象が 0 件。その場合 ~/.claude.json を作らない。
    config = home / ".claude.json"
    registered = json.loads(config.read_text())["mcpServers"] if config.exists() else {}
    assert registered == expected
    # 2 回目は登録済みなので追加しない
    calls = commands(env)
    assert sum(call[:2] == ["claude", "mcp"] for call in calls) == len(expected)


def test_existing_custom_mcp_configuration_is_preserved(environment):
    home, env = environment
    path = home / ".claude.json"
    existing = {
        "mcpServers": {name: {"command": "custom"} for name in expected_servers("tester")},
        "keep": True,
    }
    existing["mcpServers"]["other"] = {}
    path.write_text(json.dumps(existing))
    result = run_setup(render_script("tester"), env)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text()) == existing
    assert all(call[:2] != ["claude", "mcp"] for call in commands(env))


def test_malformed_claude_config_fails_without_overwriting_it(environment):
    home, env = environment
    path = home / ".claude.json"
    path.write_text("{invalid")
    result = run_setup(render_script("tester"), env)
    assert result.returncode != 0
    assert "JSONDecodeError" in result.stderr
    assert path.read_text() == "{invalid"
    assert all(call[:2] != ["claude", "mcp"] for call in commands(env))


@pytest.mark.parametrize("stage", ["which", "mcp"])
def test_failed_mcp_registration_can_be_retried(environment, stage):
    home, env = environment
    script = render_script("tester")
    result = run_setup(script, {**env, "FAIL_STAGE": stage})
    assert result.returncode != 0
    assert f"failed {stage}" in result.stderr
    assert not (home / ".claude.json").exists()
    retry = run_setup(script, env)
    assert retry.returncode == 0, retry.stderr
    assert (home / ".claude.json").exists()


def test_mise_on_path_is_supported_without_a_local_launcher(environment):
    home, env = environment
    alternate = home / "brew/bin"
    alternate.mkdir(parents=True)
    (home / ".local/bin/mise").rename(alternate / "mise")
    env["PATH"] = str(alternate) + os.pathsep + env["PATH"]
    result = run_setup(render_script("tester"), env)
    assert result.returncode == 0, result.stderr
