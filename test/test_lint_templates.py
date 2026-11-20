"""chezmoi テンプレート用リンター (scripts/lint_templates.py) の test。

Run with: ``uv run --with pytest --no-project pytest test/test_lint_templates.py -q``
"""

from __future__ import annotations

import importlib.util
import os
import re
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
def git_repo(tmp_path):
    """git 管理下の最小リポジトリを作る (列挙が git ls-files のため)。"""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    def add(relative: str, text: str) -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", relative], check=True)

    return tmp_path, add


@pytest.fixture
def repo(git_repo):
    """描画する検査用 (chezmoi が要る)。"""
    if shutil.which("chezmoi") is None:
        pytest.skip("chezmoi is not installed")
    return git_repo


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
# modify script の標準入出力 (UTF-8 の固定)
# ---------------------------------------------------------------------------

PIN_IN = 'sys.stdin.reconfigure(encoding="utf-8")'
PIN_OUT = 'sys.stdout.reconfigure(encoding="utf-8")'
SHARED_MODIFIER = "home/.chezmoitemplates/modify_x.py.tmpl"
STOCK_SETTINGS = ROOT / "home" / ".chezmoitemplates" / "modify_pi_stock_settings.py.tmpl"


def modifier(*, pin_in=True, pin_out=True, body=None):
    """標準入力を読み標準出力へ書く最小の modify script。"""
    lines = ["import sys", "", "", "def main():"]
    lines += [f"    {PIN_IN}"] * pin_in + [f"    {PIN_OUT}"] * pin_out
    lines += body or ["    raw = sys.stdin.read()", "    sys.stdout.write(raw)"]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl", True),
        ("home/dot_pi/agent/modify_compaction.json.py.tmpl", True),
        ("home/dot_pi/agent/extensions/subagent/modify_config.json.py.tmpl", True),
        ("modify_x.py.tmpl", True),
        # modify script でない
        ("home/dot_pi/agent/not_modify_x.py.tmpl", False),
        ("home/dot_pi/agent/run_modify_x.py.tmpl", False),
        ("home/dot_pi/agent/modify_x.ini", False),
        ("home/dot_pi/agent/modify_x.py", False),
    ],
)
def test_modify_scripts_are_recognised_by_name(path, expected):
    assert bool(linter.MODIFY_SCRIPT.search(path)) is expected


def streams(problems):
    """報告が指す標準入出力の名前。"""
    return sorted(re.search(r": sys\.(stdin|stdout) を", p).group(1) for p in problems)


def test_a_pinned_modifier_passes():
    assert linter.check_modify_stdio("m.py.tmpl", modifier()) == []


def test_single_quotes_are_accepted_for_the_pin():
    text = modifier().replace('"utf-8"', "'utf-8'")
    assert linter.check_modify_stdio("m.py.tmpl", text) == []


@pytest.mark.parametrize(
    "kwargs,missing",
    [
        ({"pin_in": False, "pin_out": False}, ["stdin", "stdout"]),
        ({"pin_in": False}, ["stdin"]),
        ({"pin_out": False}, ["stdout"]),
    ],
)
def test_a_text_stream_without_the_pin_is_reported(kwargs, missing):
    problems = linter.check_modify_stdio("m.py.tmpl", modifier(**kwargs))
    assert streams(problems) == sorted(missing)
    assert all(p.startswith("m.py.tmpl:") for p in problems)


def test_a_json_dump_to_stdout_counts_as_text_output():
    text = "import json, sys\n\nsys.stdin.reconfigure(encoding=\"utf-8\")\njson.dump({}, sys.stdout)\n"
    assert streams(linter.check_modify_stdio("m.py.tmpl", text)) == ["stdout"]


def test_a_pin_after_the_first_use_is_reported():
    body = ["    raw = sys.stdin.read()", f"    {PIN_IN}", "    sys.stdout.write(raw)"]
    problems = linter.check_modify_stdio("m.py.tmpl", modifier(pin_in=False, body=body))
    assert streams(problems) == ["stdin"]


def test_a_commented_out_pin_does_not_count():
    text = modifier(pin_in=False).replace("def main():", f"# {PIN_IN}\ndef main():")
    assert streams(linter.check_modify_stdio("m.py.tmpl", text)) == ["stdin"]


def test_a_mention_in_a_docstring_or_comment_is_not_a_use():
    text = '''"""標準入力 (sys.stdin) を変換して sys.stdout へ出す。"""\n# sys.stdout.write は使わない\nvalue = 1\n'''
    assert linter.check_modify_stdio("m.py.tmpl", text) == []


def test_byte_stream_io_needs_no_pin():
    """.buffer 経由は自分でエンコードするので対象外 (modify_json.py.tmpl の形)。"""
    body = ["    data = sys.stdin.buffer.read()", "    sys.stdout.buffer.write(data)"]
    assert linter.check_modify_stdio("m.py.tmpl", modifier(pin_in=False, pin_out=False, body=body)) == []


def test_a_modifier_that_does_not_touch_stdio_passes():
    assert linter.check_modify_stdio("m.py.tmpl", "import sys\n\nprint(sys.executable)\n") == []


def test_a_shared_modifier_without_the_pin_fails_the_lint(git_repo, capsys):
    """共有テンプレートは描画の対象外だが、この規則では見る。"""
    path, add = git_repo
    add(SHARED_MODIFIER, modifier(pin_out=False))
    assert run(path) == 1
    err = capsys.readouterr().err
    assert SHARED_MODIFIER in err
    assert "sys.stdout" in err


def test_a_shared_modifier_with_the_pin_passes_the_lint(git_repo):
    path, add = git_repo
    add(SHARED_MODIFIER, modifier())
    assert run(path) == 0


def test_an_explicit_path_is_checked_too(git_repo, capsys):
    path, add = git_repo
    add(SHARED_MODIFIER, modifier(pin_in=False))
    assert run(path, SHARED_MODIFIER) == 1
    assert "sys.stdin" in capsys.readouterr().err


def real_modifiers():
    return linter.modify_scripts(ROOT, [])


def test_this_repository_has_modifiers_to_check():
    """列挙が空振りして、規則が何も見ずに通ることを防ぐ。"""
    found = real_modifiers()
    assert STOCK_SETTINGS.relative_to(ROOT).as_posix() in found
    assert len(found) >= 5


def test_this_repository_modifiers_pin_stdio_to_utf8():
    problems = []
    for path in real_modifiers():
        problems += linter.check_modify_stdio(path, (ROOT / path).read_text(encoding="utf-8"))
    assert problems == []


def test_removing_the_pin_from_the_stock_settings_modifier_fails():
    """日本語の Windows で UnicodeEncodeError (cp932 が U+2014 を書けない) になった不具合の再発を、静的に止める。"""
    path = STOCK_SETTINGS.relative_to(ROOT).as_posix()
    text = STOCK_SETTINGS.read_text(encoding="utf-8")
    assert linter.check_modify_stdio(path, text) == []
    unpinned = re.sub(r"(?m)^[ \t]*sys\.std(?:in|out)\.reconfigure\(.*\)\n", "", text)
    assert unpinned != text
    assert streams(linter.check_modify_stdio(path, unpinned)) == ["stdin", "stdout"]


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
