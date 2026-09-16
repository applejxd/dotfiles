"""Regression tests for Herdr integration scripts."""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "home" / ".chezmoiscripts"
LINUX_SCRIPT = SCRIPTS / "100_linux" / "run_after_140_herdr_integration.sh.tmpl"
WINDOWS_SCRIPT = (
    SCRIPTS
    / "300_windows"
    / "run_after_343_herdr_integration.ps1.tmpl"
)
MISE_CONFIG = ROOT / "home" / "dot_config" / "mise" / "config.toml.tmpl"
MISE_SCRIPTS = {
    "linux": SCRIPTS / "100_linux/run_onchange_after_125_mise.sh.tmpl",
    "darwin": SCRIPTS / "200_mac/run_onchange_after_225_mise.sh.tmpl",
    "windows": (
        SCRIPTS / "300_windows/310_packages/run_onchange_after_313_mise.ps1.tmpl"
    ),
}


def render_template(path, *, os_name="linux", username="applejxd", home="/test-home"):
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    context = {
        "chezmoi": {
            "os": os_name,
            "username": username,
            "homeDir": str(home),
            "kernel": {"osrelease": "Linux"},
        }
    }
    template = (
        "{{ with " + json.dumps(json.dumps(context)) + " | fromJson }}\n"
        + path.read_text(encoding="utf-8-sig")
        + "\n{{ end }}"
    )
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=template,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("os_name", ["linux", "windows", "darwin"])
@pytest.mark.parametrize("username", ["applejxd", r"DOMAIN\applejxd", "other"])
def test_mise_config_keeps_platform_scope(os_name, username):
    config = tomllib.loads(render_template(MISE_CONFIG, os_name=os_name, username=username))
    tools = config["tools"]
    assert tools["gh"] == "latest"
    assert tools["copilot"] == "latest"
    has_claude = os_name != "windows" or not username.endswith("applejxd")
    assert ("claude-code" in tools) == has_claude
    if has_claude:
        assert tools["claude-code"] == "latest"
    if os_name == "windows":
        expected = {"gh": "latest", "herdr": "latest", "copilot": "latest"}
        if has_claude:
            expected["claude-code"] = "latest"
        assert config == {"tools": expected}
    else:
        assert tools["node"] == "latest"
        assert tools["uv"] == "latest"
        assert config["settings"]["experimental"] is True
        assert ("npm:@bitwarden/cli" in tools) == username.endswith("applejxd")
        if os_name == "linux":
            assert tools["herdr"] == "latest"
        else:
            assert "herdr" not in tools


def test_windows_mise_config_is_not_ignored():
    ignore = render_template(ROOT / "home" / ".chezmoiignore.tmpl", os_name="windows")
    lines = ignore.splitlines()
    assert lines.index("!.config/mise/") > lines.index(".config/*")
    assert lines.index("!.config/mise/config.toml") > lines.index("!.config/mise/")


def test_direct_installers_are_removed():
    assert not (SCRIPTS / "100_linux" / "run_once_after_126_herdr.sh").exists()
    assert not (
        SCRIPTS / "300_windows" / "310_packages" / "run_once_before_313_herdr.ps1"
    ).exists()
    assert not (
        SCRIPTS / "300_windows" / "310_packages" / "run_once_before_314_claude.ps1.tmpl"
    ).exists()
    winget = (
        SCRIPTS / "300_windows" / "310_packages" / "run_once_before_310_winget.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")
    assert "winst GitHub.Copilot" not in winget
    assert "winst jdx.mise" in winget
    assert not (SCRIPTS / "000_unix" / "run_once_after_010_tools.sh").exists()


def test_github_cli_has_no_separate_apt_install():
    source = (SCRIPTS / "100_linux/run_once_after_121_ubuntu.sh.tmpl").read_text()
    assert "cli.github.com/packages" not in source
    assert "githubcli-archive-keyring" not in source
    assert not re.search(r"\bapt(?:-get)?\s+install\s+gh\b", source)
    assert "wget curl git unzip" in source


