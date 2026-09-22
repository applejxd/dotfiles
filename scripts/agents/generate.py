#!/usr/bin/env python3
"""Generate per-CLI permission settings from a single common.toml.

Usage:
    generate.py --target claude-settings --common PATH [--existing PATH]
    generate.py --target copilot-perms --common PATH [--existing PATH]
    generate.py --target copilot-settings --common PATH [--existing PATH]
    generate.py --target copilot-mcp --common PATH [--existing PATH]
    generate.py --target copilot-hooks --common PATH
    generate.py --target gemini-settings --common PATH [--existing PATH]
    generate.py --target opencode-config --common PATH [--existing PATH]

If --existing is omitted, stdin is read. The merged JSON is printed to stdout.
For Copilot, automatically-managed keys (copilotTokens, loggedInUsers, etc.) in
the existing settings.json are preserved.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
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


def is_managed_hook_command(command: Any) -> bool:
    """コマンド文字列が本リポジトリの生成した hook かどうかを判定する。

    settings.json の hooks は Orca などの外部ツールも追記する共有領域なので、
    「HOOKS_DIR 配下のスクリプトを起動しているか」で自分の生成物だけを識別する。
    ホーム部分の表記 (絶対パス / `$HOME` / `~`) と引用符の有無は問わない。
    絶対パスで比較すると PowerShell の `''` エスケープや別表記のホームを
    取りこぼし、消し損ねた hook が二重登録される。
    """
    if not isinstance(command, str):
        return False
    return HOOKS_DIR_TAIL in command.replace("\\", "/")


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
# OpenCode config target (~/.config/opencode/opencode.json)
# ---------------------------------------------------------------------------

OPENCODE_SCHEMA = "https://opencode.ai/config.json"

# ``formatter`` の各エントリで使えるキー (公式 Formatters ガイドの表)。
OPENCODE_FORMATTER_KEYS = frozenset({"disabled", "command", "environment", "extensions"})

# 組み込み formatter の名前。ここに載っている名前は ``command`` /
# ``extensions`` を省いても組み込みの値を継承するが、載っていない名前は
# 両方揃っていないと **OpenCode が黙って無視する** ので生成時に弾く。
OPENCODE_BUILTIN_FORMATTERS = frozenset({
    "gofmt", "mix", "oxfmt", "prettier", "biome", "zig", "clang-format",
    "ktlint", "ruff", "air", "uv", "rubocop", "standardrb", "htmlbeautifier",
    "dart", "ocamlformat", "terraform", "latexindent", "gleam", "shfmt",
    "nixfmt", "rustfmt", "pint", "ormolu", "cljfmt", "dfmt",
})

# キーバインドの ID。公式一覧は ``leader`` 以外すべてドット区切り。
# 一覧そのものは持たない (OpenCode の版で増減するため)。綴り崩れだけ弾く。
OPENCODE_KEYBIND_ID = re.compile(r"^(leader|[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+)$")

# テーブル形式で書くときのキー (公式 Keybinds ガイド)。
OPENCODE_KEYBIND_OBJECT_KEYS = frozenset({"key", "preventDefault"})


def build_opencode_formatter(common: dict[str, Any]) -> dict[str, Any]:
    """``[opencode.formatter]`` を検査して ``formatter`` の値にする。

    オブジェクトを渡すと組み込み formatter も有効になる (公式:
    "An object also enables the built-ins")。つまりここへ書くのは組み込みに
    無いものだけでよい。

    Claude / Copilot では PostToolUse hook (``format-file.sh`` /
    ``markdownlint.sh``) が担っている役割で、OpenCode では CLI 本体の機能。
    hook 機構が無くてもここだけは等価な結果になる。

    綴り間違いや不完全な定義は「整形されないだけ」で表に出ないので、
    生成時に落とす (``[sandbox]`` の未知キー検査と同じ fail-closed)。
    """
    formatter = common.get("opencode", {}).get("formatter")
    if formatter is None:
        return {}
    if not isinstance(formatter, dict):
        raise ValueError("[opencode.formatter] はテーブルで書く")

    for name, entry in formatter.items():
        if not isinstance(entry, dict):
            raise ValueError(f"[opencode.formatter.{name}] はテーブルで書く")
        _reject_unknown(f"opencode.formatter.{name}", set(entry), OPENCODE_FORMATTER_KEYS)

        command = entry.get("command")
        if command is not None and (
            not isinstance(command, list)
            or not command
            or not all(isinstance(arg, str) for arg in command)
        ):
            raise ValueError(
                f"[opencode.formatter.{name}] の command は argv の文字列リストで書く "
                "(シェルは通らない。ファイルは $FILE で参照する)"
            )

        extensions = entry.get("extensions")
        if extensions is not None:
            if not isinstance(extensions, list) or not all(
                isinstance(ext, str) for ext in extensions
            ):
                raise ValueError(
                    f"[opencode.formatter.{name}] の extensions は文字列のリストで書く"
                )
            bad = [ext for ext in extensions if not ext.startswith(".")]
            if bad:
                raise ValueError(
                    f"[opencode.formatter.{name}] の extensions は先頭のドットが要る: "
                    + ", ".join(bad)
                )

        # 組み込みに無い名前は両方揃っていないと OpenCode が動かせない。
        # disabled だけのエントリは「消す」意図なので対象外。
        if name not in OPENCODE_BUILTIN_FORMATTERS and not entry.get("disabled"):
            missing = [key for key in ("command", "extensions") if not entry.get(key)]
            if missing:
                raise ValueError(
                    f"[opencode.formatter.{name}] は組み込みに無いので "
                    + " と ".join(missing)
                    + " が要る (欠けると OpenCode が黙って無視する)"
                )

    return formatter


def opencode_path_patterns(pattern: str) -> list[str]:
    """``[file]`` の glob を OpenCode の ``resource`` パターンへ直す。

    OpenCode のワイルドカードは ``*`` (``/`` を含む 0 文字以上) と ``?`` だけで、
    ``**`` という記法は無い。``**/x`` をそのまま渡すと ``*`` 2 つとして読まれ、
    ``foox`` のような意図しないパスにも当たる。

    ``**/`` は「0 段以上のディレクトリ」なので、``x`` (ルート直下) と
    ``*/x`` (入れ子) の 2 本に割る。展開後が ``*`` で始まるものは後者を
    既に含むので足さない (``*.pem`` は ``/home/u/a.pem`` にも当たる)。
    """
    body = pattern
    nested = body.startswith("**/")
    if nested:
        body = body[3:]
    body = body.replace("/**/", "/*/").replace("/**", "/*").replace("**", "*")
    patterns = [body]
    if nested and not body.startswith("*"):
        patterns.append("*/" + body)
    return patterns


def opencode_rules(action: str, effect: str, resources: list[str]) -> list[dict[str, str]]:
    return [
        {"action": action, "resource": resource, "effect": effect}
        for resource in _uniq(resources)
    ]


def build_opencode_sandbox_permissions(common: dict[str, Any]) -> list[dict[str, str]]:
    """隔離版の ``permissions`` を、通常版の宣言から導出する。

    **通常版は変えない。** 緩和を隔離版だけに閉じ込めるため、同じ宣言から
    別のリストを作る。取りこぼしを避けるので、宣言を足せば両方に反映される。

    捨ててよいのは「境界が到達させないもの」だけ。**ワークスペース相対の
    秘密 glob と ``.git/hooks`` は捨てない。** それらは境界の外の話ではなく、
    shell から届く (= permission は誤操作の抑止にしかならない)。
    see docs/change/0004-opencode-sandbox.md 「段階 3」
    """
    cfg = common.get("opencode", {}).get("sandbox", {}).get("permissions", {})
    drop_shell = [re.compile(p) for p in cfg.get("drop_shell", [])]
    drop_prefixes = tuple(cfg.get("drop_path_prefixes", []))
    default_effect = str(cfg.get("default_shell_effect", "ask"))

    out: list[dict[str, str]] = []
    for rule in build_opencode_permissions(common):
        action, resource = rule["action"], rule["resource"]
        if action == "shell":
            if resource == "*":
                # 既定の反転。境界内なので列挙をやめる
                out.append({**rule, "effect": default_effect})
                continue
            if any(p.match(resource) for p in drop_shell):
                continue
        elif action in ("read", "edit") and resource.startswith(drop_prefixes):
            continue
        out.append(rule)
    return out


def opencode_sandbox_policies(common: dict[str, Any]) -> list[dict[str, str]]:
    """隔離版の ``experimental.policies``。**運用上の禁止だけ**を置く。

    policies は permission 検査を hard-deny するもので、**任意コードへの
    境界ではない**。plugin のコードを sandbox しないし、不正な statement は
    警告付きで破棄されるので、置いた事実ではなく有効性を確認する。
    """
    cfg = common.get("opencode", {}).get("sandbox", {}).get("policies", {})
    return [
        {"action": "permission", "resource": str(r), "effect": "deny"}
        for r in cfg.get("deny", [])
    ]


def build_opencode_permissions(common: dict[str, Any]) -> list[dict[str, str]]:
    """``permissions`` の順序付きリストを組み立てる。

    OpenCode は **後に書いた規則が勝つ** (Claude の deny > ask > allow とは別)。
    そのため allow -> ask -> deny の順に並べる。``git reset`` が ask で
    ``git reset --hard`` が deny、という具体形の上書きはこの順序で成立する。

    先頭に ``{shell, "*", ask}`` を置いて既定を ask にする。最も一般的な規則
    なので **必ず先頭**でなければならない (後ろに置くと全部を ask で塗り潰す)。
    これが無いと、未掲載のコマンドは classifier ではなく無条件許可になる。
    OpenCode に classifier が無いため。

    ``shell`` の allow だけ ``[opencode.shell]`` から取る。``[bash] allow`` は
    Claude / Copilot と共有しており、未掲載を classifier へ委ねる前提で
    組まれているため、既定 ask の OpenCode とは前提が違う。

    ``shell`` の resource は「コマンド文字列」。末尾 ` *` は引数無しの形にも
    当たる仕様なので、素のトークン列へ ` *` を足すだけでよい。
    複合コマンドは OpenCode の scanner が分割してから照合する。

    ``ask_hook_owned`` も ask として出す。**OpenCode に hook 機構は無い**ので、
    Claude で hook に委ねている判定 (``rm`` の workspace 内判定など) を
    肩代わりするものが無く、静的な ask を外すと素通りになる。
    """
    bash = common.get("bash", {})
    file_ = common.get("file", {})
    shell_allow = common.get("opencode", {}).get("shell", {}).get("allow", [])

    rules: list[dict[str, str]] = [{"action": "shell", "resource": "*", "effect": "ask"}]

    rules += opencode_rules("shell", "allow", [f"{cmd} *" for cmd in shell_allow])
    rules += opencode_rules("shell", "ask", [f"{cmd} *" for cmd in bash.get("ask", [])])
    rules += opencode_rules("shell", "deny", [f"{cmd} *" for cmd in bash.get("deny", [])])

    for action, key, effect in (
        ("read", "claude_read_ask_globs", "ask"),
        ("edit", "claude_write_ask_globs", "ask"),
        ("read", "claude_read_deny_globs", "deny"),
        ("edit", "claude_write_deny_globs", "deny"),
    ):
        resources: list[str] = []
        for glob in file_.get(key, []):
            resources += opencode_path_patterns(glob)
        rules += opencode_rules(action, effect, resources)

    return rules


def opencode_guide_rules(common: dict[str, Any]) -> list[dict[str, str]]:
    """誘導 plugin が読む判定表 (``rules.json``)。

    ``unless`` は任意。``pattern`` に当たっても ``unless`` に当たれば見送る。
    除外条件を ``pattern`` へ畳み込むと読めない正規表現になるため分けている。
    """
    out = []
    for rule in common.get("opencode", {}).get("shell", {}).get("guide") or []:
        pattern, message = rule.get("pattern"), rule.get("message")
        if not pattern or not message:
            raise SystemExit("opencode.shell.guide は pattern と message が要る")
        entry = {"pattern": pattern, "message": message}
        unless = rule.get("unless")
        if unless:
            entry["unless"] = unless
        out.append(entry)
    return out


def opencode_ask_description(common: dict[str, Any]) -> dict[str, Any] | None:
    """確認画面に出す説明の設定 (``rules.json`` の ``ask_description``)。

    plugin 側は設定を持たず、ここで組み立てたものを読むだけにする。
    """
    cfg = common.get("opencode", {}).get("ask_description")
    if not cfg or not cfg.get("enabled"):
        return None
    models = [str(m) for m in cfg.get("models") or []]
    if not models:
        raise SystemExit("opencode.ask_description は models が 1 件以上要る")
    return {
        "min_command_length": int(cfg.get("min_command_length", 60)),
        "duration_ms": int(cfg.get("duration_ms", 20000)),
        "timeout_ms": int(cfg.get("timeout_ms", 5000)),
        "models": models,
    }


def opencode_bypass_agents(common: dict[str, Any]) -> list[str]:
    """誘導を素通りさせるエージェント名。

    ``permission = "allow"`` を持つものが「全部止めたいときの逃げ道」。
    以前は ``e.effect == "allow"`` で見分けていたが、それだと静的 allow を
    含む呼び出しまで誘導が素通りしてしまう（``cd x && git log`` など）。
    ``permission.evaluate`` に ``agent`` が載ることを実測したので名前で見る。
    see docs/research/opencode/permission/hook-order.md
    """
    agents = common.get("opencode", {}).get("agent") or {}
    return sorted(n for n, a in agents.items() if a.get("permission") == "allow")


def glob_to_regex(glob: str) -> str:
    """``[file]`` の glob を、絶対パスに当てる正規表現へ直す。

    ``grep`` / ``glob`` ツールの結果には**絶対パスが埋まっている**ので、
    どの階層に現れても当たるようにする（``(?:^|/)`` で始める）。
    see docs/research/opencode/permission/gaps.md
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "(?:^|/)" + "".join(out) + "$"


