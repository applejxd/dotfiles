#!/usr/bin/env python3
"""Generate per-CLI permission settings from a single common.toml.

Usage:
    generate.py --target claude-settings --common PATH [--existing PATH]
    generate.py --target copilot-perms --common PATH [--existing PATH]
    generate.py --target copilot-settings --common PATH [--existing PATH]
    generate.py --target copilot-mcp --common PATH [--existing PATH]
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
import platform
import sys
import tomllib
from pathlib import Path
from typing import Any

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


def hook_command(
    hook: dict[str, Any],
    *,
    expand_home: bool,
    platform: str | None = None,
) -> str:
    """hook の起動コマンド文字列を組み立てる。

    expand_home=True  -> "/home/user/.claude/hooks/x.py" (Claude 用の絶対パス)
    expand_home=False -> '"$HOME/.claude/hooks/x.py"'    (Copilot 用、空白を保護)
    """
    runner = hook.get("runner", "python")
    if runner == "python3" and (platform or os.name) == "nt":
        runner = "py -3 -B"
        if not expand_home:
            # Windows の既定コードページでは hook の日本語 JSON が壊れる。
            runner += " -X utf8"
    script = hook["script"]
    base = expand_user(HOOKS_DIR) if expand_home else HOOKS_DIR.replace("~", "$HOME", 1)
    path = f"{base}/{script}"
    if not expand_home:
        path = f'"{path}"'
    return f"{runner} {path}"


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
                expand_home=True,
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
            expand_home=False,
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
    for path in file_.get("claude_read_allow", []):
        allow.append(f"Read({path})")
    for domain in web.get("allow_domains", []):
        allow.append(f"WebFetch(domain:{domain})")

    deny: list[str] = []
    for cmd in bash.get("deny", []):
        deny.append(f"Bash({cmd}:*)")
    for glob in file_.get("claude_read_deny_globs", []):
        deny.append(f"Read({glob})")
    for glob in file_.get("claude_write_deny_globs", []):
        deny.append(f"Edit({glob})")
    for mcp in claude.get("mcp_deny", []):
        deny.append(mcp)

    ask: list[str] = []
    # ask_hook_owned のコマンドは check_bash.py が承認要否まで判定するので、
    # 静的な ask ルールにはしない。Claude の explicit ask はどのモードでも
    # 自動承認されず、hook の allow でも上書きできない (v2.1.77 以降) ため、
    # 静的 ask を出すと hook 側の exemption が無効化される。
    hook_owned = set(bash.get("ask_hook_owned", []))
    for cmd in bash.get("ask", []):
        if cmd in hook_owned:
            continue
        ask.append(f"Bash({cmd}:*)")
    for glob in file_.get("claude_read_ask_globs", []):
        ask.append(f"Read({glob})")
    for glob in file_.get("claude_write_ask_globs", []):
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


def _uniq(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _expand_sandbox_paths(paths: list[str]) -> list[str]:
    """``~`` を展開し、Copilot が扱えないワイルドカード入りを落とす。"""
    return [
        expand_user(path)
        for path in paths
        if "*" not in path and "?" not in path
    ]


# ``[sandbox]`` で使えるキー。命名は **共有 = 無印 / CLI 固有 = CLI 名の接頭辞**
# で統一する ([[hooks]] の claude_event / copilot_event と同じ規則)。
SHARED_SANDBOX_KEYS = frozenset({"deny", "seccomp_apply_path"})
CLAUDE_SANDBOX_KEYS = frozenset({
    "claude_read_allow",
    "claude_write_allow",
    "claude_write_deny",
    "claude_network_allow",
    "claude_network_strict",
})
COPILOT_SANDBOX_KEYS = frozenset({
    "copilot_read_allow",
    "copilot_write_allow",
    "copilot_allow_dev_tool_access",
})
KNOWN_SANDBOX_KEYS = SHARED_SANDBOX_KEYS | CLAUDE_SANDBOX_KEYS | COPILOT_SANDBOX_KEYS

# ``[file]`` は 5 キーすべて Claude 専用。Copilot の permissions-config.json は
# bash の allow と locations しか表現できず、ファイル規則を持てないため。
# Copilot 側の等価な保護は ``[sandbox] deny`` (OS レベル) と check_file_read.py。
KNOWN_FILE_KEYS = frozenset({
    "claude_read_allow",
    "claude_read_ask_globs",
    "claude_write_ask_globs",
    "claude_read_deny_globs",
    "claude_write_deny_globs",
})


def _reject_unknown(section: str, present: set[str], known: frozenset[str]) -> None:
    unknown = sorted(present - known)
    if unknown:
        raise ValueError(
            f"[{section}] に未知のキーがあります: "
            + ", ".join(unknown)
            + "\n綴り間違いか旧名の可能性があります。"
            " そのままでは設定が無視され、許可したつもりの規則が効きません。"
            "\n使えるキー: " + ", ".join(sorted(known))
        )


def validate_sandbox_keys(common: dict[str, Any]) -> None:
    """``[sandbox]`` / ``[file]`` に未知のキーが無いか検査する (fail-closed)。

    キーを読み違えても ``.get(key, [])`` は静かに空リストを返すため、
    綴り間違いや旧名の残りは **防御が黙って消える** 形で現れる。
    """
    _reject_unknown("sandbox", set(common.get("sandbox", {})), KNOWN_SANDBOX_KEYS)
    _reject_unknown("file", set(common.get("file", {})), KNOWN_FILE_KEYS)


def seccomp_arch(machine: str | None = None) -> str | None:
    """``uname -m`` 相当の値を sandbox-runtime の vendor ディレクトリ名へ変換。

    サポート外のアーキテクチャでは None を返し、呼び出し側は設定を出さない。
    """
    value = (machine or platform.machine()).lower()
    if value in {"x86_64", "amd64", "x64"}:
        return "x64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return None


def build_seccomp_config(
    common: dict[str, Any], *, machine: str | None = None
) -> dict[str, Any] | None:
    """``sandbox.seccomp`` を組み立てる (見つからなければ None)。

    Claude は apply-seccomp を npm のグローバル領域でしか自動検出しないが、
    このリポジトリでは mise で導入する (``npm install -g`` は [bash] deny)。
    mise は独自ディレクトリへ隔離するので自動検出に頼れないため、公式が
    用意している ``sandbox.seccomp.applyPath`` でパスを直接指す。

    存在しないパスを設定すると sandbox の起動が壊れかねないので、
    **実在するときだけ** 出力する。未導入のマシンや非対応アーキテクチャでは
    単に設定が出ず、Claude は従来どおり自動検出にフォールバックする。
    """
    template = common.get("sandbox", {}).get("seccomp_apply_path")
    if not template:
        return None
    arch = seccomp_arch(machine)
    if arch is None:
        return None
    path = Path(expand_user(template.replace("{arch}", arch)))
    if not path.is_file():
        return None
    return {"applyPath": str(path)}


def build_claude_sandbox(common: dict[str, Any]) -> dict[str, Any]:
    """Claude の sandbox.filesystem を whitelist (deny-by-default) で組み立てる。

    Claude の既定は「read 全許可 + deny を引く」ブラックリストだが、
    ``denyRead`` に ``~/`` を置いて ``allowRead`` で穴を開けると
    Copilot と同じ deny-by-default に揃えられる (公式ドキュメントに構成例あり)。

    whitelist にするのは迂回耐性のためだけではない。Claude の Linux sandbox は
    deny 対象の各パスに ``/dev/null`` を bind-mount する実装なので、
    ``~/**/*secret*`` のような広い名前マッチを deny に置くと数千個の
    bind-mount が必要になり実用に耐えない (common.toml のコメント参照)。
    ``~/`` 1 本なら展開されない。

    書き込み側は Claude も元から whitelist (cwd + セッション temp + 明示許可)
    なので、``allowWrite`` に追加分を渡すだけでよい。

    承認モード (auto-allow 等) には触れない: sandbox は既存の承認フローの
    上に追加される OS レベルの防御としてのみ働かせる。

    ネットワークは ``[web] allow_domains`` (WebFetch 用のドキュメントサイト) と
    ``[sandbox] network_allow`` (shell が実際に通信するCDN等) を合算して
    ``sandbox.network.allowedDomains`` に渡す。
    Claude は ``WebFetch(domain:...)`` の許可ルールからも sandbox の
    allowlist を組み立てるため前者は実質二重になるが、permission 側の記法が
    変わっても sandbox の許可が崩れないよう明示しておく。

    ``[sandbox] network_strict`` が真なら ``strictAllowlist`` を立てて
    許可外ドメインを **拒否** する (Claude Code v2.1.219 以降が必要)。
    これを立てないと許可外は拒否ではなく **承認プロンプト** になる。
    Copilot にはドメイン単位の制御が無いため (``allowOutbound`` の on/off
    だけ)、ネットワークだけは両 CLI で揃えられない。
    """
    sandbox = common.get("sandbox", {})
    deny = list(sandbox.get("deny", []))
    write_deny_extra = list(sandbox.get("claude_write_deny", []))
    web = common.get("web", {})

    network: dict[str, Any] = {
        "allowedDomains": _uniq(
            list(web.get("allow_domains", [])) + list(sandbox.get("claude_network_allow", []))
        ),
    }
    denied_domains = _uniq(list(web.get("deny_domains", [])))
    if denied_domains:
        network["deniedDomains"] = denied_domains
    if sandbox.get("claude_network_strict"):
        network["strictAllowlist"] = True

    out: dict[str, Any] = {
        "enabled": True,
        "filesystem": {
            # ホーム全体を塞いでから read_allow で穴を開ける。
            # deny は穴の内側でも効く (より具体的なパスが勝つ)。
            "denyRead": _uniq(["~/", *deny]),
            "allowRead": _uniq(list(sandbox.get("claude_read_allow", []))),
            "denyWrite": _uniq(deny + write_deny_extra),
            "allowWrite": _uniq(list(sandbox.get("claude_write_allow", []))),
        },
        "network": network,
    }
    seccomp = build_seccomp_config(common)
    if seccomp:
        out["seccomp"] = seccomp
    return out


def merge_claude_settings(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    claude = common.get("claude", {})
    if "auto_update" in claude:
        out["env"] = dict(existing.get("env") or {})
        out["env"]["DISABLE_AUTOUPDATER"] = "0" if claude["auto_update"] else "1"
    permissions = build_claude_permissions(common)
    # 新規セッションの権限モード。ask / deny と hook はどのモードでも効くので、
    # auto を既定にしても防御は残る。
    mode = claude.get("default_permission_mode")
    if mode:
        permissions["defaultMode"] = mode
    out["permissions"] = permissions
    # permissions と違い hooks は Orca などの外部ツールも追記する共有領域なので、
    # 自分が生成したエントリだけを差し替える。
    out["hooks"] = merge_claude_hooks(existing.get("hooks"), common)
    out["sandbox"] = build_claude_sandbox(common)
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
        location: dict[str, Any] = {"tool_approvals": approvals}

        # このプロジェクトで作業しているときだけ開く追加ディレクトリ。
        # ★公式仕様: "Each directory must exist when the CLI applies the
        #   configuration" — 存在しないパスは落とす。
        allowed = [expand_user(d) for d in loc.get("allowed_directories", [])]
        existing_dirs = [d for d in allowed if Path(d).is_dir()]
        if existing_dirs:
            location["allowed_directories"] = _uniq(existing_dirs)
        locations[path] = location

    return {"locations": locations}


def merge_copilot_perms(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``permissions-config.json`` を更新する (既存の承認は温存)。

    ★このファイルは **CLI 自身が書き込む**。公式に
      "When you approve a tool or grant access to a directory for the current
      location, the CLI records the decision here" とある。
      全置換すると **`chezmoi apply` のたびに対話承認が消える**ので、
      location 単位で union する。
    """
    generated = build_copilot_locations(common)
    if not isinstance(existing, dict):
        return generated

    current = existing.get("locations")
    if not isinstance(current, dict):
        current = {}

    out: dict[str, Any] = {}
    for path, entry in current.items():
        out[path] = dict(entry) if isinstance(entry, dict) else entry

    for path, entry in generated["locations"].items():
        base = out.get(path)
        if not isinstance(base, dict):
            out[path] = entry
            continue
        merged = dict(base)
        for key in ("tool_approvals", "allowed_directories"):
            incoming = entry.get(key)
            if not incoming:
                continue
            existing_value = base.get(key)
            kept = list(existing_value) if isinstance(existing_value, list) else []
            for item in incoming:
                if item not in kept:
                    kept.append(item)
            merged[key] = kept
        out[path] = merged

    result = dict(existing)
    result["locations"] = out
    return result


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
# MCP サーバ (common.toml の [[mcp]] -> 各 CLI の形式)
# ---------------------------------------------------------------------------

