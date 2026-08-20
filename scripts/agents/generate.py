#!/usr/bin/env python3
"""Generate per-CLI permission settings from a single common.toml.

Usage:
    generate.py --target claude-settings --common PATH [--existing PATH]
    generate.py --target copilot-perms --common PATH [--existing PATH]
    generate.py --target copilot-settings --common PATH [--existing PATH]
    generate.py --target copilot-hooks --common PATH

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
    out["permissions"] = build_claude_permissions(common)
    out["hooks"] = build_claude_hooks(common)
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
# Copilot settings target (一部キーのみ置換し、他は温存)
# ---------------------------------------------------------------------------

# generate.py が管理するキー一覧 (これら以外は触らない)
COPILOT_MANAGED_KEYS = {"allowedUrls", "deniedUrls", "trustedFolders"}


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

    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

TARGETS = {
    "claude-settings": merge_claude_settings,
    "copilot-hooks": merge_copilot_hooks,
    "copilot-perms": merge_copilot_perms,
    "copilot-settings": merge_copilot_settings,
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
