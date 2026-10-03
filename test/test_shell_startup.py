"""シェルの起動契約の回帰テスト。

全シェル共通の env (.zshenv / .bash_profile / shellenv.sh) は PATH と環境変数だけを扱い、
alias・出力・対話専用の設定は対話 rc に限る。契約は docs/spec/structure.md の
「シェルの起動契約」を参照。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_DIR = ROOT / "home" / "dot_config" / "shell"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="Unix の bash が無い"
)

_STARTUP_ENV = {"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "ZDOTDIR"}
_USER_ENV = {"EDITOR", "VISUAL", "LC_ALL", "LANG"}


def render(source: Path) -> str:
    """テンプレートを chezmoi で描画する。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed")
    text = source.read_text(encoding="utf-8")
    if source.suffix != ".tmpl":
        return text
    done = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """配布物だけを置いた一時 HOME。zinit / mise / fzf などの外部依存は置かない。"""
    home = tmp_path / "home"
    shell = home / ".config" / "shell"
    shell.mkdir(parents=True)
    env_files = {
        "shellenv.sh": SHELL_DIR / "shellenv.sh.tmpl",
        "shellrc.sh": SHELL_DIR / "shellrc.sh.tmpl",
    }
    for name in ("osxenv.sh", "osxrc.sh", "wslenv.sh", "wslrc.sh"):
        if (SHELL_DIR / name).exists():
            env_files[name] = SHELL_DIR / name
    for name, src in env_files.items():
        (shell / name).write_text(render(src), encoding="utf-8")
    for name, src in {
        ".zshenv": ROOT / "home" / "dot_zshenv",
        ".zshrc": ROOT / "home" / "dot_zshrc.tmpl",
        ".bash_profile": ROOT / "home" / "dot_bash_profile",
        ".bashrc": ROOT / "home" / "dot_bashrc",
    }.items():
        (home / name).write_text(render(src), encoding="utf-8")
    return home


def run(argv: list[str], home: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _STARTUP_ENV | _USER_ENV and not k.startswith("BASH_FUNC_")
    }
    env["HOME"] = str(home)
    env.update(extra)
    return subprocess.run(
        argv,
        cwd=home,  # .zshenv が git リポジトリ内で TMPDIR を書き換えないように
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
        timeout=30,
    )


def _zsh() -> str:
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is not installed")
    return zsh


# ---- 非対話 zsh (.zshenv だけ読まれる。OpenCode などの agent がこの形で起動する) ----


def _baseline_aliases(home: Path) -> str:
    """rc を一切読まない zsh (-f) が持つ alias。zsh 組み込みの run-help などが含まれる。"""
    return run([_zsh(), "-f", "-c", "alias"], home).stdout


def test_noninteractive_zsh_has_no_alias_and_no_output(home):
    done = run([_zsh(), "-c", "alias"], home)
    assert done.returncode == 0, done.stderr
    assert done.stdout == _baseline_aliases(home) and done.stderr == ""


@pytest.mark.parametrize("var", ["LC_ALL", "EDITOR", "VISUAL", "LANG"])
def test_noninteractive_zsh_keeps_explicit_env(home, var):
    done = run([_zsh(), "-c", f'print -r -- "${var}"'], home, **{var: "explicit-value"})
    assert done.stdout.strip() == "explicit-value", done.stderr


def test_noninteractive_zsh_defaults_when_unset(home):
    done = run([_zsh(), "-c", 'print -r -- "$LC_ALL $LANG $EDITOR $VISUAL"'], home)
    lc_all, lang, editor, visual = done.stdout.split()
    assert (lc_all, lang) == ("ja_JP.UTF-8", "ja_JP.UTF-8")
    assert editor and visual == editor


def test_zshrc_returns_immediately_when_noninteractive(home):
    with (home / ".zshrc").open("a", encoding="utf-8") as f:
        f.write('\necho "zshrc body ran"\n')  # 早期 return が効かないと出力される
    done = run([_zsh(), "-c", "source ~/.zshrc; echo after"], home)
    assert done.stdout == "after\n", (done.stdout, done.stderr)
    assert done.stderr == ""


def test_zshenv_does_not_source_global_zshrc(home):
    assert "/etc/zsh/zshrc" not in (home / ".zshenv").read_text(encoding="utf-8")
    assert "/etc/zsh/zshrc" in (home / ".zshrc").read_text(encoding="utf-8")


# ---- 非対話 login bash ----


def test_noninteractive_login_bash_stays_plain(home):
    script = 'alias; shopt -p dotglob nocaseglob; printf "%s\\n" "$LC_ALL"'
    done = run(["bash", "-lc", script], home)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    lines = done.stdout.splitlines()
    assert "shopt -u dotglob" in lines and "shopt -u nocaseglob" in lines
    assert not any(line.startswith("alias ") for line in lines)
    assert lines[-1] == "ja_JP.UTF-8"


def test_noninteractive_login_bash_keeps_explicit_env(home):
    done = run(["bash", "-lc", 'echo "$LC_ALL:$EDITOR"'], home, LC_ALL="C", EDITOR="foo")
    assert done.stdout.strip() == "C:foo", done.stderr


# ---- shellenv.sh 単体 ----


def test_shellenv_defines_no_alias_or_function(home):
    done = run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'shopt -s expand_aliases; source "$HOME/.config/shell/shellenv.sh"; alias; declare -F',
        ],
        home,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == "" and done.stderr == ""


def test_shellrc_defines_agent_alias(home):
    done = run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            'shopt -s expand_aliases; source "$HOME/.config/shell/shellrc.sh"; alias agent',
        ],
        home,
    )
    assert "alias agent=" in done.stdout, done.stderr


# ---- zpack ----


def _zpack_script(home: Path) -> str:
    text = (home / ".config" / "shell" / "shellrc.sh").read_text(encoding="utf-8")
    m = re.search(r"^function zpack\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, "zpack が見つからない"
    return m.group(0)


@pytest.fixture
def zpack(home, tmp_path):
    if shutil.which("zstd") is None or shutil.which("tar") is None:
        pytest.skip("zstd / tar が無い")
    work = tmp_path / "work"
    work.mkdir()
    (work / "src").mkdir()
    (work / "src" / "f.txt").write_text("hello", encoding="utf-8")

    def call(*args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        script = _zpack_script(home) + '\nzpack "$@"\n'
        return run(
            ["bash", "-c", script, "bash", *args],
            work,
            HOME=str(home),
            **extra,
        )

    call.work = work
    return call


def test_zpack_creates_archive_without_leftover(zpack):
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1")
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in zpack.work.iterdir()) == ["out.tar.zst", "src"]


def test_zpack_does_not_overwrite_existing_output(zpack):
    out = zpack.work / "out.tar.zst"
    out.write_text("precious", encoding="utf-8")
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1")
    assert done.returncode != 0
    assert out.read_text(encoding="utf-8") == "precious"
    assert sorted(p.name for p in zpack.work.iterdir()) == ["out.tar.zst", "src"]


def test_zpack_failure_leaves_no_temp_file(zpack, tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "zstd").write_text('#!/bin/sh\necho partial > "$4"\nexit 1\n', encoding="utf-8")
    (fake / "zstd").chmod(0o755)
    done = zpack("src", "out.tar.zst", ZPACK_LEVEL="1", PATH=f"{fake}:{os.environ['PATH']}")
    assert done.returncode != 0
    assert sorted(p.name for p in zpack.work.iterdir()) == ["src"]
