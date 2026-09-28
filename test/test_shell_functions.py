"""シェルの関数が、使うコマンドの有無で正しく定義されることの回帰テスト。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "home" / "dot_config" / "shell" / "fzf" / "tools.sh"

# Windows の Git Bash などに Windows 形式のパスを渡しても意味のある検査にならない
pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None, reason="Unix の bash が無い"
)

# 非対話の bash でも起動時に読まれ、関数や PATH を持ち込めてしまう変数
_STARTUP_ENV = {"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"}


def _isolated_env(path: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _STARTUP_ENV and not key.startswith("BASH_FUNC_")
    }
    env["PATH"] = str(path)
    return env


def defined_functions(tmp_path: Path, commands: list[str], script: Path = TOOLS) -> set[str]:
    """commands だけが PATH にある状態で script を読み、定義された関数を返す。"""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in commands:
        fake = bindir / name
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
    bash = shutil.which("bash")
    done = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", 'source "$1" && declare -F', "bash", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=_isolated_env(bindir),
    )
    return {line.split()[-1] for line in done.stdout.splitlines()}


@pytest.mark.parametrize(
    ("commands", "expected"),
    [(["mise"], True), (["ghq"], False), ([], False)],
    ids=["mise のみ", "ghq のみ", "どちらも無い"],
)
def test_mise_select_depends_on_mise(tmp_path, commands, expected):
    """mise-select は mise を呼ぶので、mise があるときだけ定義する (以前は ghq で判定していた)。"""
    assert ("mise-select" in defined_functions(tmp_path, commands)) is expected


def test_defined_functions_ignores_inherited_startup_env(tmp_path, monkeypatch):
    """親の BASH_ENV や export された関数を子の bash へ持ち込まないこと (ヘルパーの回帰)。"""
    monkeypatch.setenv("BASH_ENV", str(TOOLS))
    monkeypatch.setenv("BASH_FUNC_mise-select%%", "() {  :\n}")
    assert "mise-select" not in defined_functions(tmp_path, [])


def test_defined_functions_fails_when_source_fails(tmp_path):
    """読み込みに失敗したら空の結果を返さず失敗すること (ヘルパーの回帰)。"""
    with pytest.raises(subprocess.CalledProcessError):
        defined_functions(tmp_path, [], script=tmp_path / "missing.sh")
