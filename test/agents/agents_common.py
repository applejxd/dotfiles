"""common.toml は chezmoi テンプレートなので、テストからは描画して読む。

実体は ``home/dot_config/agents/common.toml.tmpl``。ユーザや OS による
出し分けをテンプレート側に持たせているため、素の TOML としては読めない。
"""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import tempfile
import tomllib
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "home" / "dot_config" / "agents"
TEMPLATE = ROOT / "home" / "dot_config" / "agents" / "common.toml.tmpl"
INCLUDE = '{{ includeTemplate "dot_config/agents/common.toml.tmpl" . }}'


@cache
def render_common(username: str | None = None) -> str:
    """common.toml を描画する。``username`` を渡すと実行ユーザを差し替える。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed", allow_module_level=True)
    template = INCLUDE
    if username is not None:
        context = json.dumps(json.dumps({"chezmoi": {"username": username}}))
        template = f"{{{{ with {context} | fromJson }}}}{INCLUDE}{{{{ end }}}}"
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", template],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def load_common(username: str | None = None) -> dict:
    """描画した common.toml を読む (呼び出し側が壊さないよう毎回読み直す)。"""
    return tomllib.loads(render_common(username))


@cache
def agents_config_dir(username: str | None = None) -> Path:
    """hook が実行時に読む形の ``~/.config/agents`` 相当を用意する。

    描画済みの ``common.toml`` と ``command_policy.py`` を置く。hook は
    ``AGENTS_CONFIG_DIR`` 配下の 2 つを読むので、配備後と同じ状態になる。
    """
    base = Path(tempfile.mkdtemp(prefix="agents-config-"))
    atexit.register(shutil.rmtree, base, ignore_errors=True)
    (base / "common.toml").write_text(render_common(username), encoding="utf-8")
    shutil.copy2(SOURCE_DIR / "command_policy.py", base / "command_policy.py")
    return base
