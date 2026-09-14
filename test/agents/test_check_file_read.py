"""Tests for the check_file_read hook and the shared glob matcher.

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "home" / "dot_config" / "agents"
HOOK = ROOT / "home" / "dot_claude" / "hooks" / "executable_check_file_read.py"
COMMON_PATH = AGENTS_DIR / "common.toml"

sys.path.insert(0, str(AGENTS_DIR))
import command_policy as policy  # noqa: E402


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()


def run_hook(tool_name: str, path: str, *, config_dir: Path | None = None) -> dict:
    """hook を実プロセスで起動し、出力 JSON を返す (無出力なら空 dict)。"""
    env = dict(os.environ)
    env["AGENTS_CONFIG_DIR"] = str(config_dir or AGENTS_DIR)
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"path": path},
        }
    )
    proc = subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, f"hook が異常終了: {proc.stderr}"
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def is_denied(result: dict) -> bool:
    return result.get("permissionDecision") == "deny"


# ---------------------------------------------------------------------------
# glob マッチャ (Claude の Read() permission と同じ記法)
# ---------------------------------------------------------------------------

def test_double_star_crosses_directories():
    assert policy.matches_any_glob("a/b/c/server.pem", ["**/*.pem"])


def test_single_star_does_not_cross_directories():
    assert policy.matches_any_glob("a/server.pem", ["*.pem"]) is None
    assert policy.matches_any_glob("server.pem", ["*.pem"])


def test_leading_dot_slash_is_normalized():
    assert policy.matches_any_glob("./certs/server.key", ["**/*.key"])


def test_backslash_paths_are_normalized():
    # Windows から渡るパスでも同じ判定になること
    assert policy.matches_any_glob(r"certs\server.key", ["**/*.key"])


def test_home_paths_match_tilde_globs():
    home = os.path.expanduser("~")
    assert policy.matches_any_glob(f"{home}/.copilot/settings.json",
                                   ["~/.copilot/settings.json"])


def test_returns_the_matching_glob():
    assert policy.matches_any_glob("secrets/db.yaml", ["**/x", "**/secrets/**"]) == (
        "**/secrets/**"
    )


def test_empty_path_never_matches():
    assert policy.matches_any_glob("", ["**/*"]) is None


# ---------------------------------------------------------------------------
# hook の判定
# ---------------------------------------------------------------------------

SECRET_PATHS = [
    "certs/server.key",
    "certs/server.pem",
    "secrets/db.yaml",
    ".env",
    "config/service-account-prod.json",
    "app/refresh.token",
]

LEGIT_PATHS = [
    "README.md",
    "src/tokenizer.py",
    "docs/monkey-patching.md",
    "home/AppData/Roaming/Keyhac/extension/fakeymacs/keyhac.bat",
    "scripts/agents/generate.py",
]


@pytest.mark.parametrize("path", SECRET_PATHS)
def test_secret_paths_are_denied(path):
    assert is_denied(run_hook("view", path)), f"deny されていない: {path}"


@pytest.mark.parametrize("path", LEGIT_PATHS)
def test_legit_paths_are_allowed(path):
    assert not is_denied(run_hook("view", path)), f"誤検知: {path}"


@pytest.mark.parametrize("tool", ["Read", "view"])
def test_both_cli_read_tool_names_are_handled(tool):
    # Claude は Read、Copilot は view。どちらの名前でも同じ判定になること
    assert is_denied(run_hook(tool, "certs/server.key"))


@pytest.mark.parametrize("tool", ["bash", "Bash", "edit", "create", "powershell"])
def test_non_read_tools_are_ignored(tool):
    # 読み取り以外は対象外 (bash は check_bash.py、書き込みは sandbox が担当)
    assert not is_denied(run_hook(tool, "certs/server.key"))


def test_missing_path_is_ignored():
    env = dict(os.environ)
    env["AGENTS_CONFIG_DIR"] = str(AGENTS_DIR)
    payload = json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "view", "tool_input": {}}
    )
    proc = subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_fails_closed_when_policy_is_unreadable(tmp_path):
    # 設定を読めないときに素通りさせない (check_bash.py と同じ方針)
    assert is_denied(run_hook("view", "README.md", config_dir=tmp_path))


# ---------------------------------------------------------------------------
# 設定との結び付き
# ---------------------------------------------------------------------------

def test_hook_is_registered_for_copilot_only():
    hooks = {h["id"]: h for h in COMMON["hooks"]}
    entry = hooks["check_file_read"]
    assert entry["copilot_event"] == "PreToolUse"
    # Claude は同じリストから Read() deny permission を生成済みなので hook 不要。
    # 付けると全ファイル読み取りにプロセス起動コストが乗るだけ。
    assert "claude_event" not in entry, (
        "Claude には permission があるので hook を付けない "
        "(docs/adr/0007-filesystem-guard-boundary.md)"
    )


def test_hook_matcher_covers_read_tools():
    hooks = {h["id"]: h for h in COMMON["hooks"]}
    import re

    matcher = re.compile(hooks["check_file_read"]["copilot_matcher"])
    assert matcher.match("view")
    assert matcher.match("Read")
    assert not matcher.match("bash")
    assert not matcher.match("edit")


def test_hooks_never_use_permission_request_event():
    """`permissionRequest` は使わないこと。

    公式仕様では `permissionRequest` だけが
    「Hook outputs are merged with later hook outputs overriding earlier ones」
    と定義されており、読み込み順は policy → user → **project** → plugins。
    つまりリポジトリ側の hook が user 側の決定を上書きできてしまう。

    一方 `preToolUse` は
    「if any hook returns "deny", the tool is blocked」なので、
    プロジェクト設定から打ち消せない。deny を確実に効かせるため
    こちらだけを使う。
    """
    for hook in COMMON["hooks"]:
        for key in ("claude_event", "copilot_event"):
            event = hook.get(key, "")
            assert event.lower() != "permissionrequest", (
                f"{hook['id']} が permissionRequest を使っている。"
                "プロジェクト側 hook に上書きされるため preToolUse を使うこと"
            )


def test_hook_reads_the_same_list_as_claude_permissions():
    # ルールが 2 箇所に分かれると片方だけ古くなる。同じキーを見ていること。
    assert policy.load_read_deny_globs(str(COMMON_PATH)) == (
        COMMON["file"]["claude_read_deny_globs"]
    )