def _home_variants(glob: str) -> list[str]:
    """``~/`` 始まりの glob を、展開した形と併せて 2 本にする。

    ``grep`` / ``glob`` の結果には**展開済みの絶対パス**が載るので、
    ``~`` のままの正規表現は一度も当たらない。コマンド文字列には
    ``~`` のまま書かれるので、どちらの形も残す。
    """
    if not glob.startswith("~/"):
        return [glob]
    return [glob, expand_user(glob)]


def opencode_read_deny_regexes(common: dict[str, Any]) -> list[str]:
    """``grep`` / ``glob`` の結果を濾すためのパターン。

    ``read`` の deny glob と同じものを使う。両ツールは permission の
    ``read`` deny を迂回するので、保護は plugin 側で自作するしかない。
    see docs/research/opencode/permission/gaps.md
    """
    globs = common.get("file", {}).get("claude_read_deny_globs") or []
    return [glob_to_regex(v) for g in globs for v in _home_variants(str(g))]


def opencode_deny_path_regexes(common: dict[str, Any]) -> list[str]:
    """コマンド文字列に載ったパスへ当てるパターン (出力全体を伏せる判定)。

    ``read`` の deny glob から作るが、``**/*secret*`` のような**部分一致**は
    除く。``docs/secret-handling.md`` のような正当なパスまで当たり、
    無関係な出力を丸ごと伏せてしまうため。
    末尾の ``/**`` を落としてから最終要素で判定する
    (``**/.ssh/**`` の最終要素は ``**`` になり、素の判定では落ちる)。
    """
    out: list[str] = []
    for g in common.get("file", {}).get("claude_read_deny_globs") or []:
        base = str(g).removesuffix("/**").rsplit("/", 1)[-1]
        if len(base) > 1 and base.startswith("*") and base.endswith("*"):
            continue
        out.extend(glob_to_regex(v) for v in _home_variants(str(g)))
    return out


