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
    ROOT / "home" / "dot_copilot" / "modify_mcp-config.json.py.tmpl": (
        ".copilot/mcp-config.json",
        "copilot-mcp",
    ),
    ROOT / "home" / "dot_gemini" / "modify_settings.json.py.tmpl": (
        ".gemini/settings.json",
        "gemini-settings",
    ),
    ROOT / "home" / "dot_config" / "opencode" / "modify_opencode.json.py.tmpl": (
        ".config/opencode/opencode.json",
        "opencode-config",
    ),
}
COPILOT_HOOKS = (
    ROOT / "home" / "dot_copilot" / "hooks" / "modify_from-claude.json.py.tmpl"
)
CHEZMOI_CONFIG = ROOT / "home" / ".chezmoi.toml.tmpl"


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
        '"common" (includeTemplate "dot_config/agents/common.toml.tmpl" .) '
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


def test_copilot_hooks_modifier_renders_as_json():
    # hooks ファイルは完全な生成物なので、既存内容があっても作り直す
    result = run_wrapper(render_modifier(COPILOT_HOOKS), b'{"stale": true}')

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    generated = json.loads(result.stdout)
    assert generated["version"] == 1
    assert "stale" not in generated


def test_windows_templates_use_latest_python_3():
    config = CHEZMOI_CONFIG.read_text(encoding="utf-8")

    assert 'args = ["-3"]' in config
    # hooks の生成も modify_ 経由になったので、Windows の Python 選択は
    # [interpreters.py] が受け持つ (テンプレート側に py -3 を書かない)
    assert "modify_json.py.tmpl" in COPILOT_HOOKS.read_text(encoding="utf-8")


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
    # permissions-config.json は CLI 自身が承認を書き込むファイルなので、
    # 生成側は locations を union するだけで他のキーには触らない
    # (全置換すると chezmoi apply のたびに対話承認が消える)。
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
        "import sys\n"
        "print('partial output')\n"
        "print('failure marker', file=sys.stderr)\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    wrapper = render_shared_wrapper(tmp_path, "claude-settings")

    result = run_wrapper(wrapper, b"{}")

    assert result.returncode == 7
    assert result.stdout == b""
    assert b"failure marker" in result.stderr
