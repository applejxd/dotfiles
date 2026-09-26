"""generate.py が Python 3.11 未満を明示的に拒否することを確認する。

chezmoi は project の uv 環境ではなく `[interpreters.py]` の Python で
modify script を実行する。そこが 3.10 以下だと素の
`ModuleNotFoundError: No module named 'tomllib'` だけが出て、
原因も対処も分からないまま apply が止まる。
see docs/adr/0003-require-python-311-for-agent-configuration.md
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATE = ROOT / "scripts" / "agents" / "generate.py"

# tomllib だけを ModuleNotFoundError にして 3.10 以下の環境を再現する。
# 実際に古い Python を用意しなくても import ガードの経路を通せる。
BLOCK_TOMLLIB = """
import importlib.abc
import runpy
import sys


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'", name=name)
        return None


sys.meta_path.insert(0, Blocker())
sys.argv = ["generate.py", "--target", "claude-settings", "--common", "unused.toml"]
runpy.run_path({path!r}, run_name="__main__")
"""


def run_without_tomllib() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", BLOCK_TOMLLIB.format(path=str(GENERATE))],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


def test_missing_tomllib_fails_with_actionable_message():
    result = run_without_tomllib()

    assert result.returncode != 0
    message = result.stderr
    # 何が足りないか
    assert "Python 3.11" in message
    # どう直すか
    assert "interpreters.py" in message
    assert "chezmoi init" in message
    # どこを読むか
    assert "docs/spec/troubleshooting.md" in message


def test_missing_tomllib_reports_the_offending_interpreter():
    """どの python が使われたかが分からないと、PATH の切り分けができない。"""
    result = run_without_tomllib()

    assert sys.executable in result.stderr


# ---------------------------------------------------------------------------
# run_before_005_python.sh
#
# まっさらな Ubuntu 22.04 以前は python3 が 3.10 で tomllib を持たない。
# ファイル適用 (= modify script) より先に 3.11 以上を 1 つ確保する。
# ---------------------------------------------------------------------------

BEFORE_SCRIPT = ROOT / "home" / ".chezmoiscripts" / "000_unix" / "run_before_005_python.sh"

# 実物の Python を用意しなくても分岐を通せるよう、`-c 'import tomllib'` の
# 成否だけを固定したスタブを置く。
WITH_TOMLLIB = "#!/bin/sh\nexit 0\n"
WITHOUT_TOMLLIB = "#!/bin/sh\nexit 1\n"


def write_stub(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def make_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """PATH と HOME を切り離した最小環境を作る。"""
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    # python の発見とネットワーク遮断が主眼なので、素朴なファイル操作の道具は通す
    for tool in ("bash", "sh", "mktemp", "rm", "uname", "mkdir", "ln"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    # ネットワークへ出ないように curl は必ずスタブ。呼ばれたら記録する。
    write_stub(
        bin_dir / "curl",
        f'#!/bin/sh\necho called >> "{tmp_path / "curl.log"}"\nexit 7\n',
    )
    return bin_dir, home


def run_before_script(bin_dir: Path, home: Path) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    return subprocess.run(
        [bash, str(BEFORE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(home), "PATH": str(bin_dir)},
    )


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_before_script_is_a_no_op_when_python_is_already_usable(tmp_path: Path):
    """既に使える Python があるなら何もしない (毎回の apply を遅くしない)。"""
    bin_dir, home = make_sandbox(tmp_path)
    write_stub(bin_dir / "python3", WITH_TOMLLIB)

    result = run_before_script(bin_dir, home)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "curl.log").exists(), "不要な導入を試みている"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_before_script_finds_toolchain_python_outside_path(tmp_path: Path):
    """mise / uv の Python は shim が PATH に無くても検出する。"""
    bin_dir, home = make_sandbox(tmp_path)
    write_stub(bin_dir / "python3", WITHOUT_TOMLLIB)
    write_stub(
        home / ".local/share/uv/python/cpython-3.13.11-linux-x86_64-gnu/bin/python3.13",
        WITH_TOMLLIB,
    )

    result = run_before_script(bin_dir, home)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "curl.log").exists(), "既にあるのに導入を試みている"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_before_script_never_blocks_apply_when_install_fails(tmp_path: Path):
    """導入に失敗しても apply は止めない。

    ここで非ゼロを返すと chezmoi apply 全体が落ちる。生成が必要になった時点で
    generate.py が理由を説明するので、警告だけ出して先へ進める。
    """
    bin_dir, home = make_sandbox(tmp_path)
    write_stub(bin_dir / "python3", WITHOUT_TOMLLIB)

    result = run_before_script(bin_dir, home)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "curl.log").exists(), "導入を試みていない"
    assert "python3.12" in result.stderr, "手動での復旧手段を案内していない"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_before_script_uses_uv_without_sudo(tmp_path: Path):
    """sudo を使わずユーザ領域の uv で Python を取りに行く。"""
    bin_dir, home = make_sandbox(tmp_path)
    write_stub(bin_dir / "python3", WITHOUT_TOMLLIB)
    uv_log = tmp_path / "uv.log"
    write_stub(
        home / ".local/bin/uv",
        f'#!/bin/sh\necho "$@" >> "{uv_log}"\nexit 0\n',
    )

    result = run_before_script(bin_dir, home)

    assert result.returncode == 0, result.stderr
    assert uv_log.read_text(encoding="utf-8").strip() == "python install 3.13"
    assert not (tmp_path / "curl.log").exists(), "uv があるのに再導入している"
    assert "sudo" not in result.stdout


def test_before_script_runs_ahead_of_file_application():
    """`run_before_` でないと modify script より後になり意味がない。"""
    assert BEFORE_SCRIPT.name.startswith("run_before_")
    assert BEFORE_SCRIPT.parent.name == "000_unix"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_before_script_links_the_interpreter_shim(tmp_path: Path):
    """見つけた Python を chezmoi が指す固定パスへ張る。

    `.chezmoi.toml.tmpl` は init 時に 3.11 以上が PATH に無いと、この shim を
    `[interpreters.py]` へ焼く。後から uv で入る Python は PATH に出ないので、
    ここで橋渡ししないと modify script が全滅する
    (素の Ubuntu で実測: 残差分 16 件すべて modify)。
    """
    bin_dir, home = make_sandbox(tmp_path)
    write_stub(bin_dir / "python3", WITHOUT_TOMLLIB)
    real = home / ".local/share/uv/python/cpython-3.13.11-linux-x86_64-gnu/bin/python3.13"
    write_stub(real, WITH_TOMLLIB)

    result = run_before_script(bin_dir, home)

    assert result.returncode == 0, result.stderr
    shim = home / ".local/bin/chezmoi-python3"
    assert shim.is_symlink(), "shim が張られていない"
    assert shim.resolve() == real.resolve()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix 専用のスクリプト")
def test_shim_path_matches_the_config_template():
    """スクリプトが張る先と、設定が指す先が一致していること。

    別ファイルなので、片方だけ変えると静かに壊れる。
    """
    script = BEFORE_SCRIPT.read_text(encoding="utf-8")
    config = (
        BEFORE_SCRIPT.parents[2] / ".chezmoi.toml.tmpl"
    ).read_text(encoding="utf-8")
    shim_rel = ".local/bin/chezmoi-python3"
    assert shim_rel in script
    assert shim_rel in config