def opencode_redact(common: dict[str, Any]) -> dict[str, Any] | None:
    """shell 出力の伏字化の設定 (``rules.json`` の ``redact``)。

    誘導と結果フィルタを抜けたものへの安全網。**境界ではない**
    (``base64`` や ``tr`` で変換されるとすり抜ける)。
    see docs/research/opencode/permission/output-filter-and-subagents.md
    """
    cfg = common.get("opencode", {}).get("redact")
    if not cfg or not cfg.get("enabled"):
        return None
    rules: list[dict[str, str]] = []
    for rule in cfg.get("rule") or []:
        name, pattern = rule.get("name"), rule.get("pattern")
        if not name or not pattern:
            raise SystemExit("opencode.redact.rule は name と pattern が要る")
        rules.append({"name": str(name), "pattern": str(pattern)})
    out: dict[str, Any] = {"rule": rules}
    if cfg.get("deny_path_output"):
        out["deny_path"] = opencode_deny_path_regexes(common)
        unless = cfg.get("deny_path_unless")
        if unless:
            out["deny_path_unless"] = str(unless)
    return out


def _project_boundary(
    cfg: dict[str, Any],
    common: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    """プロジェクト 1 つ分の境界設定を組み立てる。

    共通の許可リストに、プロジェクト固有の追加分を足す。
    **許可リストはプロジェクト側のファイルに置かない。** 敵対的なリポジトリが
    自分で ``~/.ssh`` を許可できてしまい、グローバル設定が負ける穴と同じになる。
    ここ (``common.toml``) がプロジェクトパスをキーとして持つ。
    """
    workspace = expand_user(str(project["path"]))
    read = [expand_user(str(p)) for p in cfg.get("read") or []]
    write = [expand_user(str(p)) for p in cfg.get("write") or []]
    deny_read = [expand_user(str(p)) for p in cfg.get("deny_read") or ["~"]]
    # プロジェクト固有の追加分。機密でないパスだけを開ける。
    read += [expand_user(str(p)) for p in project.get("read") or []]
    write += [expand_user(str(p)) for p in project.get("write") or []]
    protected = [str(Path(workspace) / rel) for rel in cfg.get("protected") or []]

    sandbox_cfg = common.get("sandbox", {})
    web = common.get("web", {})
    network: dict[str, Any] = {
        "allowedDomains": _uniq(
            list(web.get("allow_domains", []))
            + list(sandbox_cfg.get("claude_network_allow", []))
            + list(cfg.get("network_allow", []))
            + list(project.get("network_allow", []))
        ),
        "deniedDomains": _uniq(list(web.get("deny_domains", []))),
        "allowLocalBinding": False,
    }
    out: dict[str, Any] = {
        "workspace": workspace,
        "config": {
            "network": network,
            "filesystem": {
                "denyRead": _uniq(deny_read),
                "allowRead": _uniq([workspace, *read]),
                "allowWrite": _uniq([workspace, *write]),
                "denyWrite": protected,
            },
        },
    }
    for key in ("data_home", "db"):
        rel = cfg.get(key)
        if rel:
            out[key] = str(Path(workspace) / str(rel))
    return out


def opencode_sandbox(common: dict[str, Any]) -> dict[str, Any] | None:
    """OpenCode を丸ごと囲う境界の設定 (CHG-0004 段階 2・4)。

    ランチャーが ``srt -s <この設定> -c "opencode --standalone"`` で使う。
    **プロジェクトごとに 1 つ**の境界設定を出し、ランチャーが cwd で選ぶ。

    **``runtime_path`` の実体があるときだけ返す。** 無いマシン (macOS /
    Windows / 初回 apply 前) では設定を出さず、ランチャーは起動を断る。
    ``seccomp_apply_path`` と同じ作り。

    癖が 2 つある。どちらも黙って壊れるので注意する。
    see docs/research/opencode/permission/sandbox-runtime.md

    - R1: ``allowRead`` に ``allowWrite`` の祖先を載せると書き込みが無効化される。
      ワークスペースは両方へ完全一致で入れる。
    - R2: どちらにも載らない領域への書き込みは「成功したように見えて消える」。
    """
    cfg = common.get("opencode", {}).get("sandbox")
    if not cfg or not cfg.get("enabled"):
        return None
    runtime = expand_user(str(cfg.get("runtime_path", "")))
    if not runtime or not Path(runtime).is_file():
        return None

    # 主プロジェクト + 追加宣言。順序は宣言順で、ランチャーは最長一致で選ぶ。
    declared: list[dict[str, Any]] = [{"path": cfg["workspace"]}]
    declared += [dict(p) for p in cfg.get("project") or [] if p.get("path")]

    out: dict[str, Any] = {
        "runtime_path": runtime,
        "projects": [_project_boundary(cfg, common, p) for p in declared],
    }
    # 隔離版の設定ディレクトリは**ワークスペースの外**。内側からは allowRead
    # だけなので、緩和設定を自分で広げられない。ランチャーが起動のたびに
    # ここへ opencode.json を書き直す。
    config_dir = cfg.get("config_dir")
    if config_dir:
        out["config_dir"] = expand_user(str(config_dir))
    out["permissions"] = build_opencode_sandbox_permissions(common)
    # 誘導 plugin を隔離版でも読み込む。**目的は伏字化**（境界内の `.env` などが
    # そのままモデルの文脈へ入るのを防ぐ）。境界はワークスペースの中を守らない。
    # ★段階 5 で当初案（`grep` / `glob` の無効化と誘導の削除）は撤回した。
    #   消すと `read` / `edit` の deny が空振りする。
    #   see docs/change/0004-opencode-sandbox.md 「段階 5」
    if opencode_guide_rules(common) or opencode_redact(common):
        out["plugins"] = [opencode_guide_plugin_path()]
    policies = opencode_sandbox_policies(common)
    if policies:
        out["policies"] = policies
    prompt = cfg.get("system_prompt")
    if prompt:
        out["system_prompt"] = str(prompt).strip()
    # 既定モデルの優先順。ランチャーが資格情報のある provider を上から選ぶ。
    # ★実在しない ID を書くと起動しても応答が来ないので、宣言側で確認する。
    preference = cfg.get("model_preference") or []
    if preference:
        out["model_preference"] = [
            {"provider": str(p.get("provider", "")), "model": str(p.get("model", ""))}
            for p in preference
            if p.get("provider") and p.get("model")
        ]
    return out


def build_opencode_guide(_existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "guide": opencode_guide_rules(common),
        "bypass_agents": opencode_bypass_agents(common),
        "read_deny": opencode_read_deny_regexes(common),
    }
    ask = opencode_ask_description(common)
    if ask:
        out["ask_description"] = ask
    redact = opencode_redact(common)
    if redact:
        out["redact"] = redact
    sandbox = opencode_sandbox(common)
    if sandbox:
        out["sandbox"] = sandbox
    return out


# 誘導 plugin の置き場。plugin / plugins という名前にしないこと。その 2 つは
# 設定ディレクトリ直下で自動探索され、明示指定と二重にロードされる。
# 明示指定は**ディレクトリ**でないと解決されず、``~`` も展開されない
# (どちらも黙って無視される)。
# see docs/research/opencode/plugin/loading.md
OPENCODE_GUIDE_PLUGIN = "~/.config/opencode/guide-plugin"


def opencode_guide_plugin_path() -> str:
    return os.path.expanduser(OPENCODE_GUIDE_PLUGIN)


def merge_opencode_plugins(existing_plugins: Any, common: dict[str, Any]) -> list[Any]:
    """``plugins`` を更新する (宣言外のエントリは残す)。"""
    path = opencode_guide_plugin_path()
    out = [p for p in (existing_plugins or []) if p not in (path, OPENCODE_GUIDE_PLUGIN)]
    if opencode_guide_rules(common) or opencode_ask_description(common):
        out.append(path)
    return out


def merge_opencode_agents(existing_agent: Any, common: dict[str, Any]) -> dict[str, Any]:
    """``agent`` を更新する (common.toml に無いエージェントは残す)。

    OpenCode 側が ``/agents`` などで同じファイルへ書くため、宣言した名前だけを
    差し替える (``mcp`` と同じ方針)。

    ``permission`` に ``"allow"`` のような文字列を置くと、OpenCode が
    ``{action:"*", resource:"*", effect:"allow"}`` へ展開する (実測)。
    """
    out = dict(existing_agent) if isinstance(existing_agent, dict) else {}
    for name, agent in (common.get("opencode", {}).get("agent") or {}).items():
        entry = dict(out.get(name) or {})
        entry.update(agent)
        out[name] = entry
    return out


def merge_opencode_mcp(existing_mcp: Any, common: dict[str, Any]) -> dict[str, Any]:
    """``mcp.servers`` を更新する (common.toml に無いサーバは残す)。

    ``opencode mcp add`` や ``/mcps`` も同じファイルへ書くため、宣言した名前
    だけを差し替える。``headers`` / ``environment`` / ``oauth`` には触らない:
    いずれもトークンを環境変数参照で入れる場所で、common.toml が持たない情報
    だから (ADR-0005)。
    """
    out = dict(existing_mcp) if isinstance(existing_mcp, dict) else {}
    servers = dict(out.get("servers") or {})
    for name, server in mcp_servers(common):
        entry = dict(servers.get(name) or {})
        if server["transport"] == "http":
            # OpenCode は http を "remote" と呼ぶ (V2 の MCP ガイド)
            entry["type"] = "remote"
            entry["url"] = server["url"]
            stale = ("command", "cwd", "environment")
        else:
            # stdio は "local"。command は実行ファイルと引数を 1 本の配列で書く
            entry["type"] = "local"
            entry["command"] = [server["command"], *server["args"]]
            stale = ("url", "headers", "oauth")
        # transport を変えたときに前の形のキーを残さない (両方あると曖昧になる)
        for key in stale:
            entry.pop(key, None)
        servers[name] = entry
    out["servers"] = servers
    return out


def _opencode_keybind_value(command: str, binding: Any) -> Any:
    """``[opencode.keybinds]`` の値 1 件を検査する。"""
    where = f"[opencode.keybinds] の {command}"
    if binding is False:
        return binding
    if binding is True:
        raise ValueError(f'{where} に true は書けない (無効化は false か "none")')
    if isinstance(binding, str):
        if not binding:
            raise ValueError(f'{where} が空文字 (無効化は "none" と書く)')
        return binding
    if isinstance(binding, list):
        if not binding or not all(isinstance(key, str) and key for key in binding):
            raise ValueError(f"{where} のリストは空でない文字列だけで書く")
        return binding
    if isinstance(binding, dict):
        _reject_unknown(
            f"opencode.keybinds.{command}", set(binding), OPENCODE_KEYBIND_OBJECT_KEYS
        )
        key = binding.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"{where} はテーブルで書くなら key が要る")
        return binding
    raise ValueError(f"{where} は文字列・リスト・テーブル・false のどれかで書く")


