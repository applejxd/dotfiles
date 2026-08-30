"""Tests for hook generation in scripts/agents/generate.py.

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
HOOK_SRC_DIR = ROOT / "home" / "dot_claude" / "hooks"

# Claude Code 公式 docs の hook イベント一覧のうち、本リポジトリで使う可能性のあるもの。
# ここに無い名前を common.toml に書いた場合はタイポとみなす。
KNOWN_CLAUDE_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStop",
    "Stop",
    "PreCompact",
    "SessionEnd",
    "Notification",
}

# matcher をサポートしないイベント (設定しても silently ignored)
CLAUDE_EVENTS_WITHOUT_MATCHER = {"UserPromptSubmit", "Stop"}


def load_common() -> dict:
    with COMMON_PATH.open("rb") as f:
        return tomllib.load(f)


COMMON = load_common()


# ---------------------------------------------------------------------------
# common.toml 側の健全性
# ---------------------------------------------------------------------------

def test_hooks_section_exists():
    assert COMMON.get("hooks"), "common.toml に [[hooks]] が無い"


def test_hook_ids_are_unique():
    ids = [h["id"] for h in COMMON["hooks"]]
    assert len(ids) == len(set(ids))


def test_hook_scripts_exist_in_repo():
    for hook in COMMON["hooks"]:
        # chezmoi の executable_ 接頭辞を付けた実体があること
        src = HOOK_SRC_DIR / f"executable_{hook['script']}"
        assert src.is_file(), f"hook script not found: {src}"


def test_hook_runner_is_known():
    for hook in COMMON["hooks"]:
        # 素の Ubuntu には `python` が無いので python3 を使う
        assert hook.get("runner") in {"python3", "bash"}


def test_claude_events_are_known():
    for hook in COMMON["hooks"]:
        event = hook.get("claude_event")
        if event:
            assert event in KNOWN_CLAUDE_EVENTS, f"unknown claude event: {event}"


def test_no_matcher_for_events_without_matcher_support():
    for hook in COMMON["hooks"]:
        if hook.get("claude_event") in CLAUDE_EVENTS_WITHOUT_MATCHER:
            assert "claude_matcher" not in hook, (
                f"{hook['id']}: {hook['claude_event']} は matcher 非対応"
            )


def test_multiedit_is_not_referenced():
    # MultiEdit は Claude Code v2.0 系で削除済み
    for hook in COMMON["hooks"]:
        assert "MultiEdit" not in hook.get("claude_matcher", "")
        assert "MultiEdit" not in hook.get("copilot_matcher", "")


# ---------------------------------------------------------------------------
# Claude 出力
# ---------------------------------------------------------------------------

def test_claude_hooks_cover_every_declared_hook():
    hooks = gen.build_claude_hooks(COMMON)
    commands = [
        cmd["command"]
        for entries in hooks.values()
        for entry in entries
        for cmd in entry["hooks"]
    ]
    for hook in COMMON["hooks"]:
        if hook.get("claude_event"):
            assert any(c.endswith(hook["script"]) for c in commands)


def test_claude_hook_command_is_absolute_path():
    hooks = gen.build_claude_hooks(COMMON)
    for entries in hooks.values():
        for entry in entries:
            for cmd in entry["hooks"]:
                runner, path = cmd["command"].split(" ", 1)
                assert runner in {"python3", "bash"}
                assert path.startswith("/"), f"not absolute: {path}"
                assert "~" not in path and "$HOME" not in path


def test_claude_hook_entry_keys():
    hooks = gen.build_claude_hooks(COMMON)
    for entries in hooks.values():
        for entry in entries:
            assert set(entry) <= {"matcher", "hooks"}
            for cmd in entry["hooks"]:
                assert set(cmd) <= {"type", "command", "timeout"}
                assert cmd["type"] == "command"


def test_claude_timeout_is_emitted():
    hooks = gen.build_claude_hooks(COMMON)
    for entries in hooks.values():
        for entry in entries:
            for cmd in entry["hooks"]:
                # 未指定だと command hook のデフォルトは 600 秒と長いので明示する
                assert isinstance(cmd.get("timeout"), int)


def test_claude_matcher_omitted_when_not_declared():
    hooks = gen.build_claude_hooks(COMMON)
    stop_entries = hooks.get("Stop", [])
    assert stop_entries, "Stop hook が生成されていない"
    for entry in stop_entries:
        assert "matcher" not in entry


def test_claude_settings_merge_preserves_other_keys():
    existing = {"env": {"FOO": "1"}, "includeCoAuthoredBy": False}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["env"] == {"FOO": "1"}
    assert merged["includeCoAuthoredBy"] is False
    assert "hooks" in merged
    assert "permissions" in merged


def test_claude_settings_merge_replaces_hooks():
    existing = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit"}]}}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["hooks"] == gen.build_claude_hooks(COMMON)


# ---------------------------------------------------------------------------
# Copilot 出力
# ---------------------------------------------------------------------------

def test_copilot_hooks_version():
    out = gen.build_copilot_hooks(COMMON)
    assert out["version"] == 1


def test_copilot_matchers_are_anchored():
    out = gen.build_copilot_hooks(COMMON)
    for entries in out["hooks"].values():
        for entry in entries:
            matcher = entry.get("matcher")
            if matcher is None:
                continue
            assert matcher.startswith("^") and matcher.endswith("$"), (
                f"Copilot の matcher は anchored される。明示せよ: {matcher}"
            )


def test_copilot_hook_uses_home_variable():
    out = gen.build_copilot_hooks(COMMON)
    for entries in out["hooks"].values():
        for entry in entries:
            assert "$HOME/.claude/hooks/" in entry["bash"]


def test_copilot_hook_entry_keys():
    out = gen.build_copilot_hooks(COMMON)
    for entries in out["hooks"].values():
        for entry in entries:
            assert set(entry) <= {"matcher", "type", "bash", "timeoutSec"}
            assert entry["type"] == "command"
            assert isinstance(entry["timeoutSec"], int)


def test_copilot_hooks_ignore_existing_content():
    out = gen.merge_copilot_hooks({"hooks": {"Stop": [{"bash": "stale"}]}}, COMMON)
    assert out == gen.build_copilot_hooks(COMMON)


def test_copilot_settings_disable_co_author_trailer():
    merged = gen.merge_copilot_settings({"includeCoAuthoredBy": True}, COMMON)

    assert merged["includeCoAuthoredBy"] is False


# ---------------------------------------------------------------------------
# 両 CLI の整合性
# ---------------------------------------------------------------------------

def test_both_clis_reference_the_same_scripts():
    claude = gen.build_claude_hooks(COMMON)
    copilot = gen.build_copilot_hooks(COMMON)

    def scripts(commands):
        return {c.rsplit("/", 1)[-1] for c in commands}

    claude_scripts = scripts(
        cmd["command"]
        for entries in claude.values()
        for entry in entries
        for cmd in entry["hooks"]
    )
    copilot_scripts = scripts(
        entry["bash"] for entries in copilot["hooks"].values() for entry in entries
    )
    assert claude_scripts == copilot_scripts


def test_generate_target_registry():
    assert "copilot-hooks" in gen.TARGETS
