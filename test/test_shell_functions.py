"""シェルの関数が、使うコマンドの有無で正しく定義されることの回帰テスト。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "home" / "dot_config" / "shell" / "fzf" / "tools.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash が無い")


def defined_functions(tmp_path: Path, commands: list[str]) -> set[str]:
    """commands だけが PATH にある状態で tools.sh を読み、定義された関数を返す。"""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in commands:
        fake = bindir / name
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
    bash = shutil.which("bash")
    done = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", f'PATH="{bindir}"; source "{TOOLS}"; declare -F'],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
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
