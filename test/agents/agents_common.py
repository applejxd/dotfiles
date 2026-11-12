"""pi-mcp-servers.toml は chezmoi テンプレートなので、テストからは描画して読む。

実体は ``home/.chezmoitemplates/pi-mcp-servers.toml``。ユーザや機 (is-work) による
出し分けをテンプレート側に持たせているため、素の TOML としては読めない。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "home" / ".chezmoitemplates" / "pi-mcp-servers.toml"
INCLUDE = '{{ includeTemplate "pi-mcp-servers.toml" . }}'


@cache
def render_mcp_servers(username: str | None = None) -> str:
    """pi-mcp-servers.toml を描画する。``username`` を渡すと実行ユーザを差し替える。"""
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


def load_mcp_servers(username: str | None = None) -> dict:
    """描画した pi-mcp-servers.toml を読む (呼び出し側が壊さないよう毎回読み直す)。"""
    return tomllib.loads(render_mcp_servers(username))