@pytest.mark.parametrize("username,agent", [("applejxd", "copilot"), ("other", "claude")])
def test_windows_integration_uses_mise_and_checks_failures(username, agent):
    source = render_template(WINDOWS_SCRIPT, os_name="windows", username=username)
    assert " install herdr" not in source
    assert f"$agentCommand = '{agent}'" in source
    assert "$herdrPath = & $miseCommand.Path -C $homeDir which herdr" in source
    assert "$agentPath = & $miseCommand.Path -C $homeDir which $agentCommand" in source
    assert "Failed to resolve Herdr via mise" in source
    assert "Failed to resolve $agentCommand via mise" in source
    assert "GetEnvironmentVariable('Path', 'User')" in source
    assert "-CommandType Application -ErrorAction Stop" in source
    assert source.index("which herdr") < source.index("integration install $agentCommand")
    assert source.index("which $agentCommand") < source.index("Split-Path -Parent $agentPath")
    assert source.index("Split-Path -Parent $agentPath") < source.index(
        "integration install $agentCommand"
    )
    assert r"Programs\Herdr" not in source
    assert "$startInfo.FileName = $herdrPath" in source


@pytest.mark.parametrize("os_name", MISE_SCRIPTS)
def test_platform_bootstrap_installs_the_declared_tools_together(os_name):
    source = render_template(MISE_SCRIPTS[os_name], os_name=os_name)
    assert re.search(r"# mise config: [0-9a-f]{64}", source)
    commands = [line for line in source.splitlines() if line.strip() and not line.startswith("#")]
    installs = [line for line in commands if re.search(r"\binstall\s*$", line)]
    assert len(installs) == 1
    assert ("-C $homeDir" if os_name == "windows" else '-C "$HOME"') in installs[0]
    assert not re.search(r"\binstall (?:claude-code|copilot|herdr)\b", source)
    assert "reshim" in source
    if os_name == "windows":
        assert "mise install failed with exit code $LASTEXITCODE" in source
        assert "mise reshim failed with exit code $LASTEXITCODE" in source


