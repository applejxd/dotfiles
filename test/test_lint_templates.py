"""chezmoi テンプレート用リンター (scripts/lint_templates.py) の test。

Run with: ``uv run --with pytest --no-project pytest test/test_lint_templates.py -q``
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lint_templates.py"


def load_linter():
    spec = importlib.util.spec_from_file_location("lint_templates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_templates"] = module
    spec.loader.exec_module(module)
    return module


linter = load_linter()


@pytest.fixture
def repo(tmp_path):
    """git 管理下の最小リポジトリを作る (列挙が git ls-files のため)。"""
    if shutil.which("chezmoi") is None:
        pytest.skip("chezmoi is not installed")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    def add(relative: str, text: str) -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", relative], check=True)

    return tmp_path, add


def run(repo_path, *paths):
    return linter.main(["--source", str(repo_path), *paths])


# ---------------------------------------------------------------------------
# 描画コンテキストの決め方
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,expected",
    [
        ("home/.chezmoiscripts/100_linux/a.sh.tmpl", ("linux",)),
        ("home/.chezmoiscripts/200_mac/a.sh.tmpl", ("darwin",)),
        ("home/.chezmoiscripts/300_windows/a.ps1.tmpl", ("windows",)),
        ("home/.chezmoiscripts/000_unix/a.sh.tmpl", ("linux", "darwin")),
        ("home/.chezmoiscripts/400_unix/a.sh.tmpl", ("linux", "darwin")),
        # ディレクトリ規約の外は全 OS で描画する
        ("home/dot_config/a.toml.tmpl", ("linux", "darwin", "windows")),
        # 入れ子でも親のディレクトリ規約に従う
        ("home/.chezmoiscripts/100_linux/110_native/a.sh.tmpl", ("linux",)),
    ],
)
def test_os_axis_follows_the_directory_convention(path, expected):
    assert linter.target_platforms(path) == expected


def test_user_axis_only_applies_to_templates_that_branch_on_it():
    assert linter.target_users("{{ .chezmoi.username }}") == ("applejxd", "other-user")
    assert linter.target_users("{{ .chezmoi.os }}") == ("applejxd",)


# ---------------------------------------------------------------------------
# 検出
# ---------------------------------------------------------------------------

def test_broken_toml_is_reported(repo, capsys):
    path, add = repo
    add("home/a.toml.tmpl", 'valid = "yes"\nbroken = \n')
    assert run(path) == 1
    assert "a.toml.tmpl" in capsys.readouterr().err


def test_broken_python_is_reported(repo, capsys):
    path, add = repo
    add("home/a.py.tmpl", "def broken(:\n    pass\n")
    assert run(path) == 1
    assert "a.py.tmpl" in capsys.readouterr().err


def test_broken_shell_is_reported(repo, capsys):
    path, add = repo
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    add("home/a.sh.tmpl", "#!/bin/bash\nif [ -e $1 ]; then :; fi\n")
    assert run(path) == 1
    assert "SC2086" in capsys.readouterr().err


def test_valid_templates_pass(repo):
    path, add = repo
    add("home/a.toml.tmpl", 'ok = {{ .chezmoi.os | quote }}\n')
    add("home/a.py.tmpl", "value = 1\n")
    assert run(path) == 0


def test_a_branch_only_reachable_for_another_user_is_still_checked(repo, capsys):
    """single コンテキストでは見逃す壊れ方を捕まえる。"""
    path, add = repo
    add(
        "home/a.toml.tmpl",
        '{{ if not (regexMatch "applejxd" .chezmoi.username) }}broken = {{ end }}\n',
    )
    assert run(path) == 1
    assert "user=other-user" in capsys.readouterr().err


def test_a_windows_only_branch_is_checked(repo, capsys):
    path, add = repo
    add(
        "home/a.toml.tmpl",
        '{{ if eq .chezmoi.os "windows" }}broken = {{ end }}\n',
    )
    assert run(path) == 1
    assert "os=windows" in capsys.readouterr().err


def test_templates_that_render_to_nothing_are_skipped(repo):
    path, add = repo
    add("home/a.toml.tmpl", '{{ if eq .chezmoi.os "plan9" }}broken = {{ end }}\n')
    assert run(path) == 0


# ---------------------------------------------------------------------------
# 秘密・除外
# ---------------------------------------------------------------------------

def test_secret_templates_are_skipped_without_touching_the_vault(repo, tmp_path):
    """--skip-secrets により bw を起動しないこと。"""
    path, add = repo
    add("home/a.toml.tmpl", 'x = {{ (bitwarden "item" "whatever").login.username | quote }}\n')

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    log = tmp_path / "bw-calls.log"
    stub = stub_dir / "bw"
    stub.write_text(f'#!/bin/sh\necho "$*" >> {log}\nexit 1\n', encoding="utf-8")
    stub.chmod(0o755)

    original = os.environ["PATH"]
    os.environ["PATH"] = f"{stub_dir}{os.pathsep}{original}"
    try:
        assert run(path) == 0
    finally:
        os.environ["PATH"] = original
    assert not log.exists(), "vault を叩いてはいけない"


def test_unlintable_and_excluded_templates_are_left_alone(repo):
    path, add = repo
    # 対象外の拡張子 (PSScriptAnalyzer が要る)
    add("home/a.ps1.tmpl", "this is not valid powershell {{{\n")
    # 単体では描画できない共有テンプレート
    add("home/.chezmoitemplates/shared.toml.tmpl", "broken = \n")
    assert run(path) == 0


# ---------------------------------------------------------------------------
# 実リポジトリ
# ---------------------------------------------------------------------------

def test_this_repository_passes():
    if shutil.which("chezmoi") is None or shutil.which("shellcheck") is None:
        pytest.skip("chezmoi / shellcheck is not installed")
    assert linter.main(["--source", str(ROOT)]) == 0
