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


def test_windows_python_hooks_use_latest_python_3():
    claude = gen.build_claude_hooks(COMMON, platform="nt")
    copilot = gen.build_copilot_hooks(COMMON, platform="nt")

    commands = [
        cmd["command"]
        for entries in claude.values()
        for entry in entries
        for cmd in entry["hooks"]
    ]
    commands.extend(
        entry["bash"]
        for entries in copilot["hooks"].values()
        for entry in entries
    )
    python_commands = [command for command in commands if command.endswith(".py")]
    assert python_commands
    assert all(command.startswith("py -3 ") for command in python_commands)


def test_runtime_code_has_no_external_tomli_dependency():
    runtime_files = [
        ROOT / "scripts" / "agents" / "generate.py",
        ROOT / "home" / "dot_config" / "agents" / "command_policy.py",
    ]
    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        assert "import tomllib" in source
        assert "import tomli" not in source


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
# 外部ツール (Orca 等) の hook を模したフィクスチャ
# ---------------------------------------------------------------------------

# Orca が ~/.claude/settings.json に注入する hook を模したコマンド
FOREIGN_COMMAND = (
    'if [ -f "${HOME-}/.orca/agent-hooks/claude-hook.sh" ]; then '
    '/bin/sh "${HOME-}/.orca/agent-hooks/claude-hook.sh"; else printf \'{}\\n\'; fi'
)
MANAGED_DIR = gen.expand_user(gen.HOOKS_DIR)


def foreign_entry(matcher: str | None = None) -> dict:
    entry: dict = {}
    if matcher:
        entry["matcher"] = matcher
    entry["hooks"] = [{"type": "command", "command": FOREIGN_COMMAND, "timeout": 10}]
    return entry


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
    # matcher 非対応イベント (Stop 等) の hook は common.toml に無いこともあるので
    # 合成した設定で挙動を確認する
    synthetic = {
        "hooks": [
            {
                "id": "matcherless",
                "script": "check_bash.py",
                "runner": "python3",
                "claude_event": "Stop",
                "timeout_sec": 30,
            }
        ]
    }
    entries = gen.build_claude_hooks(synthetic)["Stop"]
    assert entries
    for entry in entries:
        assert "matcher" not in entry


def test_claude_settings_merge_preserves_other_keys():
    existing = {"env": {"FOO": "1"}, "includeCoAuthoredBy": False}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["env"] == {"FOO": "1"}
    assert merged["includeCoAuthoredBy"] is False
    assert "hooks" in merged
    assert "permissions" in merged


def test_claude_settings_merge_regenerates_managed_hooks():
    # hooks リストを持たない項目は解釈できないので温存し、管理 hook は再生成する
    orphan = {"matcher": "Edit|Write|MultiEdit"}
    merged = gen.merge_claude_settings({"hooks": {"PreToolUse": [orphan]}}, COMMON)
    expected = gen.build_claude_hooks(COMMON)
    assert merged["hooks"]["PreToolUse"] == expected["PreToolUse"] + [orphan]
    assert merged["hooks"]["PostToolUse"] == expected["PostToolUse"]


def test_stale_managed_hook_is_replaced_not_duplicated():
    # common.toml から消したスクリプトの残骸は除去され、重複もしない。
    # 同じイベントに同居する外部 hook は残ること (全置換では落ちる)。
    stale = {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": f"python3 {MANAGED_DIR}/removed-long-ago.py",
                "timeout": 30,
            }
        ],
    }
    existing = {"hooks": {"PreToolUse": [stale, foreign_entry("*")]}}
    merged = gen.merge_claude_settings(existing, COMMON)
    commands = [
        cmd["command"]
        for entries in merged["hooks"].values()
        for entry in entries
        for cmd in entry["hooks"]
    ]
    assert not any("removed-long-ago.py" in c for c in commands)
    assert len(commands) == len(set(commands))
    assert FOREIGN_COMMAND in commands
    expected = gen.build_claude_hooks(COMMON)
    assert merged["hooks"]["PreToolUse"] == expected["PreToolUse"] + [foreign_entry("*")]


# ---------------------------------------------------------------------------
# hooks は外部ツール (Orca 等) との共有領域なので、管理外の項目を消さないこと
# ---------------------------------------------------------------------------

def test_is_managed_hook_command_detects_both_path_forms():
    assert gen.is_managed_hook_command(f"python3 {MANAGED_DIR}/check_bash.py")
    assert gen.is_managed_hook_command("python3 $HOME/.claude/hooks/check_bash.py")
    assert not gen.is_managed_hook_command(FOREIGN_COMMAND)
    assert not gen.is_managed_hook_command(None)


def test_foreign_hooks_are_preserved_on_shared_event():
    # chezmoi も使う PreToolUse に外部 hook が同居していても消えない
    existing = {"hooks": {"PreToolUse": [foreign_entry("*")]}}
    merged = gen.merge_claude_settings(existing, COMMON)
    commands = [c["command"] for e in merged["hooks"]["PreToolUse"] for c in e["hooks"]]
    assert FOREIGN_COMMAND in commands
    # 管理 hook が先、外部 hook が後 (既存ファイルの並びに合わせて差分を最小化)
    assert commands[-1] == FOREIGN_COMMAND
    assert any(MANAGED_DIR in c for c in commands)