# Claude Code はサーバ名に使える文字を「英数字・ハイフン・アンダースコア」に
# 限っている。Codex 側では id がそのまま TOML のキー (`[mcp_servers.<id>]`) に
# なるため、ここを外れた名前は生成物を壊す。
MCP_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
# transport ごとの必須キー。両方の形のキーを持つ定義は生成先で曖昧になるので、
# ここに無いキーは (typo も含めて) 弾く。
MCP_TRANSPORT_KEYS = {
    "http": {"url"},
    "stdio": {"command", "args"},
}
MCP_COMMON_KEYS = {"id", "purpose", "transport"}


def mcp_servers(common: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``[[mcp]]`` を (名前, 定義) の宣言順リストにして返す。

    ユーザ・OS による出し分けは common.toml 側の chezmoi テンプレートが
    済ませているので、ここには条件が無い (展開後の表だけを見る)。

    設定ミスは黙って無効な MCP 定義を書き出すより、apply を止めた方がよい
    (生成先の 3 つが食い違ったまま気付けなくなる)。
    """
    servers: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for server in common.get("mcp", []):
        name = server.get("id", "")
        if not name or set(name) - MCP_ID_CHARS:
            raise ValueError(
                f"[[mcp]] の id が不正: {name!r} "
                "(英数字・ハイフン・アンダースコアのみ)"
            )
        if name in seen:
            raise ValueError(f"[[mcp]] の id が重複している: {name}")
        seen.add(name)

        transport = server.get("transport")
        if transport not in MCP_TRANSPORT_KEYS:
            raise ValueError(
                f"[[mcp]] {name} の transport が未対応: {transport!r} "
                f"(対応: {', '.join(sorted(MCP_TRANSPORT_KEYS))})"
            )
        unknown = set(server) - MCP_COMMON_KEYS - MCP_TRANSPORT_KEYS[transport]
        if unknown:
            raise ValueError(
                f"[[mcp]] {name} に {transport} では使わないキーがある: "
                + ", ".join(sorted(unknown))
            )

        entry: dict[str, Any] = {"transport": transport}
        if transport == "http":
            url = server.get("url")
            if not url:
                raise ValueError(f"[[mcp]] {name} に url が無い")
            entry["url"] = url
        else:
            command = server.get("command")
            if not command:
                raise ValueError(f"[[mcp]] {name} に command が無い")
            args = server.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError(f"[[mcp]] {name} の args は文字列のリストで書く")
            entry["command"] = command
            entry["args"] = list(args)

        servers.append((name, entry))
    return servers


def merge_copilot_mcp(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``~/.copilot/mcp-config.json`` の ``mcpServers`` を更新する。

    このファイルは CLI 自身も書き込む (`copilot mcp add` / `/mcp`) ので、
    common.toml に書いた名前だけを差し替え、ほかのサーバは残す。
    同じ名前でも ``headers`` / ``env`` / ``tools`` には触れない: 前 2 つは
    トークンを環境変数参照で入れる場所 (ADR-0005)、最後は手元で絞った
    公開範囲で、どれも common.toml が持たない情報だから。
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    servers = dict(out.get("mcpServers") or {})
    for name, server in mcp_servers(common):
        entry = dict(servers.get(name) or {})
        if server["transport"] == "http":
            entry["type"] = "http"
            entry["url"] = server["url"]
            entry.setdefault("headers", {})
            stale = ("command", "args")
        else:
            # Copilot は stdio を "local" と呼ぶ (実測: `copilot mcp add` の出力)
            entry["type"] = "local"
            entry["command"] = server["command"]
            entry["args"] = server["args"]
            stale = ("url", "headers")
        # transport を変えたときに前の形のキーを残さない (両方あると曖昧になる)
        for key in stale:
            entry.pop(key, None)
        entry.setdefault("tools", ["*"])
        servers[name] = entry
    out["mcpServers"] = servers
    return out


# ---------------------------------------------------------------------------
# Copilot settings target (一部キーのみ置換し、他は温存)
# ---------------------------------------------------------------------------

# generate.py が管理するキー一覧 (これら以外は触らない)
COPILOT_MANAGED_KEYS = {
    "allowedUrls",
    "autoUpdate",
    "deniedUrls",
    "includeCoAuthoredBy",
    "trustedFolders",
    # enabledPlugins は丸ごとではなく common.toml に書いたキーだけ
    "enabledPlugins",
    # sandbox は丸ごとではなく enabled と
    # userPolicy.filesystem.deniedPaths のみ (下記 build_copilot_sandbox)
    "sandbox",
}


def build_copilot_sandbox(
    existing_sandbox: Any, common: dict[str, Any]
) -> dict[str, Any]:
    """settings.json の sandbox キーを組み立てる。

    Copilot の sandbox は **deny-by-default のホワイトリスト**。既定の許可は
    cwd (read/write)、``.git``、skill 置き場、システムの ``/usr`` 一部程度で、
    ``$HOME`` 直下は一切含まれない。

    ``allowDevToolAccess`` (PATH・キャッシュの自動 read-only 付与) は
    **無効にしている** (ADR-0008)。そのためツールチェーンへの許可は
    ``copilot_read_allow`` / ``copilot_write_allow`` が全面的に担う。

    Claude 専用キーは渡さない:

    - ``claude_read_allow`` / ``claude_write_allow`` は Copilot 側の
      ``copilot_*`` が同じ役割を担う。ホーム外の扱いと write の範囲が違う
      (Claude は ``denyRead`` が ``~/`` 配下だけなので ``/usr`` は元から読める)。
    - ``claude_write_deny`` (改竄防止) は cwd の外に書けない時点で不要。

    ``deniedPaths`` は共通の ``deny`` から導出して**置き換える**。Copilot は
    **絶対パス限定・ワイルドカード非対応**なので wildcard を含むものは除く。

    ``readwritePaths`` / ``readonlyPaths`` は ``/sandbox config`` の TUI から
    手で足した分を消さないよう **合算**する。
    ``network`` / ``allowBypass`` / ``auth`` などの挙動設定には触れない。
    """
    out: dict[str, Any] = dict(existing_sandbox) if isinstance(existing_sandbox, dict) else {}
    out["enabled"] = True

    sandbox = common.get("sandbox", {})

    # PATH やキャッシュへの自動 read-only 付与。これが有効だと、同じパスへの
    # **ユーザ指定の read-write を自動側の read-only が上書きする**
    # (github/copilot-cli#4846。MXC は同一パスの RO/RW 競合を RO へ解決する)。
    # 明示制御へ倒すため false を渡す。詳細は ADR-0008。
    if "copilot_allow_dev_tool_access" in sandbox:
        out["allowDevToolAccess"] = bool(sandbox["copilot_allow_dev_tool_access"])

    user_policy = dict(out.get("userPolicy") or {})
    filesystem = dict(user_policy.get("filesystem") or {})

    denied = _expand_sandbox_paths(sandbox.get("deny", []))
    filesystem["deniedPaths"] = _uniq(denied)

    # ツールチェーンへの許可。dev-tool 自動付与を切っているので、これが
    # Copilot の $HOME 配下の可視範囲そのものになる。
    # TUI で足した既存エントリを消さないよう合算する
    ro_src = _expand_sandbox_paths(sandbox.get("copilot_read_allow", []))
    rw_src = _expand_sandbox_paths(sandbox.get("copilot_write_allow", []))

    # 同一パスを read と write の両方に書くと、sandbox 実装が競合を
    # 「最も制限的な意図」= read-only へ解決し、write が無言で消える
    # (github/copilot-cli#4846)。write は read を含むので write だけに書く。
    overlap = sorted(set(ro_src) & set(rw_src))
    if overlap:
        raise ValueError(
            "copilot_read_allow と copilot_write_allow に同じパスがある: "
            + ", ".join(overlap)
            + " (read-only に潰されるので write 側にだけ書くこと)"
        )

    for key, extra in (("readonlyPaths", ro_src), ("readwritePaths", rw_src)):
        if not extra and key not in filesystem:
            continue
        current = filesystem.get(key)
        current = list(current) if isinstance(current, list) else []
        filesystem[key] = _uniq(current + extra)

    user_policy["filesystem"] = filesystem
    out["userPolicy"] = user_policy
    return out


def merge_copilot_settings(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    web = common.get("web", {})
    copilot = common.get("copilot", {})

    out = dict(existing)
    if "auto_update" in copilot:
        out["autoUpdate"] = bool(copilot["auto_update"])
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

    out["sandbox"] = build_copilot_sandbox(existing.get("sandbox"), common)

    # enabledPlugins は他の経路 (マーケットプレイスの追加操作など) でも
    # 増えるため、common.toml に書いたキーだけを上書きして残りは温存する。
    enabled_plugins = copilot.get("enabled_plugins")
    if enabled_plugins:
        merged_plugins = dict(existing.get("enabledPlugins") or {})
        merged_plugins.update({k: bool(v) for k, v in enabled_plugins.items()})
        out["enabledPlugins"] = merged_plugins

    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

TARGETS = {
    "claude-settings": merge_claude_settings,
    "copilot-hooks": merge_copilot_hooks,
    "copilot-mcp": merge_copilot_mcp,
    "copilot-perms": merge_copilot_perms,
    "copilot-settings": merge_copilot_settings,
    "gemini-settings": merge_gemini_settings,
}

# 既存内容を一切参照しない (完全生成の) ターゲット。
# 既存ファイルが壊れた JSON でも作り直せるよう、読み込み自体を省く。
# 省かないと、壊れたファイルを直すための apply がパースで失敗して詰む。
FULL_GENERATION_TARGETS = {"copilot-hooks"}


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


# chezmoi 管理外のローカル上書き。存在しなければ無視する。
# このマシンだけで通したいパス (データセット置き場やマウント先など) を、
# 共有の common.toml を汚さずに足すための口。
#   ~/.config/agents/local.toml   (AGENTS_LOCAL_CONFIG で差し替え可)
#
# chezmoi は管理下に無いファイルを消さないので、apply しても残る。
# また ~/.config/agents は [sandbox] write_deny_extra に入っており
# sandbox 内のコマンドからは書けないので、エージェント自身がここに
# 許可を書き足して自分の権限を広げることはできない。
LOCAL_OVERLAY_ENV = "AGENTS_LOCAL_CONFIG"

# ローカル上書きを許すキー。いずれも **追記のみ** で、共有設定の
# エントリを消したり緩めたりはできない (deny を弱める方向には使えない)。
LOCAL_SANDBOX_KEYS = (
    "deny",
    "claude_read_allow",
    "claude_write_allow",
    "claude_write_deny",
    "copilot_read_allow",
    "copilot_write_allow",
)

# local.toml の [[copilot.locations]] で書けるキー。
# Copilot はリポジトリ内の設定ファイルから sandbox / permissions を足せない
# (公式のリポジトリ設定キー一覧に含まれない) ため、プロジェクト単位の許可は
# ここが実質唯一の「共有設定を汚さない置き場」になる。
LOCAL_LOCATION_KEYS = ("path", "approvals", "allowed_directories")


def local_overlay_path() -> Path:
    override = os.environ.get(LOCAL_OVERLAY_ENV)
    if override:
        return Path(override)
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "agents" / "local.toml"


def load_local_overlay(path: Path | None = None) -> dict[str, Any]:
    target = path or local_overlay_path()
    try:
        with target.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # 壊れたローカル設定で apply 全体を落とさない。共有設定だけで続行する。
        print(f"warning: ignoring {target}: {exc}", file=sys.stderr)
        return {}


def _merge_local_sandbox(
    merged: dict[str, Any], local_sandbox: dict[str, Any]
) -> None:
    """local.toml の ``[sandbox]`` を追記する (既存エントリは消さない)。"""
    ignored = sorted(set(local_sandbox) - set(LOCAL_SANDBOX_KEYS))
    if ignored:
        print(
            "warning: local.toml の [sandbox] で追記できないキーを無視しました: "
            + ", ".join(ignored)
            + " (使えるキー: " + ", ".join(LOCAL_SANDBOX_KEYS) + ")",
            file=sys.stderr,
        )
    sandbox = dict(merged.get("sandbox") or {})
    for key in LOCAL_SANDBOX_KEYS:
        extra = local_sandbox.get(key)
        if extra:
            sandbox[key] = _uniq(list(sandbox.get(key, [])) + list(extra))
    merged["sandbox"] = sandbox


def _merge_local_locations(merged: dict[str, Any], local_locations: list[Any]) -> None:
    """local.toml の ``[[copilot.locations]]`` を追記する。

    Copilot はリポジトリ内の設定ファイルから sandbox / permissions を足せない
    ので、プロジェクト単位の許可はここが「共有設定を汚さない置き場」になる。
    同じ ``path`` が共有側にもある場合は union する (置き換えない)。
    """
    existing: dict[str, Any] = {}
    order: list[str] = []
    for entry in merged.get("copilot", {}).get("locations", []):
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        existing[entry["path"]] = dict(entry)
        order.append(entry["path"])

    for entry in local_locations:
        if not isinstance(entry, dict) or "path" not in entry:
            print(
                "warning: local.toml の [[copilot.locations]] に path がない"
                " エントリを無視しました",
                file=sys.stderr,
            )
            continue
        ignored = sorted(set(entry) - set(LOCAL_LOCATION_KEYS))
        if ignored:
            print(
                "warning: local.toml の [[copilot.locations]] で追記できない"
                "キーを無視しました: " + ", ".join(ignored)
                + " (使えるキー: " + ", ".join(LOCAL_LOCATION_KEYS) + ")",
                file=sys.stderr,
            )
        path = entry["path"]
        if path not in existing:
            existing[path] = {"path": path}
            order.append(path)
        target = existing[path]
        for key in ("approvals", "allowed_directories"):
            extra = entry.get(key)
            if not extra:
                continue
            if key == "allowed_directories":
                target[key] = _uniq(list(target.get(key, [])) + list(extra))
            else:
                current = list(target.get(key, []))
                for item in extra:
                    if item not in current:
                        current.append(item)
                target[key] = current

    copilot = dict(merged.get("copilot") or {})
    copilot["locations"] = [existing[p] for p in order]
    merged["copilot"] = copilot


def apply_local_overlay(
    common: dict[str, Any], local: dict[str, Any]
) -> dict[str, Any]:
    """ローカル上書きを common へ追記する (既存エントリは消さない)。"""
    local_sandbox = local.get("sandbox") or {}
    local_locations = (local.get("copilot") or {}).get("locations") or []
    if not local_sandbox and not local_locations:
        return common

    merged = dict(common)
    if local_sandbox:
        _merge_local_sandbox(merged, local_sandbox)
    if local_locations:
        _merge_local_locations(merged, local_locations)
    return merged


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
    common = apply_local_overlay(common, load_local_overlay())
    # 旧名・綴り間違いは防御を黙って消すので、生成前に落とす
    validate_sandbox_keys(common)
    existing = {} if args.target in FULL_GENERATION_TARGETS else load_existing(args.existing)
    merger = TARGETS[args.target]
    merged = merger(existing, common)

    json.dump(merged, sys.stdout, indent=2, ensure_ascii=False, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