@pytest.mark.skipif(os.name == "nt", reason="POSIX marker scripts for order verification")
@pytest.mark.parametrize("os_name", ["linux", "darwin", "windows"])
def test_chezmoi_applies_mise_config_before_bootstrap_and_integrations(tmp_path, os_name):
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    source = tmp_path / "source"
    destination = tmp_path / "home"
    destination.mkdir()
    mise_config = source / "dot_config/mise/config.toml"
    mise_config.parent.mkdir(parents=True)
    mise_config.write_text('[tools]\ncopilot = "latest"\n')
    (source / ".chezmoiignore").write_text(
        render_template(ROOT / "home/.chezmoiignore.tmpl", os_name=os_name, home=destination)
    )
    winget = SCRIPTS / "300_windows/310_packages/run_once_before_310_winget.ps1.tmpl"
    mcp = SCRIPTS / "400_unix/run_once_after_410_claude_mcp.sh"
    for path in [*MISE_SCRIPTS.values(), LINUX_SCRIPT, WINDOWS_SCRIPT, winget, mcp]:
        assert path.is_file()
        relative = str(path.relative_to(SCRIPTS)).removesuffix(".tmpl")
        # Keep the real ordering names, but use portable markers instead of PowerShell.
        relative = relative.replace(".ps1", ".sh")
        marker = source / ".chezmoiscripts" / relative
        marker.parent.mkdir(parents=True, exist_ok=True)
        check = "test ! -e" if "before_" in relative else "test -f"
        marker.write_text(
            "#!/bin/sh\nset -eu\n"
            f'{check} "$HOME/.config/mise/config.toml"\n'
            f"printf '%s\\n' '{path.relative_to(SCRIPTS)}'\n"
        )
    config = tmp_path / "chezmoi.toml"
    config.write_text("")
    result = subprocess.run(
        [
            chezmoi,
            "--config", str(config),
            "--source", str(source),
            "--destination", str(destination),
            "--persistent-state", str(tmp_path / "state.boltdb"),
            "--cache", str(tmp_path / "cache"),
            "apply",
        ],
        env={**os.environ, "HOME": str(destination)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    expected = {
        "linux": [MISE_SCRIPTS["linux"], LINUX_SCRIPT, mcp],
        "darwin": [MISE_SCRIPTS["darwin"], mcp],
        "windows": [winget, MISE_SCRIPTS["windows"], WINDOWS_SCRIPT],
    }
    assert result.stdout.splitlines() == [
        str(path.relative_to(SCRIPTS)) for path in expected[os_name]
    ]


@pytest.fixture
def linux_environment(tmp_path):
    if os.name == "nt":
        pytest.skip("Linux shell script")
    home = tmp_path / "home with spaces"
    mise = home / ".local/bin/mise"
    herdr = home / ".local/share/mise/installs/herdr/0.9.0/herdr"
    stub = textwrap.dedent("""
        import json
        import os
        import shutil
        import sys
        from pathlib import Path

        args = sys.argv[1:]
        tool = Path(sys.argv[0]).name
        with open(os.environ["COMMAND_LOG"], "a") as log:
            log.write(json.dumps([tool, *args]) + "\\n")
        stage = args[2] if tool == "mise" else args[0]
        failure = os.environ.get("FAIL_STAGE")
        if failure == stage:
            sys.exit("failed " + stage)
        if tool == "mise":
            if stage == "which":
                if args[3] == "herdr":
                    print(os.environ["HERDR_BINARY"])
                elif failure == "missing_agent":
                    print(str(Path.home() / "missing-agent"))
                else:
                    print(str(Path(os.environ["AGENT_BIN_DIR"]) / args[3]))
        elif stage == "integration":
            expected = str(Path(os.environ["AGENT_BIN_DIR"]) / args[2])
            assert shutil.which(args[2]) == expected
            settings = Path.home() / ("." + args[2]) / "settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text('{"preserved":true}')
        elif stage == "--skill":
            if failure == "invalid_skill":
                print("invalid skill")
            else:
                print("---\\nname: herdr\\ndescription: Test skill\\n---\\n# Herdr")
        else:
            sys.exit("unexpected arguments: " + repr(args))
        """)
    for executable in (mise, herdr):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(f"#!{sys.executable}\n" + stub)
        executable.chmod(0o755)
    legacy = home / ".local/bin/herdr"
    legacy.write_text("#!/bin/sh\nexit 99\n")
    legacy.chmod(0o755)
    agent_bin = home / ".local/share/mise/installs/agents/latest"
    agent_bin.mkdir(parents=True)
    for agent in ("claude", "copilot"):
        (agent_bin / agent).write_text("#!/bin/sh\nexit 0\n")
        (agent_bin / agent).chmod(0o755)
        (mise.parent / agent).write_text("#!/bin/sh\nexit 99\n")
        (mise.parent / agent).chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "HERDR_BINARY": str(herdr),
        "AGENT_BIN_DIR": str(agent_bin),
        "COMMAND_LOG": str(tmp_path / "commands.jsonl"),
        "PATH": str(mise.parent) + os.pathsep + os.environ["PATH"],
    }
    return home, env


def run_linux_integration(home, env, username="applejxd"):
    return subprocess.run(
        ["bash"],
        input=render_template(LINUX_SCRIPT, home=home, username=username),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("username,agent", [("applejxd", "copilot"), ("other", "claude")])
def test_linux_integration_uses_managed_binary_and_refreshes_skill(
    linux_environment, username, agent
):
    home, env = linux_environment
    skill_dir = home / ".claude/skills/herdr"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_text("old skill")
    for _ in range(2):
        result = run_linux_integration(home, env, username)
        assert result.returncode == 0, result.stderr
        assert skill.read_text().startswith("---\nname: herdr\n")
        assert (home / f".{agent}/settings.json").read_text() == '{"preserved":true}\n'
        assert sorted(path.name for path in skill_dir.iterdir()) == ["SKILL.md"]
    commands = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    assert commands == [
        ["mise", "-C", str(home), "which", "herdr"],
        ["mise", "-C", str(home), "which", agent],
        ["herdr", "integration", "install", agent],
        ["herdr", "--skill"],
    ] * 2


@pytest.mark.parametrize(
    "stage",
    ["which", "integration", "--skill", "invalid_skill", "missing_binary", "missing_agent"],
)
def test_linux_integration_stops_on_errors_and_preserves_skill(linux_environment, stage):
    home, env = linux_environment
    env["FAIL_STAGE"] = stage
    if stage == "missing_binary":
        env["HERDR_BINARY"] = str(home / "missing-herdr")
    skill_dir = home / ".claude/skills/herdr"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_text("old skill")
    result = run_linux_integration(home, env)
    assert result.returncode != 0
    assert result.stderr
    assert skill.read_text() == "old skill"
    assert sorted(path.name for path in skill_dir.iterdir()) == ["SKILL.md"]


def test_windows_skill_replace_uses_nonempty_backup_path():
    source = WINDOWS_SCRIPT.read_text(encoding="utf-8")

    assert "[System.IO.File]::Replace($skillTempPath, $skillPath, $null)" not in source
    assert (
        "[System.IO.File]::Replace($skillTempPath, $skillPath, $skillBackupPath)" in source
    )
    assert "Remove-Item -LiteralPath $skillBackupPath -Force" in source
