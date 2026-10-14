"""Tests for hook generation in scripts/agents/hooks.py (called from generate.py).

Run with: ``uv run --with pytest --no-project pytest test/agents/`` or
``python3 -m pytest test/agents/``.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import generate as gen  # noqa: E402
import hooks as hk  # noqa: E402
from agents_common import agents_config_dir, load_common  # noqa: E402

COMMON_PATH = agents_config_dir() / "common.toml"

HOOK_SRC_DIR = ROOT / "home" / "dot_claude" / "hooks"

# 撤去した hook の登録を模した入力 (生成・統合の関数そのものの試験用)。
# common.toml の [[hooks]] には、いまは Claude / Copilot の登録が無い (ADR-0017)。
# 古い登録が settings.json に残っていても、生成側が外せることを確かめるために形を残す。
SAMPLE_HOOKS = [
    {
        "id": "check_bash",
        "script": "check_bash.py",
        "runner": "python3",
        "claude_event": "PreToolUse",
        "claude_matcher": "Bash",
        "timeout_sec": 30,
    },
    {
        "id": "redirect-tmp",
        "script": "redirect-tmp.py",
        "runner": "python3",
        "claude_event": "PreToolUse",
        "claude_matcher": "Bash|Write|Edit",
        "timeout_sec": 30,
    },
    {
        "id": "markdownlint",
        "script": "markdownlint.sh",
        "runner": "bash",
        "claude_event": "PostToolUse",
        "claude_matcher": "Edit|Write",
        "timeout_sec": 30,
    },
    {
        "id": "format-file",
        "script": "format-file.sh",
        "runner": "bash",
        "claude_event": "PostToolUse",
        "claude_matcher": "Edit|Write",
        "timeout_sec": 30,
    },
]
SAMPLE_RETIRED = [
    "block-dangerous-commands.sh",
    "update-adr-on-stop.py",
    "checkpoint_precompact.py",
    "checkpoint_restore.py",
    "checkpoint_restore_pending.py",
]

LIVE = load_common()
COMMON = {**LIVE, "hooks": SAMPLE_HOOKS, "retired_hooks": {"scripts": SAMPLE_RETIRED}}


# ---------------------------------------------------------------------------
# common.toml 側 (撤去後の状態)
# ---------------------------------------------------------------------------


def test_no_hook_is_registered_for_claude_or_copilot():
    """[[hooks]] は pi の編集後の整形だけ。Claude / Copilot へは何も登録しない (ADR-0017)。"""
    assert LIVE["hooks"]
    for hook in LIVE["hooks"]:
        assert hook.get("post_edit") is True, hook["id"]
        assert not [k for k in hook if k.startswith(("claude_", "copilot_"))], hook["id"]
    assert hk.build_claude_hooks(LIVE) == {}


def test_live_hooks_are_unique_and_their_scripts_exist():
    ids = [h["id"] for h in LIVE["hooks"]]
    assert len(ids) == len(set(ids))
    for hook in LIVE["hooks"]:
        assert hook.get("runner") in {"python3", "bash"}
        src = HOOK_SRC_DIR / f"executable_{hook['script']}"
        assert src.is_file(), f"hook script not found: {src}"


def test_the_retired_judge_hooks_are_listed_so_stale_registrations_are_removed():
    retired = set(LIVE["retired_hooks"]["scripts"])
    assert {"check_bash.py", "redirect-tmp.py", "check_file_read.py"} <= retired
    assert not retired & {h["script"] for h in LIVE["hooks"]}


def test_stale_judge_hook_registrations_are_removed_from_an_existing_settings():
    """以前の生成物が settings.json に残っていても、外部ツールの hook を残して外す。"""
    old = hk.build_claude_hooks(COMMON)
    foreign = {"matcher": "*", "hooks": [{"type": "command", "command": "other-tool hook"}]}
    existing = {"hooks": {**old, "SessionStart": [foreign]}}
    merged = gen.merge_claude_settings(existing, LIVE)
    assert merged["hooks"] == {"SessionStart": [foreign]}


def test_pi_post_edit_hooks_come_from_the_post_edit_flag():
    out = gen.pi_post_edit_hooks(LIVE)
    assert [h["id"] for h in out] == ["markdownlint", "format-file"]
    assert (
        gen.pi_post_edit_hooks({"hooks": [{"id": "x", "script": "x.sh", "runner": "bash"}]}) == []
    )


def test_the_copilot_hooks_target_is_gone():
    assert "copilot-hooks" not in gen.TARGETS
    assert not (ROOT / "home" / "dot_copilot" / "hooks").exists()
    assert ".copilot/hooks/from-claude.json" in (ROOT / "home" / ".chezmoiremove").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# common.toml 側の健全性
# ---------------------------------------------------------------------------


def test_runtime_code_has_no_external_tomli_dependency():
    runtime_files = [
        ROOT / "scripts" / "agents" / "generate.py",
        ROOT / "home" / "dot_config" / "agents" / "command_policy.py",
    ]
    for path in runtime_files:
        source = path.read_text(encoding="utf-8")
        assert "import tomllib" in source
        assert "import tomli" not in source


# ---------------------------------------------------------------------------
# 外部ツール (Orca 等) の hook を模したフィクスチャ
# ---------------------------------------------------------------------------

# Orca が ~/.claude/settings.json に注入する hook を模したコマンド
FOREIGN_COMMAND = (
    'if [ -f "${HOME-}/.orca/agent-hooks/claude-hook.sh" ]; then '
    "/bin/sh \"${HOME-}/.orca/agent-hooks/claude-hook.sh\"; else printf '{}\\n'; fi"
)
MANAGED_DIR = hk.expand_user(hk.HOOKS_DIR)


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
    hooks = hk.build_claude_hooks(COMMON)
    commands = [
        cmd["command"] for entries in hooks.values() for entry in entries for cmd in entry["hooks"]
    ]
    for hook in COMMON["hooks"]:
        if hook.get("claude_event"):
            assert any(c.rstrip("\"'").endswith(hook["script"]) for c in commands)


def test_claude_hook_command_is_absolute_path():
    hooks = hk.build_claude_hooks(COMMON)
    for entries in hooks.values():
        for entry in entries:
            for cmd in entry["hooks"]:
                args = shlex.split(cmd["command"], posix=os.name != "nt")
                assert args[0] in ({"py", "bash"} if os.name == "nt" else {"python3", "bash"})
                if args[0] == "py":
                    assert args[1:3] == ["-3", "-B"]
                path = args[-1].strip('"')
                assert Path(path).is_absolute(), f"not absolute: {path}"
                assert "~" not in path and "$HOME" not in path


def test_claude_hook_entry_keys():
    hooks = hk.build_claude_hooks(COMMON)
    for entries in hooks.values():
        for entry in entries:
            assert set(entry) <= {"matcher", "hooks"}
            for cmd in entry["hooks"]:
                assert set(cmd) <= {"type", "command", "timeout"}
                assert cmd["type"] == "command"


def test_claude_timeout_is_emitted():
    hooks = hk.build_claude_hooks(COMMON)
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
    entries = hk.build_claude_hooks(synthetic)["Stop"]
    assert entries
    for entry in entries:
        assert "matcher" not in entry


def test_claude_settings_merge_preserves_other_keys():
    existing = {"env": {"FOO": "1"}, "includeCoAuthoredBy": False}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["env"] == {"FOO": "1", "DISABLE_AUTOUPDATER": "1"}
    assert merged["includeCoAuthoredBy"] is False
    assert "hooks" in merged
    assert "permissions" in merged


def test_claude_settings_merge_regenerates_managed_hooks():
    # hooks リストを持たない項目は解釈できないので温存し、管理 hook は再生成する
    orphan = {"matcher": "Edit|Write|MultiEdit"}
    merged = gen.merge_claude_settings({"hooks": {"PreToolUse": [orphan]}}, COMMON)
    expected = hk.build_claude_hooks(COMMON)
    assert merged["hooks"]["PreToolUse"] == expected["PreToolUse"] + [orphan]
    assert merged["hooks"]["PostToolUse"] == expected["PostToolUse"]


def test_stale_managed_hook_is_replaced_not_duplicated():
    # 撤去済み (retired_hooks) のスクリプトの残骸は除去され、重複もしない。
    # 同じイベントに同居する外部 hook は残ること (全置換では落ちる)。
    stale = {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": f"python3 {MANAGED_DIR}/checkpoint_restore.py",
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
    assert not any("checkpoint_restore.py" in c for c in commands)
    assert len(commands) == len(set(commands))
    assert FOREIGN_COMMAND in commands
    expected = hk.build_claude_hooks(COMMON)
    assert merged["hooks"]["PreToolUse"] == expected["PreToolUse"] + [foreign_entry("*")]


# ---------------------------------------------------------------------------
# hooks は外部ツール (Orca 等) との共有領域なので、管理外の項目を消さないこと
# ---------------------------------------------------------------------------

SCRIPTS = hk.managed_hook_scripts(COMMON)

# `herdr integration install claude` が settings.json へ足す hook (Docker で実測)。
# スクリプトは HOOKS_DIR に置かれるが、このリポジトリの hook ではない
HERDR_ENTRY = {
    "matcher": "^(startup|resume|clear|compact|fork)$",
    "hooks": [
        {
            "type": "command",
            "command": f"bash '{MANAGED_DIR}/herdr-agent-state.sh' session",
            "timeout": 10,
        }
    ],
}


def test_herdr_hook_in_the_shared_directory_is_preserved():
    """HOOKS_DIR に置かれた外部の hook を自分の hook と誤認して消さない。"""
    existing = {"hooks": {"SessionStart": [HERDR_ENTRY]}}
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["hooks"]["SessionStart"] == [HERDR_ENTRY]


def test_generation_is_stable_with_herdr_installer_in_between():
    """生成 -> Herdr の導入 -> 生成 を繰り返しても結果が変わらない。

    防御 hook (check_bash.py) はどの段階でも PreToolUse の Bash に居ること。
    """

    def install_herdr(settings: dict) -> dict:
        hooks = settings.setdefault("hooks", {})
        entries = hooks.setdefault("SessionStart", [])
        if HERDR_ENTRY not in entries:
            entries.append(json.loads(json.dumps(HERDR_ENTRY)))
        return settings

    def has_check_bash(settings: dict) -> bool:
        return any(
            entry.get("matcher") == "Bash"
            and any(cmd["command"].endswith('/check_bash.py"') for cmd in entry["hooks"])
            for entry in settings["hooks"]["PreToolUse"]
        )

    first = gen.merge_claude_settings({}, COMMON)
    assert has_check_bash(first)
    installed = install_herdr(json.loads(json.dumps(first)))
    second = gen.merge_claude_settings(installed, COMMON)
    assert has_check_bash(second)
    assert second == installed
    third = gen.merge_claude_settings(install_herdr(json.loads(json.dumps(second))), COMMON)
    assert third == second


def test_unknown_script_in_the_shared_directory_is_preserved():
    command = f"python3 {MANAGED_DIR}/someone-elses-hook.py"
    assert not hk.is_managed_hook_command(command, SCRIPTS)


@pytest.mark.parametrize(
    "command",
    [
        f"python3 {MANAGED_DIR}/check_bash.py.bak",
        f"python3 {MANAGED_DIR}/xcheck_bash.py",
        f"python3 {MANAGED_DIR}/check_bash.pyc",
    ],
)
def test_similar_names_are_not_mistaken_for_managed(command):
    assert not hk.is_managed_hook_command(command, SCRIPTS)


@pytest.mark.parametrize(
    "command",
    [
        'python3 "C:\\Users\\o\'neil\\.claude\\hooks\\check_bash.py"',
        "py -3 -B -X utf8 'C:\\Users\\o''neil\\.claude\\hooks\\check_bash.py'",
        "bash $HOME/.claude/hooks/markdownlint.sh --fix",
        f"python3 {MANAGED_DIR}/checkpoint_restore_pending.py",
    ],
)
def test_managed_forms_are_detected(command):
    assert hk.is_managed_hook_command(command, SCRIPTS)


def test_retired_scripts_are_not_current_hooks():
    """撤去済みの一覧に現役の hook が混ざると、管理の意図が読めなくなる。"""
    current = {hook["script"] for hook in COMMON["hooks"]}
    retired = set(COMMON["retired_hooks"]["scripts"])
    assert retired
    assert not current & retired


def test_is_managed_hook_command_detects_both_path_forms():
    assert hk.is_managed_hook_command(f"python3 {MANAGED_DIR}/check_bash.py", SCRIPTS)
    assert hk.is_managed_hook_command("python3 $HOME/.claude/hooks/check_bash.py", SCRIPTS)
    assert not hk.is_managed_hook_command(FOREIGN_COMMAND, SCRIPTS)
    assert not hk.is_managed_hook_command(None, SCRIPTS)


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
    # ★ここで使うイベントは、common.toml で登録していないものを選ぶ。
    #   登録済みのイベントを使うと、生成された hook が混ざって意図が崩れる。
    existing = {
        "hooks": {
            "Notification": [foreign_entry()],
            "PermissionRequest": [foreign_entry("*")],
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    for event in ("Notification", "PermissionRequest"):
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
    kept = hk.strip_managed_claude_hooks([mixed], SCRIPTS)
    assert len(kept) == 1
    assert [c["command"] for c in kept[0]["hooks"]] == [FOREIGN_COMMAND]
    # 元のエントリを破壊しない
    assert len(mixed["hooks"]) == 2


def test_event_becoming_empty_is_dropped():
    # 管理 hook しか無いイベントは消える。同じ入力で外部 hook が同居する
    # イベントは残るので、「そもそも生成しない」のとは区別できる。
    # ★common.toml で登録していないイベントを使う (登録済みだと生成分が残る)。
    managed_only = {
        "hooks": [{"type": "command", "command": f"python3 {MANAGED_DIR}/update-adr-on-stop.py"}]
    }
    existing = {
        "hooks": {
            "Notification": [managed_only],
            "SessionEnd": [managed_only, foreign_entry()],
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    assert "Notification" not in merged["hooks"]
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
    assert gen.merge_claude_settings({}, COMMON)["hooks"] == hk.build_claude_hooks(COMMON)


def test_unparseable_shapes_are_preserved_not_dropped():
    # 解釈できない形は将来のスキーマ変更や未知のツールの可能性があるので残す。
    # ただし chezmoi も生成するイベントで list 以外だった場合は結合できないので
    # 生成物を優先する (Claude のスキーマ上 list 以外は元々無効)。
    # ★温存側には common.toml で登録していないイベントを使う。
    existing = {
        "hooks": {
            "WeirdEvent": {"command": "inline"},
            "Notification": [{"matcher": "*", "command": "orca-inline"}],
            "PreToolUse": "not-a-list",
        }
    }
    merged = gen.merge_claude_settings(existing, COMMON)
    assert merged["hooks"]["WeirdEvent"] == {"command": "inline"}
    assert merged["hooks"]["Notification"] == [{"matcher": "*", "command": "orca-inline"}]
    assert merged["hooks"]["PreToolUse"] == hk.build_claude_hooks(COMMON)["PreToolUse"]


# ---------------------------------------------------------------------------
# Copilot 出力
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ホームに空白やアポストロフィがあっても 1 引数に収まること
# ---------------------------------------------------------------------------

# 空白と ' はどちらも Windows のファイル名として合法。
WEIRD_HOME = r"C:\Users\O'Brien First Last"
WEIRD_HOOK = {"script": "check_bash.py", "runner": "python3"}


@pytest.fixture
def weird_home(monkeypatch):
    monkeypatch.setattr(hk, "expand_user", lambda p: p.replace("~", WEIRD_HOME, 1))
    return f"{WEIRD_HOME}/.claude/hooks/check_bash.py"


def powershell_single_quoted_arg(command: str) -> str:
    """PowerShell の単一引用符で囲まれた末尾の引数を取り出す。"""
    assert command.endswith("'"), command
    return command[command.index("'") + 1 : -1].replace("''", "'")


def test_claude_windows_hook_path_is_one_argument(weird_home):
    # Claude Code は Windows でも hook コマンドを shell (Git Bash) に渡す。
    command = hk.hook_command(WEIRD_HOOK, launcher="claude", platform="nt")
    assert "$HOME" not in command
    assert shlex.split(command) == ["py", "-3", "-B", "-X", "utf8", weird_home]


def test_copilot_powershell_hook_path_is_one_argument(weird_home):
    command = hk.hook_command(WEIRD_HOOK, launcher="powershell", platform="nt")
    assert "$HOME" not in command
    assert command.startswith("py -3 -B -X utf8 ")
    # ' は '' へ二重化され、PowerShell 側で元のパスへ戻る
    assert "''Brien" in command
    assert powershell_single_quoted_arg(command) == weird_home


def test_claude_unix_hook_path_is_one_argument(weird_home):
    command = hk.hook_command(WEIRD_HOOK, launcher="claude", platform="posix")
    assert shlex.split(command) == ["python3", weird_home]


def test_copilot_unix_hook_keeps_home_variable(weird_home):
    # bash フィールドは Unix 専用。ホームを埋め込まず $HOME を参照させる。
    command = hk.hook_command(WEIRD_HOOK, launcher="bash", platform="posix")
    assert command == 'python3 "$HOME/.claude/hooks/check_bash.py"'


def test_managed_hook_detection_survives_quoting(weird_home):
    for launcher, platform in [
        ("claude", "nt"),
        ("claude", "posix"),
        ("powershell", "nt"),
        ("bash", "posix"),
    ]:
        command = hk.hook_command(WEIRD_HOOK, launcher=launcher, platform=platform)
        assert hk.is_managed_hook_command(command, SCRIPTS), command


def test_copilot_settings_disable_co_author_trailer():
    merged = gen.merge_copilot_settings({"includeCoAuthoredBy": True}, COMMON)

    assert merged["includeCoAuthoredBy"] is False


# ---------------------------------------------------------------------------
# 両 CLI の整合性
# ---------------------------------------------------------------------------

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
    # MCP は宣言しない。deepwiki を外した時点で管理対象が 0 件になった。
    assert "mcpServers" not in gen.GEMINI_MANAGED


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


def test_windows_python_hooks_use_latest_python_3():
    claude = hk.build_claude_hooks(COMMON, platform="nt")
    commands = [
        cmd["command"] for entries in claude.values() for entry in entries for cmd in entry["hooks"]
    ]
    python_commands = [c for c in commands if c.rstrip("\"'").endswith(".py")]
    assert python_commands
    assert all(c.startswith("py -3 -B -X utf8 ") for c in python_commands)
