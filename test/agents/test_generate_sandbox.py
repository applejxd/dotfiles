"""Tests for sandbox settings generation in scripts/agents/generate.py.

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402

COMMON_PATH = ROOT / "home" / "dot_config" / "agents" / "common.toml"


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()


# ---------------------------------------------------------------------------
# common.toml 側の健全性
# ---------------------------------------------------------------------------

def test_sandbox_section_exists():
    assert "sandbox" in COMMON
    assert COMMON["sandbox"]["deny_read"]
    assert COMMON["sandbox"]["deny_write_extra"]
    assert COMMON["sandbox"]["copilot_deny_paths"]


def test_sandbox_paths_use_home_prefix_or_are_project_relative():
    # sandbox の記法は permission の glob 記法と異なり、user 設定では無印/`./`
    # が ~/.claude 基準になる。ホーム全体に効かせるパスは必ず `~/` で始める
    # ことをここで固定しておく (書き忘れの防止)。
    sandbox = COMMON["sandbox"]
    for key in ("deny_read", "deny_write_extra", "copilot_deny_paths"):
        for path in sandbox[key]:
            assert path.startswith("~/"), (
                f"[sandbox].{key} の '{path}' は '~/' から始まっていない。"
                "user 設定では無印パスが ~/.claude 基準になるため意図しない"
                "範囲になる可能性がある。"
            )


def test_copilot_deny_paths_have_no_wildcards():
    # Copilot の Filesystem パス指定はワイルドカード非対応・絶対パス限定
    # (公式ドキュメントに明記)。誤って glob を混ぜないようにする。
    for path in COMMON["sandbox"]["copilot_deny_paths"]:
        assert "*" not in path, f"copilot_deny_paths に glob は使えない: {path}"


# ---------------------------------------------------------------------------
# build_claude_sandbox() の出力
# ---------------------------------------------------------------------------

def test_build_claude_sandbox_enabled():
    sandbox = gen.build_claude_sandbox(COMMON)
    assert sandbox["enabled"] is True


def test_build_claude_sandbox_deny_read_matches_common():
    sandbox = gen.build_claude_sandbox(COMMON)
    deny_read = sandbox["filesystem"]["denyRead"]
    assert set(deny_read) == set(COMMON["sandbox"]["deny_read"])
    # 順序が安定していること (uniq が元の順序を保持する)
    assert len(deny_read) == len(set(deny_read))


def test_build_claude_sandbox_deny_write_is_superset_of_deny_read():
    sandbox = gen.build_claude_sandbox(COMMON)
    deny_read = set(sandbox["filesystem"]["denyRead"])
    deny_write = set(sandbox["filesystem"]["denyWrite"])
    assert deny_read <= deny_write
    assert set(COMMON["sandbox"]["deny_write_extra"]) <= deny_write
    assert len(sandbox["filesystem"]["denyWrite"]) == len(deny_write)


def test_build_claude_sandbox_no_duplicates_when_overlap():
    # deny_write_extra に deny_read と同じパスを重複して書いても、
    # denyWrite が二重に持たないこと。
    common = {
        "sandbox": {
            "deny_read": ["~/.ssh", "~/.env"],
            "deny_write_extra": ["~/.ssh", "~/.bashrc"],
        }
    }
    sandbox = gen.build_claude_sandbox(common)
    assert sandbox["filesystem"]["denyWrite"] == ["~/.ssh", "~/.env", "~/.bashrc"]


def test_build_claude_sandbox_empty_section():
    sandbox = gen.build_claude_sandbox({})
    assert sandbox == {
        "enabled": True,
        "filesystem": {"denyRead": [], "denyWrite": []},
    }


# ---------------------------------------------------------------------------
# merge_claude_settings() への統合
# ---------------------------------------------------------------------------

def test_merge_claude_settings_includes_sandbox():
    merged = gen.merge_claude_settings({}, COMMON)
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["filesystem"]["denyRead"]


def test_merge_claude_settings_preserves_other_keys():
    existing = {"someOtherUserKey": "keep-me", "sandbox": {"enabled": False}}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["someOtherUserKey"] == "keep-me"
    # sandbox は common.toml 由来で常に全置換される (enabled=True を強制)
    assert merged["sandbox"]["enabled"] is True
