"""秘密ファイルの一覧が hook と permission でずれないことを固定する。

Bash hook (bashrules/tables.toml の credential_paths / history_basenames) が
守るファイルは、``[file] read_deny_globs`` (Claude の Read / OpenCode の read /
Copilot の check_file_read.py) でも守る。片方にしか無いと、Read ツール側で
読めてしまう。.env は直下以外でも deny / ask になること。

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import fnmatch
import sys
import tomllib
from pathlib import Path

import pytest
from check_bash_hook import COMMON

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "agents"))
import generate as gen
from test_check_bash_sensitive import _matches_any

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "home" / "dot_claude" / "hooks" / "lib" / "bashrules" / "tables.toml"
SENSITIVE = tomllib.loads(TABLES.read_text(encoding="utf-8"))["sensitive"]

# credential_paths は "/.kube/config" のように先頭が "/" の末尾一致用の断片
CREDENTIAL_SAMPLES = [f"~{p}" for p in SENSITIVE["credential_paths"]]
HISTORY_SAMPLES = [f"~/{name}" for name in SENSITIVE["history_basenames"]]


def _opencode_resources(key: str) -> set[str]:
    out: set[str] = set()
    for glob in COMMON["file"][key]:
        out |= set(gen.opencode_path_patterns(glob))
    return out


def _opencode_hits(path: str, resources: set[str]) -> bool:
    """OpenCode の wildcard (``*`` は ``/`` を跨ぐ) で path が当たるか。"""
    return any(fnmatch.fnmatchcase(path, r) for r in resources)


@pytest.mark.parametrize("path", CREDENTIAL_SAMPLES + HISTORY_SAMPLES)
def test_hook_secret_is_in_read_deny_globs(path):
    assert _matches_any(path, COMMON["file"]["read_deny_globs"]), (
        f"{path} は Bash hook が守るのに [file] read_deny_globs に無い"
    )


@pytest.mark.parametrize("path", CREDENTIAL_SAMPLES + HISTORY_SAMPLES)
def test_hook_secret_is_denied_for_opencode_read(path):
    assert _opencode_hits(path, _opencode_resources("read_deny_globs")), path


@pytest.mark.parametrize("path", [".env", "app/.env", "a/b/.env", "/home/u/app/.env"])
def test_dotenv_is_denied_at_any_depth(path):
    assert _matches_any(path.lstrip("/"), COMMON["file"]["read_deny_globs"]), path
    assert _opencode_hits(path, _opencode_resources("read_deny_globs")), path
    assert _matches_any(path.lstrip("/"), COMMON["file"]["write_deny_globs"]), path


@pytest.mark.parametrize("path", [".env.local", "app/.env.production", "/home/u/app/.env.dev"])
def test_dotenv_variants_ask_at_any_depth(path):
    assert _opencode_hits(path, _opencode_resources("read_ask_globs")), path
    assert _opencode_hits(path, _opencode_resources("write_ask_globs")), path
    assert _matches_any(path.lstrip("/"), COMMON["file"]["read_ask_globs"]), path
