"""Cross-platform tests for chezmoi JSON modifier wrappers."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")

MODIFIERS = {
    ROOT / "home" / "dot_claude" / "modify_settings.json.py.tmpl": (
        ".claude/settings.json",
        "claude-settings",
    ),
    ROOT / "home" / "dot_copilot" / "modify_private_settings.json.py.tmpl": (
        ".copilot/settings.json",
        "copilot-settings",
    ),
    ROOT
    / "home"
    / "dot_copilot"
    / "modify_private_permissions-config.json.py.tmpl": (
        ".copilot/permissions-config.json",
        "copilot-perms",
    ),
}
COPILOT_HOOKS = ROOT / "home" / "dot_copilot" / "hooks" / "from-claude.json.tmpl"


def execute_template(template: str) -> bytes:
    if CHEZMOI is None:
        pytest.skip("chezmoi is not installed")
    result = subprocess.run(
        [CHEZMOI, "--source", str(ROOT), "execute-template"],
        cwd=ROOT,
        input=template.encode(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def render_modifier(path: Path) -> bytes:
    return execute_template(path.read_text(encoding="utf-8"))


def render_shared_wrapper(working_tree: Path, target: str) -> bytes:
    template = (
        '{{ template "modify_json.py.tmpl" '
        f'(dict "workingTree" {json.dumps(str(working_tree))} '
        f'"target" {json.dumps(target)})'
        " }}"
    )
    return execute_template(template)


def run_wrapper(wrapper: bytes, data: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-c", wrapper.decode("utf-8")],
        cwd=ROOT,
        input=data,
        capture_output=True,
        check=False,
    )


def test_modifier_targets_keep_json_names():
    if CHEZMOI is None:
        pytest.skip("chezmoi is not installed")
    result = subprocess.run(
        [CHEZMOI, "--source", str(ROOT), "managed"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    managed = {line.replace("\\", "/") for line in result.stdout.splitlines()}
    for target, _ in MODIFIERS.values():
        assert target in managed
        assert f"{target}.py" not in managed


def test_copilot_hooks_template_renders_as_json():
    rendered = execute_template(COPILOT_HOOKS.read_text(encoding="utf-8"))

    assert json.loads(rendered)["version"] == 1


@pytest.mark.parametrize(("source", "_"), MODIFIERS.items())
def test_rendered_modifiers_compile(source: Path, _: tuple[str, str]):
    compile(render_modifier(source).decode("utf-8"), str(source), "exec")


@pytest.mark.parametrize(("source", "metadata"), MODIFIERS.items())
def test_modifiers_preserve_unicode_and_are_idempotent(
    source: Path,
    metadata: tuple[str, str],
):
    wrapper = render_modifier(source)
    data = '{"unmanaged":"日本語","managed":"stale"}\r\n'.encode()

    first = run_wrapper(wrapper, data)
    assert first.returncode == 0, first.stderr.decode(errors="replace")
    parsed = json.loads(first.stdout)
    if metadata[1] == "copilot-perms":
        assert "unmanaged" not in parsed
    else:
        assert parsed["unmanaged"] == "日本語"
    assert first.stdout.endswith(b"\n")
    assert b"\r\n" not in first.stdout

    second = run_wrapper(wrapper, first.stdout)
    assert second.returncode == 0, second.stderr.decode(errors="replace")
    assert second.stdout == first.stdout, metadata[0]


@pytest.mark.parametrize("source", MODIFIERS)
def test_modifiers_accept_empty_input(source: Path):
    result = run_wrapper(render_modifier(source), b"")

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert isinstance(json.loads(result.stdout), dict)


def test_missing_inputs_are_passed_through_byte_for_byte(tmp_path: Path):
    wrapper = render_shared_wrapper(tmp_path, "claude-settings")
    data = b'{"value":"unchanged"}\r\n\xff'

    result = run_wrapper(wrapper, data)

    assert result.returncode == 0
    assert result.stdout == data
    assert result.stderr == b""


def test_generator_failure_has_no_stdout(tmp_path: Path):
    common = tmp_path / "home" / "dot_config" / "agents" / "common.toml"
    generator = tmp_path / "scripts" / "agents" / "generate.py"
    common.parent.mkdir(parents=True)
    generator.parent.mkdir(parents=True)
    common.write_text("", encoding="utf-8")
    generator.write_text(
        "import sys\nprint('partial output')\nprint('failure marker', file=sys.stderr)\nsys.exit(7)\n",
        encoding="utf-8",
    )
    wrapper = render_shared_wrapper(tmp_path, "claude-settings")

    result = run_wrapper(wrapper, b"{}")

    assert result.returncode == 7
    assert result.stdout == b""
    assert b"failure marker" in result.stderr