def test_foreign_only_events_are_preserved():
    # chezmoi が一切使わないイベントはキーごと温存する
    existing = {
        "hooks": {
            "SessionStart": [foreign_entry()],
            "PermissionRequest": [foreign_entry("*")],
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    for event in ("SessionStart", "PermissionRequest"):
        assert event in merged["hooks"], f"{event} が消えている"
        assert merged["hooks"][event][0]["hooks"][0]["command"] == FOREIGN_COMMAND


def test_mixed_entry_is_filtered_per_command():
    # 1 エントリに管理 / 外部が混在する場合はコマンド単位で絞り込む
    mixed = {
        "matcher": "Bash",
        "hooks": [
            {"type": "command", "command": f"python3 {MANAGED_DIR}/check_bash.py"},
            {"type": "command", "command": FOREIGN_COMMAND, "timeout": 10},
        ],
    }
    kept = gen.strip_managed_claude_hooks([mixed])
    assert len(kept) == 1
    assert [c["command"] for c in kept[0]["hooks"]] == [FOREIGN_COMMAND]
    # 元のエントリを破壊しない
    assert len(mixed["hooks"]) == 2


def test_event_becoming_empty_is_dropped():
    # 管理 hook しか無いイベントは消える。同じ入力で外部 hook が同居する
    # イベントは残るので、「そもそも生成しない」のとは区別できる。
    managed_only = {
        "hooks": [{"type": "command", "command": f"python3 {MANAGED_DIR}/gone.py"}]
    }
    existing = {
        "hooks": {
            "PreCompact": [managed_only],
            "SessionEnd": [managed_only, foreign_entry()],
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    assert "PreCompact" not in merged["hooks"]
    assert merged["hooks"]["SessionEnd"] == [foreign_entry()]


def test_falsy_foreign_value_is_preserved():
    # 空リスト以外の falsy な値も、解釈できない以上は落とさない
    existing = {"hooks": {"WeirdEvent": {}}}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["hooks"]["WeirdEvent"] == {}


def test_merge_is_idempotent():
    existing = {
        "hooks": {
            "PreToolUse": [foreign_entry("*")],
            "SessionStart": [foreign_entry()],
        }
    }
    once = gen.merge_claude_settings(existing, COMMON)
    twice = gen.merge_claude_settings(once, COMMON)
    assert once == twice


def test_merge_tolerates_missing_or_broken_hooks():
    assert gen.merge_claude_settings({}, COMMON)["hooks"] == gen.build_claude_hooks(COMMON)


def test_unparseable_shapes_are_preserved_not_dropped():
    # 解釈できない形は将来のスキーマ変更や未知のツールの可能性があるので残す。
    # ただし chezmoi も生成するイベントで list 以外だった場合は結合できないので
    # 生成物を優先する (Claude のスキーマ上 list 以外は元々無効)。
    existing = {
        "hooks": {
            "WeirdEvent": {"command": "inline"},
            "SessionStart": [{"matcher": "*", "command": "orca-inline"}],
            "PreToolUse": "not-a-list",
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["hooks"]["WeirdEvent"] == {"command": "inline"}
    assert merged["hooks"]["SessionStart"] == [{"matcher": "*", "command": "orca-inline"}]
    assert merged["hooks"]["PreToolUse"] == gen.build_claude_hooks(COMMON)["PreToolUse"]


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


# ---------------------------------------------------------------------------
# Gemini 出力 (hooks は Orca が書き込むので触らないこと)
# ---------------------------------------------------------------------------

def test_gemini_target_is_registered():
    assert "gemini-settings" in gen.TARGETS


def test_gemini_managed_branches_are_applied():
    merged = gen.merge_gemini_settings({}, COMMON)
    assert merged["general"]["sessionRetention"]["enabled"] is True
    assert merged["security"]["auth"]["selectedType"] == "oauth-personal"
    assert merged["experimental"]["skills"]["enabled"] is True
    assert merged["experimental"]["enableAgents"] is True
    assert merged["mcpServers"]["deepwiki"]["httpUrl"] == "https://mcp.deepwiki.com/mcp"


def test_gemini_preserves_foreign_hooks():
    existing = {"hooks": {"PreToolUse": [foreign_entry("*")]}}
    merged = gen.merge_gemini_settings(existing, COMMON)
    assert merged["hooks"] == existing["hooks"]


def test_gemini_preserves_sibling_keys_in_managed_branch():
    # 管理下の枝でも、管理外の兄弟キーは残す (mcpServers の他サーバなど)
    existing = {
        "mcpServers": {"other": {"command": "foo"}},
        "experimental": {"someFlag": True},
    }
    merged = gen.merge_gemini_settings(existing, COMMON)
    assert merged["mcpServers"]["other"] == {"command": "foo"}
    assert merged["experimental"]["someFlag"] is True
    assert merged["experimental"]["enableAgents"] is True


def test_gemini_preserves_existing_key_order():
    # Sprig の toPrettyJson と違いキー順を並べ替えないこと (差分ノイズ対策)
    existing = {"zzz": 1, "hooks": {}, "aaa": 2}
    merged = gen.merge_gemini_settings(existing, COMMON)
    assert list(merged)[:3] == ["zzz", "hooks", "aaa"]


def test_gemini_merge_is_idempotent():
    existing = {"hooks": {"SessionStart": [foreign_entry()]}, "theme": "Default"}
    once = gen.merge_gemini_settings(existing, COMMON)
    assert gen.merge_gemini_settings(once, COMMON) == once


def test_gemini_merge_does_not_mutate_input():
    existing = {"experimental": {"someFlag": True}}
    gen.merge_gemini_settings(existing, COMMON)
    assert existing == {"experimental": {"someFlag": True}}
