#!/usr/bin/env python3
"""Generate per-CLI permission settings from a single common.toml.

Usage:
    generate.py --target claude-settings --common PATH [--existing PATH]
    generate.py --target copilot-perms --common PATH [--existing PATH]
    generate.py --target copilot-settings --common PATH [--existing PATH]
    generate.py --target copilot-hooks --common PATH
    generate.py --target gemini-settings --common PATH [--existing PATH]

If --existing is omitted, stdin is read. The merged JSON is printed to stdout.
For Copilot, automatically-managed keys (copilotTokens, loggedInUsers, etc.) in
the existing settings.json are preserved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand_user(path: str) -> str:
    return os.path.expanduser(path)


def first_token(pattern: str) -> str:
    """Extract the first command name from a bash pattern.

    "git diff"     -> "git"
    "uv sync"      -> "uv"
    "cmake -S"     -> "cmake"
    "wc"           -> "wc"
    """
    head = pattern.split(":", 1)[0]
    return head.split()[0] if head else ""


# ---------------------------------------------------------------------------
# Hooks (Claude / Copilot 共通の単一ソース -> 各 CLI の設定形式へ)
# ---------------------------------------------------------------------------

# hook スクリプトの配置先。Claude / Copilot とも同じ実体を共有する。
HOOKS_DIR = "~/.claude/hooks"


def hook_command(hook: dict[str, Any], *, expand_home: bool) -> str:
    """hook の起動コマンド文字列を組み立てる。

    expand_home=True  -> "/home/user/.claude/hooks/x.py" (Claude 用の絶対パス)
    expand_home=False -> "$HOME/.claude/hooks/x.py"      (Copilot 用)
    """
    runner = hook.get("runner", "python")
    script = hook["script"]
    base = expand_user(HOOKS_DIR) if expand_home else HOOKS_DIR.replace("~", "$HOME", 1)
    return f"{runner} {base}/{script}"


def is_managed_hook_command(command: Any) -> bool:
    """コマンド文字列が本リポジトリの生成した hook かどうかを判定する。

    settings.json の hooks は Orca などの外部ツールも追記する共有領域なので、
    「HOOKS_DIR 配下のスクリプトを起動しているか」で自分の生成物だけを識別する。
    hook_command() は絶対パス表記と $HOME 表記の両方を出しうるので双方を見る。
    """
    if not isinstance(command, str):
        return False
    prefixes = (
        expand_user(HOOKS_DIR) + "/",
        HOOKS_DIR.replace("~", "$HOME", 1) + "/",
    )
    return any(prefix in command for prefix in prefixes)


def strip_managed_claude_hooks(entries: Any) -> Any:
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
                and is_managed_hook_command(command.get("command"))
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
    preserved: dict[str, Any] = {}
    if isinstance(existing, dict):
        for event, entries in existing.items():
            kept = strip_managed_claude_hooks(entries)
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


def build_claude_hooks(common: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
            "command": hook_command(hook, expand_home=True),
        }
        timeout = hook.get("timeout_sec")
        if timeout:
            command["timeout"] = timeout
        entry["hooks"] = [command]
        out.setdefault(event, []).append(entry)
    return out


def build_copilot_hooks(common: dict[str, Any]) -> dict[str, Any]:
    """Copilot CLI の ~/.copilot/hooks/*.json 用 hooks (フラット構造) を組み立てる。"""
    hooks: dict[str, list[dict[str, Any]]] = {}
    for hook in common.get("hooks", []):
        event = hook.get("copilot_event")
        if not event:
            continue
        entry: dict[str, Any] = {}
        matcher = hook.get("copilot_matcher")
        if matcher:
            entry["matcher"] = matcher
        entry["type"] = "command"
        entry["bash"] = hook_command(hook, expand_home=False)
        timeout = hook.get("timeout_sec")
        if timeout:
            entry["timeoutSec"] = timeout
        hooks.setdefault(event, []).append(entry)
    return {"version": 1, "hooks": hooks}


def merge_copilot_hooks(_existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    # hooks ファイルは完全な生成物なので既存内容は参照しない
    return build_copilot_hooks(common)


# ---------------------------------------------------------------------------
# Claude target
# ---------------------------------------------------------------------------

def build_claude_permissions(common: dict[str, Any]) -> dict[str, list[str]]:
    # bash.allow / ask / deny は素のトークン列 (例: "git push") で書かれているので
    # Claude の pattern 記法 Bash(git push:*) に展開する。
    # 同じリストを hook (check_bash.py) も読むため、ルールは 1 箇所に書けばよい。
    #
    # 書き込み系の permission rule は Edit(path) に統一する。
    # Claude Code v2.1.210 で Write(path) / NotebookEdit(path) / Glob(path) は
    # deprecated となり、起動時警告が出るようになった (代替は Edit(path) / Read(path))。
    # ref: anthropics/claude-code CHANGELOG.md v2.1.210
    bash = common.get("bash", {})
    file_ = common.get("file", {})
    web = common.get("web", {})
    claude = common.get("claude", {})

    allow: list[str] = []
    for cmd in bash.get("allow", []):
        allow.append(f"Bash({cmd}:*)")
    for path in file_.get("read_allow", []):
        allow.append(f"Read({path})")
    for domain in web.get("allow_domains", []):
        allow.append(f"WebFetch(domain:{domain})")

    deny: list[str] = []
    for cmd in bash.get("deny", []):
        deny.append(f"Bash({cmd}:*)")
    for glob in file_.get("read_deny_globs", []):
        deny.append(f"Read({glob})")
    for glob in file_.get("write_deny_globs", []):
        deny.append(f"Edit({glob})")
    for mcp in claude.get("mcp_deny", []):
        deny.append(mcp)

    ask: list[str] = []
    for cmd in bash.get("ask", []):
        ask.append(f"Bash({cmd}:*)")
    for glob in file_.get("read_ask_globs", []):
        ask.append(f"Read({glob})")
    for glob in file_.get("write_ask_globs", []):
        ask.append(f"Edit({glob})")

    # 順序を安定化 (重複除去しつつ元順序を保持)
    def uniq(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"allow": uniq(allow), "ask": uniq(ask), "deny": uniq(deny)}


def merge_claude_settings(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    permissions = build_claude_permissions(common)
    # 新規セッションの権限モード。ask / deny と hook はどのモードでも効くので、
    # auto を既定にしても防御は残る。
    mode = common.get("claude", {}).get("default_permission_mode")
    if mode:
        permissions["defaultMode"] = mode
    out["permissions"] = permissions
    # permissions と違い hooks は Orca などの外部ツールも追記する共有領域なので、
    # 自分が生成したエントリだけを差し替える。
    out["hooks"] = merge_claude_hooks(existing.get("hooks"), common)
    return out


# ---------------------------------------------------------------------------
# Copilot perms target
# ---------------------------------------------------------------------------

def build_copilot_locations(common: dict[str, Any]) -> dict[str, Any]:
    bash = common.get("bash", {})
    copilot = common.get("copilot", {})

    # bash.allow から first token を抽出して unique 化
    cmd_names: list[str] = []
    seen: set[str] = set()
    for p in bash.get("allow", []):
        t = first_token(p)
        if t and t not in seen:
            seen.add(t)
            cmd_names.append(t)

    locations: dict[str, dict[str, Any]] = {}
    for loc in copilot.get("locations", []):
        path = expand_user(loc["path"])
        approvals = []
        # 共通 commands を先頭に追加
        if cmd_names:
            approvals.append({"kind": "commands", "commandIdentifiers": cmd_names})
        # toml で書かれた approvals を後続に追加
        for ap in loc.get("approvals", []):
            entry = {"kind": ap["kind"]}
            if "commands" in ap:
                entry["commandIdentifiers"] = ap["commands"]
            approvals.append(entry)
        locations[path] = {"tool_approvals": approvals}

    return {"locations": locations}


def merge_copilot_perms(_existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    # permissions-config.json は自動管理キーが無いので全置換で問題ない
    return build_copilot_locations(common)


# ---------------------------------------------------------------------------
# Gemini settings target (管理する枝だけ上書きし、他は温存)
# ---------------------------------------------------------------------------

# generate.py が管理する枝。ここに書いた葉だけを上書きし、それ以外
# (Orca が書き込む hooks など) は既存の値と順序をそのまま残す。
GEMINI_MANAGED: dict[str, Any] = {
    "general": {
        "sessionRetention": {
            "enabled": True,
            "maxAge": "30d",
            "warningAcknowledged": True,
        },
    },
    "security": {
        "auth": {
            "selectedType": "oauth-personal",
        },
    },
    "experimental": {
        "skills": {
            "enabled": True,
        },
        "enableAgents": True,
    },
    "mcpServers": {
        "deepwiki": {
            "httpUrl": "https://mcp.deepwiki.com/mcp",
        },
    },
}


def deep_merge_managed(existing: Any, managed: dict[str, Any]) -> dict[str, Any]:
    """existing のキー順を保ったまま managed の枝だけを再帰的に上書きする。"""
    out = dict(existing) if isinstance(existing, dict) else {}
    for key, value in managed.items():
        if isinstance(value, dict):
            out[key] = deep_merge_managed(out.get(key), value)
        else:
            out[key] = value
    return out


def merge_gemini_settings(existing: dict[str, Any], _common: dict[str, Any]) -> dict[str, Any]:
    # Sprig の toPrettyJson は map のキーをアルファベット順に並べ替えるため、
    # テンプレートで書き戻すと Gemini / Orca が書いた順序と毎回衝突して差分
    # ノイズになっていた。Python の dict は挿入順を保つのでこれを避けられる。
    return deep_merge_managed(existing, GEMINI_MANAGED)


# ---------------------------------------------------------------------------
# Copilot settings target (一部キーのみ置換し、他は温存)
# ---------------------------------------------------------------------------

# generate.py が管理するキー一覧 (これら以外は触らない)
COPILOT_MANAGED_KEYS = {
    "allowedUrls",
    "deniedUrls",
    "includeCoAuthoredBy",
    "trustedFolders",
}


def merge_copilot_settings(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    web = common.get("web", {})
    copilot = common.get("copilot", {})

    out = dict(existing)
    out["allowedUrls"] = list(web.get("allow_domains", []))
    deny = list(web.get("deny_domains", []))
    if deny:
        out["deniedUrls"] = deny
    elif "deniedUrls" in out:
        # common で空なら削除
        out.pop("deniedUrls", None)

    out["trustedFolders"] = [expand_user(p) for p in copilot.get("trusted_folders", [])]

    if "include_co_authored_by" in copilot:
        out["includeCoAuthoredBy"] = bool(copilot["include_co_authored_by"])

    # 新規対話セッションの権限モード。assisted は experimental な
    # auto-approval 機能に依存するため、両方をここで揃える。
    mode = copilot.get("default_permission_mode")
    if mode:
        out["defaultPermissionMode"] = mode
    if "experimental" in copilot:
        out["experimental"] = bool(copilot["experimental"])

    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

TARGETS = {
    "claude-settings": merge_claude_settings,
    "copilot-hooks": merge_copilot_hooks,
    "copilot-perms": merge_copilot_perms,
    "copilot-settings": merge_copilot_settings,
    "gemini-settings": merge_gemini_settings,
}


def load_existing(path: str | None) -> dict[str, Any]:
    if path is None or path == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
    raw = raw.strip()
    if not raw:
        return {}
    return json.loads(raw)


def load_common(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("--common", required=True, help="path to common.toml")
    parser.add_argument(
        "--existing",
        default=None,
        help="path to existing JSON (defaults to stdin)",
    )
    args = parser.parse_args(argv)

    common = load_common(args.common)
    existing = load_existing(args.existing)
    merger = TARGETS[args.target]
    merged = merger(existing, common)

    json.dump(merged, sys.stdout, indent=2, ensure_ascii=False, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
