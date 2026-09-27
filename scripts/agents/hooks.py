"""Hooks (Claude / Copilot 共通の単一ソース -> 各 CLI の設定形式へ)。

common.toml の ``[[hooks]]`` から各 CLI の登録を組み立て、既存設定に同居する
外部ツールの hook を温存しながら自分の生成物だけを差し替える。
generate.py から import される (逆向きの依存は持たない)。
"""

from __future__ import annotations

import os
import re
from typing import Any


def expand_user(path: str) -> str:
    return os.path.expanduser(path)


# hook スクリプトの配置先。Claude / Copilot とも同じ実体を共有する。
HOOKS_DIR = "~/.claude/hooks"
# ホーム表記に依存せず「このディレクトリを起動しているか」を判定するための部分。
HOOKS_DIR_TAIL = HOOKS_DIR.removeprefix("~") + "/"


def quote_powershell(value: str) -> str:
    """PowerShell の単一引用符で囲む (リテラル扱い、`'` は `''` へ二重化)。

    Copilot が `powershell` フィールドを `-Command` へ渡す場合、二重引用符は
    外側の引用と衝突して失われうる。単一引用符なら中身は展開も再解釈もされない。
    """
    return "'" + value.replace("'", "''") + "'"


def hook_command(
    hook: dict[str, Any],
    *,
    launcher: str,
    platform: str | None = None,
) -> str:
    """hook の起動コマンド文字列を組み立てる。

    launcher は生成先フィールドを解釈する側。パス表記と引用符が変わる。

    | launcher     | 生成先                          | パス   | 引用            |
    | ------------ | ------------------------------- | ------ | --------------- |
    | "claude"     | settings.json の hooks[].command | 絶対   | `"..."`         |
    | "bash"       | from-claude.json の bash (Unix) | $HOME  | `"..."`         |
    | "powershell" | from-claude.json の powershell  | 絶対   | `'...'`         |

    Windows で `$HOME` を使わないのは、PowerShell の `$HOME` が
    `HOMEDRIVE`+`HOMEPATH` 由来で chezmoi の `~` (`%USERPROFILE%`) と
    一致しないことがあるため (docs/spec/structure.md)。生成は対象マシン上で
    走るので `expand_user()` は chezmoi と同じホームを返す。
    """
    runner = hook.get("runner", "python")
    if runner == "python3" and (platform or os.name) == "nt":
        # -B: __pycache__ を作らない / -X utf8: 既定コードページだと日本語 JSON が壊れる
        runner = "py -3 -B -X utf8"
    # bash フィールドは Unix 専用。ホームを埋め込まず $HOME を参照させる。
    base = HOOKS_DIR.replace("~", "$HOME", 1) if launcher == "bash" else expand_user(HOOKS_DIR)
    path = f"{base}/{hook['script']}"
    quoted = quote_powershell(path) if launcher == "powershell" else f'"{path}"'
    return f"{runner} {quoted}"


def managed_hook_scripts(common: dict[str, Any]) -> frozenset[str]:
    """このリポジトリが HOOKS_DIR に配る hook のスクリプト名 (現役 + 撤去済み)。

    see docs/spec/agent-permissions.md#外部ツールとの共存-orca--herdr
    """
    current = {hook["script"] for hook in common.get("hooks", []) if "script" in hook}
    retired = common.get("retired_hooks", {}).get("scripts", [])
    return frozenset(current | set(retired))


def is_managed_hook_command(command: Any, scripts: frozenset[str]) -> bool:
    """コマンド文字列が本リポジトリの hook (``scripts`` のどれか) を起動しているか。

    ホーム部分の表記 (絶対パス / `$HOME` / `~`) と引用符の有無は問わない。
    絶対パスで比較すると PowerShell の `''` エスケープや別表記のホームを
    取りこぼし、消し損ねた hook が二重登録される。
    スクリプト名の直後は引用符・空白・末尾のいずれかに限る
    (`check_bash.py.bak` などを自分の hook と誤認しない)。
    """
    if not isinstance(command, str) or not scripts:
        return False
    names = "|".join(re.escape(name) for name in sorted(scripts))
    pattern = re.escape(HOOKS_DIR_TAIL) + f"(?:{names})" + r"(?=$|[\s\"'])"
    return re.search(pattern, command.replace("\\", "/")) is not None