def build_opencode_keybinds(common: dict[str, Any]) -> dict[str, Any]:
    """``[opencode.keybinds]`` を検査して ``cli.json`` の ``keybinds`` にする。

    キーバインドは **``cli.json`` 側にしか無い**。``opencode.json`` へ書いても
    読まれないので、誤配置に気づけない。
    see docs/spec/agent-permissions.md 「キーバインド」
    """
    keybinds = common.get("opencode", {}).get("keybinds")
    if keybinds is None:
        return {}
    if not isinstance(keybinds, dict):
        raise ValueError("[opencode.keybinds] はテーブルで書く")

    out: dict[str, Any] = {}
    for command, binding in keybinds.items():
        if not OPENCODE_KEYBIND_ID.match(command):
            raise ValueError(
                f"[opencode.keybinds] の {command!r} は ID の形をしていない "
                "(公式一覧の ID をそのまま書く)"
            )
        out[command] = _opencode_keybind_value(command, binding)
    return out


def merge_opencode_cli(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``~/.config/opencode/cli.json`` を更新する。

    TUI 側 plugin は **``cli.json`` からしか読まれない**（``opencode.json`` の
    ``plugins`` はサーバ側だけ）。キーバインドも同じくここにしか書けない。
    ``attention`` などユーザ設定が同居するので、宣言したエントリだけを
    差し替える。
    see docs/research/opencode/plugin/loading.md
    """
    out = dict(existing)
    keybinds = build_opencode_keybinds(common)
    if keybinds:
        # 宣言したら keybinds テーブルごと common.toml 側の持ち物にする。
        # 1 件消したときに配備先へ残らないようにするため。
        out["keybinds"] = keybinds
    path = opencode_guide_plugin_path()
    plugins = [p for p in (out.get("plugins") or []) if p not in (path, OPENCODE_GUIDE_PLUGIN)]
    if opencode_guide_rules(common) or opencode_ask_description(common):
        plugins.append(path)
    if plugins:
        out["plugins"] = plugins
    else:
        out.pop("plugins", None)
    return out


def merge_opencode_config(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``~/.config/opencode/opencode.json`` (global config) を更新する。

    ``permissions`` は毎回置き換える。対話で「常に許可」した内容は
    project scope の saved approval として別に保存され、このファイルには
    入らないので、置き換えても手元の承認は失われない。
    """
    out: dict[str, Any] = {"$schema": OPENCODE_SCHEMA}
    out.update(existing)
    out["$schema"] = OPENCODE_SCHEMA

    opencode = common.get("opencode", {})
    if "auto_update" in opencode:
        out["update"] = "notify" if opencode["auto_update"] else "disable"

    formatter = build_opencode_formatter(common)
    if formatter:
        out["formatter"] = formatter

    out["permissions"] = build_opencode_permissions(common)
    plugins = merge_opencode_plugins(existing.get("plugins"), common)
    if plugins:
        out["plugins"] = plugins
    agent = merge_opencode_agents(existing.get("agent"), common)
    if agent:
        out["agent"] = agent
    out["mcp"] = merge_opencode_mcp(existing.get("mcp"), common)
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
    "opencode-cli": merge_opencode_cli,
    "opencode-config": merge_opencode_config,
    "opencode-guide": build_opencode_guide,
}

# 既存内容を一切参照しない (完全生成の) ターゲット。
# 既存ファイルが壊れた JSON でも作り直せるよう、読み込み自体を省く。
# 省かないと、壊れたファイルを直すための apply がパースで失敗して詰む。
FULL_GENERATION_TARGETS = {"copilot-hooks", "opencode-guide"}


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
