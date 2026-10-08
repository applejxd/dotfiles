"""common.toml は chezmoi テンプレートなので、テストからは描画して読む。

実体は ``home/dot_config/agents/common.toml.tmpl``。ユーザや OS による
出し分けをテンプレート側に持たせているため、素の TOML としては読めない。
"""

from __future__ import annotations

import atexit
import json
import os
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

# Windows の node は SYSTEMROOT などが無いと起動直後に abort する (exit 134)
_WINDOWS_NODE_ENV = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")


def node_env(**extra: str) -> dict[str, str]:
    """PATH を空にして node を動かす env。plugin が外部コマンドに頼らないことを保つ。"""
    env = {"PATH": ""}
    if os.name == "nt":
        env.update({k: os.environ[k] for k in _WINDOWS_NODE_ENV if k in os.environ})
    env.update(extra)
    return env


@cache
def render_common(username: str | None = None) -> str:
    """common.toml を描画する。``username`` を渡すと実行ユーザを差し替える。"""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi is not installed", allow_module_level=True)
    template = INCLUDE
    if username is not None:
        context = json.dumps(
            json.dumps({"chezmoi": {"username": username, "homeDir": "/test-home"}})
        )
        template = f"{{{{ with {context} | fromJson }}}}{INCLUDE}{{{{ end }}}}"
    result = subprocess.run(
        [chezmoi, "--source", str(ROOT), "execute-template", template],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def load_common(username: str | None = None, *, raw: bool = False) -> dict:
    """描画した common.toml を読む (呼び出し側が壊さないよう毎回読み直す)。

    ``generate.load_common`` と同じく、``[pi]`` の共有の節を OpenCode の位置へ写した形で返す。
    ``raw=True`` なら写さない (描画したそのままの形)。
    """
    common = tomllib.loads(render_common(username))
    if raw:
        return common
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "agents"))
    import generate

    return generate.resolve_pi_shared(common)


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