def strip_managed_claude_hooks(entries: Any, scripts: frozenset[str]) -> Any:
    """1 イベント分の hook エントリ列から、管理対象のコマンドだけを取り除く。

    削除するのは「全コマンドが自分の生成物だと確認できたエントリ」だけ。
    解釈できない形 (list でない、"hooks" リストを持たない等) は将来のスキーマ
    変更や未知のツールの書き込みでありうるのでそのまま残す。この関数の目的は
    データを失わないことなので、判断できないものは触らない。
    """
    if not isinstance(entries, list):
        return entries
    kept: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            kept.append(entry)
            continue
        foreign = [
            command
            for command in entry["hooks"]
            if not (
                isinstance(command, dict)
                and is_managed_hook_command(command.get("command"), scripts)
            )
        ]
        if not foreign:
            # 自分の生成物しか無いエントリ。common.toml から作り直す
            continue
        new_entry = dict(entry)
        new_entry["hooks"] = foreign
        kept.append(new_entry)
    return kept


def merge_claude_hooks(
    existing: Any, common: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """common.toml 由来の hook を再生成しつつ、外部ツールの hook を温存する。

    出力順は「common.toml のイベント -> 既存にしか無いイベント」、各イベント内は
    「再生成した管理エントリ -> 温存した外部エントリ」。既存ファイルの並びと
    一致するため差分が最小になり、2 回適用しても結果が変わらない (冪等)。
    """
    managed = build_claude_hooks(common)
    scripts = managed_hook_scripts(common)
    preserved: dict[str, Any] = {}
    if isinstance(existing, dict):
        for event, entries in existing.items():
            kept = strip_managed_claude_hooks(entries, scripts)
            if isinstance(kept, list) and not kept:
                # 自分の生成物しか無かったイベント。生成側で作り直す
                continue
            preserved[event] = kept

    out: dict[str, list[dict[str, Any]]] = {}
    for event, entries in managed.items():
        extra = preserved.get(event)
        # 管理イベントは list 前提。Claude のスキーマ上 list 以外は元々無効なので、
        # 結合できない値は生成物を優先する。
        out[event] = list(entries) + (extra if isinstance(extra, list) else [])
    for event, entries in preserved.items():
        if event not in out:
            out[event] = entries
    return out


def build_claude_hooks(
    common: dict[str, Any],
    *,
    platform: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Claude Code の settings.json 用 hooks (ネスト構造) を組み立てる。

    - matcher を省略すると「全マッチ」扱い (公式仕様)
    - timeout は秒。省略時の command hook のデフォルトは 600 秒と長いため、
      common.toml の timeout_sec を明示的に出力する
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for hook in common.get("hooks", []):
        event = hook.get("claude_event")
        if not event:
            continue
        entry: dict[str, Any] = {}
        matcher = hook.get("claude_matcher")
        if matcher:
            entry["matcher"] = matcher
        command: dict[str, Any] = {
            "type": "command",
            "command": hook_command(
                hook,
                launcher="claude",
                platform=platform,
            ),
        }
        timeout = hook.get("timeout_sec")
        if timeout:
            command["timeout"] = timeout
        entry["hooks"] = [command]
        out.setdefault(event, []).append(entry)
    return out


def build_copilot_hooks(
    common: dict[str, Any],
    *,
    platform: str | None = None,
) -> dict[str, Any]:
    """Copilot CLI の ~/.copilot/hooks/*.json 用 hooks (フラット構造) を組み立てる。"""
    hooks: dict[str, list[dict[str, Any]]] = {}
    command_key = "powershell" if (platform or os.name) == "nt" else "bash"
    for hook in common.get("hooks", []):
        event = hook.get("copilot_event")
        if not event:
            continue
        entry: dict[str, Any] = {}
        matcher = hook.get("copilot_matcher")
        if matcher:
            entry["matcher"] = matcher
        entry["type"] = "command"
        entry[command_key] = hook_command(
            hook,
            launcher=command_key,
            platform=platform,
        )
        timeout = hook.get("timeout_sec")
        if timeout:
            entry["timeoutSec"] = timeout
        hooks.setdefault(event, []).append(entry)
    return {"version": 1, "hooks": hooks}


def merge_copilot_hooks(_existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    # hooks ファイルは完全な生成物なので既存内容は参照しない
    return build_copilot_hooks(common)
