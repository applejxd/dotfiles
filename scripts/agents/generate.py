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
import ntpath
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # Python 3.10 以下には tomllib が無い
    raise SystemExit(
        "agent 設定の生成には Python 3.11 以上が必要です"
        f" (実行中: {platform.python_version()} / {sys.executable})。"
        " chezmoi の [interpreters.py] が古い python を指していると起きます。"
        " `chezmoi init` で設定を作り直すか、3.11 以上を導入してください。"
        " see docs/spec/troubleshooting.md"
    ) from exc

# PYTHONSAFEPATH / -P で起動されても隣のモジュールを import できるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooks import expand_user, merge_claude_hooks, merge_copilot_hooks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    for glob in file_.get("read_deny_globs", []):
        deny.append(f"Read({glob})")
    for glob in file_.get("write_deny_globs", []):
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
    for glob in file_.get("read_ask_globs", []):
        ask.append(f"Read({glob})")
    for glob in file_.get("write_ask_globs", []):
        ask.append(f"Edit({glob})")

    return {"allow": _uniq(allow), "ask": _uniq(ask), "deny": _uniq(deny)}


def _uniq(seq: list[str]) -> list[str]:
    """重複を除き、最初に現れた順を保つ。"""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _expand_sandbox_paths(paths: list[str]) -> list[str]:
    """``~`` を展開し、Copilot が扱えないワイルドカード入りを落とす。

    Windows では ``C:\\Users\\x/.ssh`` と区切りが混ざるので、OS の形式へ揃える
    (Copilot の設定例は ``C:\\Users\\...``)。see docs/spec/agent-permissions.md#windows-での扱い
    """
    return [_os_path(expand_user(path)) for path in paths if "*" not in path and "?" not in path]


def _os_path(path: Any) -> Any:
    """Windows では区切りを OS の形式へ揃える。それ以外の OS と文字列以外はそのまま。"""
    if os.name == "nt" and isinstance(path, str):
        return ntpath.normpath(path)
    return path


# ``[sandbox]`` で使えるキー。新しいキーは **共有 = 無印 / CLI 固有 = CLI 名の接頭辞**
# で付ける ([[hooks]] の claude_event / copilot_event と同じ規則)。無印でも
# seccomp_apply_path と shell_network_allow は既存の例外で、Copilot へは渡らない。
# see docs/spec/glossary.md
SHARED_SANDBOX_KEYS = frozenset({"deny", "seccomp_apply_path", "shell_network_allow"})
CLAUDE_SANDBOX_KEYS = frozenset(
    {
        "claude_read_allow",
        "claude_write_allow",
        "claude_write_deny",
        "claude_network_strict",
    }
)
COPILOT_SANDBOX_KEYS = frozenset(
    {
        "copilot_read_allow",
        "copilot_write_allow",
        "copilot_allow_dev_tool_access",
    }
)
KNOWN_SANDBOX_KEYS = SHARED_SANDBOX_KEYS | CLAUDE_SANDBOX_KEYS | COPILOT_SANDBOX_KEYS

# ``[file]`` の deny / ask glob は **Claude 専用ではない**。
#   - Claude   : Read() / Edit() の permission になる
#   - OpenCode : 通常版・境界版の read / edit 規則になる (CHG-0004 で追加)
#   - Copilot  : check_file_read.py が同じリストを view ツールへ適用する
# そのため接頭辞を付けない (ADR-0007「共有 = 無印」)。
# ``claude_read_allow`` だけは Claude 固有の補償なので接頭辞を残す。
KNOWN_FILE_KEYS = frozenset(
    {
        "claude_read_allow",
        "read_ask_globs",
        "write_ask_globs",
        "read_deny_globs",
        "write_deny_globs",
        "deny_exceptions",
    }
)


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
    ``[sandbox] shell_network_allow`` (shell が実際に通信するCDN等) を合算して
    ``sandbox.network.allowedDomains`` に渡す。
    Claude は ``WebFetch(domain:...)`` の許可ルールからも sandbox の
    allowlist を組み立てるため前者は実質二重になるが、permission 側の記法が
    変わっても sandbox の許可が崩れないよう明示しておく。

    ``[sandbox] claude_network_strict`` が真なら ``strictAllowlist`` を立てて
    許可外ドメインを **拒否** する (Claude Code v2.1.219 以降が必要)。
    これを立てないと許可外は拒否ではなく **承認プロンプト** になる。
    Copilot にはドメイン単位の制御が無いため (``allowOutbound`` の on/off
    だけ)、ネットワークだけは両 CLI で揃えられない。
    """
    sandbox = common.get("sandbox", {})
    deny = list(sandbox.get("deny", []))
    claude_write_deny = list(sandbox.get("claude_write_deny", []))
    web = common.get("web", {})

    network: dict[str, Any] = {
        "allowedDomains": _uniq(
            list(web.get("allow_domains", [])) + list(sandbox.get("shell_network_allow", []))
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
            "denyWrite": _uniq(deny + claude_write_deny),
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
MCP_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
# transport ごとの必須キー。両方の形のキーを持つ定義は生成先で曖昧になるので、
# ここに無いキーは (typo も含めて) 弾く。
MCP_TRANSPORT_KEYS = {
    "http": {"url"},
    "stdio": {"command", "args"},
}
MCP_COMMON_KEYS = {"id", "purpose", "transport", "clis"}

# ``clis`` に書ける生成先。省略したら全部に入る。
MCP_CLIS = {"claude", "copilot", "opencode", "codex"}


def mcp_servers(common: dict[str, Any], cli: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    """``[[mcp]]`` を (名前, 定義) の宣言順リストにして返す。

    ユーザ・OS による出し分けは common.toml 側の chezmoi テンプレートが
    済ませているので、ここには条件が無い (展開後の表だけを見る)。

    ``cli`` を渡すと、``clis`` でその生成先を除いたサーバを落とす。
    ``clis`` を書かないサーバは全部の生成先に入る。

    設定ミスは黙って無効な MCP 定義を書き出すより、apply を止めた方がよい
    (生成先の 3 つが食い違ったまま気付けなくなる)。
    """
    servers: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for server in common.get("mcp", []):
        name = server.get("id", "")
        if not name or set(name) - MCP_ID_CHARS:
            raise ValueError(
                f"[[mcp]] の id が不正: {name!r} (英数字・ハイフン・アンダースコアのみ)"
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

        targets = server.get("clis")
        if targets is not None:
            if not isinstance(targets, list) or not targets:
                raise ValueError(f"[[mcp]] {name} の clis は空でないリストで書く")
            bad = sorted(set(targets) - MCP_CLIS)
            if bad:
                raise ValueError(
                    f"[[mcp]] {name} の clis に未対応の生成先がある: "
                    + ", ".join(bad)
                    + f" (対応: {', '.join(sorted(MCP_CLIS))})"
                )
            if cli is not None and cli not in targets:
                continue

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
    for name, server in mcp_servers(common, "copilot"):
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


def build_copilot_sandbox(existing_sandbox: Any, common: dict[str, Any]) -> dict[str, Any]:
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
        # 以前の版が書いた C:\Users\x/.local のような形も揃えてから合算する (重複させない)
        current = [_os_path(p) for p in current] if isinstance(current, list) else []
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
    if copilot.get("model"):
        out["model"] = copilot["model"]
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
OPENCODE_BUILTIN_FORMATTERS = frozenset(
    {
        "gofmt",
        "mix",
        "oxfmt",
        "prettier",
        "biome",
        "zig",
        "clang-format",
        "ktlint",
        "ruff",
        "air",
        "uv",
        "rubocop",
        "standardrb",
        "htmlbeautifier",
        "dart",
        "ocamlformat",
        "terraform",
        "latexindent",
        "gleam",
        "shfmt",
        "nixfmt",
        "rustfmt",
        "pint",
        "ormolu",
        "cljfmt",
        "dfmt",
    }
)

# キーバインドの ID。公式一覧は ``leader`` 以外すべてドット区切り。
# 一覧そのものは持たない (OpenCode の版で増減するため)。綴り崩れだけ弾く。
OPENCODE_KEYBIND_ID = re.compile(r"^(leader|[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+)$")

# テーブル形式で書くときのキー (公式 Keybinds ガイド)。
OPENCODE_KEYBIND_OBJECT_KEYS = frozenset({"key", "preventDefault"})


def build_opencode_formatter(common: dict[str, Any]) -> dict[str, Any] | None:
    """``[opencode.formatter]`` を検査して ``formatter`` の値にする。

    未宣言は ``None`` (既存に触らない)、空テーブルは ``{}`` (置き換える)。

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
        return None
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
        {"action": action, "resource": resource, "effect": effect} for resource in _uniq(resources)
    ]


def opencode_external_read_dirs(common: dict[str, Any]) -> list[str]:
    """作業ツリーの外でも確認なしに読める場所 (``~`` のまま返す)。

    ``[opencode.external_read] paths`` に隔離版の ``work_read`` を足す。
    隔離版で読める作業場所を、通常版でも同じ一覧から開ける (二重に並べない)。
    """
    opencode = common.get("opencode", {})
    dirs = [
        *opencode.get("external_read", {}).get("paths", []),
        *opencode.get("sandbox", {}).get("work_read", []),
    ]
    return _uniq([str(d).rstrip("/") for d in dirs])


def opencode_external_read_rules(common: dict[str, Any]) -> list[dict[str, str]]:
    """``external_directory`` を allow にし、同じ場所の ``edit`` は ask に戻す。

    ``external_directory`` は read と edit の**両方**の前段なので、allow だけだと
    既定 allow の edit が確認なしに通る。read は既定で allow なので足さない
    (足すと既定の ``*.env`` の ask を上書きする)。``~`` は OpenCode が展開する。
    see docs/spec/agent-config-generation.md#作業ツリーの外の読み取り
    """
    dirs = [f"{d}/*" for d in opencode_external_read_dirs(common)]
    return opencode_rules("external_directory", "allow", dirs) + opencode_rules("edit", "ask", dirs)


def opencode_skill_script_rules(common: dict[str, Any]) -> tuple[list[str], list[str]]:
    """スキルのスクリプトを確認なしに実行させる shell 規則 (allow, deny)。

    shell の resource は生のコマンド文字列で ``~`` を展開しないので、``~/`` と
    展開した形の両方を出す。``exact`` は引数ごと完全一致で通す (前方一致の
    ``*`` を付けない)。前方一致の形はリダイレクト (``>`` / ``<``) が任意書き込みの
    手段になるので、allow の後ろで deny にする。
    see docs/spec/agent-config-generation.md#スキルのスクリプト
    """
    allow, heads = _skill_script_allow_and_heads(common)
    deny = [r for head in heads for r in (f"{head} *>*", f"{head} *<*")]
    return allow, deny


def _skill_script_allow_and_heads(common: dict[str, Any]) -> tuple[list[str], list[str]]:
    """スキルのスクリプトの allow と、前方一致で通す形の先頭 (リダイレクトを deny する対象)。"""
    cfg = common.get("opencode", {}).get("skill_scripts", {})
    runners = cfg.get("runners", {})
    roots = tuple(
        expand_user(d).replace("\\", "/") + "/"
        for d in common.get("opencode", {}).get("external_read", {}).get("paths", [])
    )
    allow: list[str] = []
    heads: list[str] = []
    for entry in cfg.get("allow", []):
        script = str(entry.get("script", ""))
        where = f"[opencode.skill_scripts] の {script!r}"
        if ".." in script.split("/") or not expand_user(script).replace("\\", "/").startswith(
            roots
        ):
            raise ValueError(f"{where} が [opencode.external_read] paths の中に無い")
        suffix = script.rsplit(".", 1)[-1] if "." in script else ""
        if not runners.get(suffix):
            raise ValueError(f"{where} の拡張子に対応する runners が無い")
        exact = entry.get("exact") or []
        if exact and entry.get("subcommands"):
            raise ValueError(f"{where} は exact と subcommands を併用できない")
        for runner in runners[suffix]:
            for path in _home_variants(script):
                allow += [f"{runner} {path} {args}" for args in exact]
                for sub in [] if exact else entry.get("subcommands") or [""]:
                    head = f"{runner} {path}" + (f" {sub}" if sub else "")
                    allow.append(f"{head} *")
                    heads.append(head)
    return allow, heads


def opencode_skill_script_asks(common: dict[str, Any]) -> list[str]:
    """スキルのスクリプトのうち、確認 (ask) を通すサブコマンド (``ask = [...]``)。

    隔離版はシェルの既定が allow なので、確認を残すには明示の ask が要る。
    ``allow`` の規則と違い、隔離版でも捨てない。
    see docs/change/0014-deterministic-commit-runner.md
    """
    cfg = common.get("opencode", {}).get("skill_scripts", {})
    runners = cfg.get("runners", {})
    out: list[str] = []
    for entry in cfg.get("allow", []):
        script = str(entry.get("script", ""))
        asks = entry.get("ask") or []
        overlap = set(asks) & set(entry.get("subcommands") or [])
        if overlap or (asks and entry.get("exact")):
            raise ValueError(f"[opencode.skill_scripts] の {script!r} は ask と allow が重なる")
        suffix = script.rsplit(".", 1)[-1] if "." in script else ""
        for runner in runners.get(suffix, []):
            for path in _home_variants(script):
                out += [f"{runner} {path} {sub} *" for sub in asks]
    return out


def build_opencode_sandbox_permissions(common: dict[str, Any]) -> list[dict[str, str]]:
    """隔離版の ``permissions`` を、通常版の宣言から導出する。

    **通常版は変えない。** 緩和を隔離版だけに閉じ込めるため、同じ宣言から
    別のリストを作る。取りこぼしを避けるので、宣言を足せば両方に反映される。

    捨ててよいのは「境界が到達させないもの」だけ。**ワークスペース相対の
    秘密 glob と ``.git/hooks`` は捨てない。** それらは境界の外の話ではなく、
    shell から届く (= permission は誤操作の抑止にしかならない)。
    see docs/change/closed/0004-opencode-sandbox.md 「段階 3」
    """
    cfg = common.get("opencode", {}).get("sandbox", {}).get("permissions", {})
    drop_shell = [re.compile(p) for p in cfg.get("drop_shell", [])]
    drop_prefixes = tuple(cfg.get("drop_path_prefixes", []))
    default_effect = str(cfg.get("default_shell_effect", "ask"))
    # 既定が allow なら、スキルのスクリプトの規則は拒否 (リダイレクトの deny) を増やすだけ
    skill_rules = (
        {r for group in opencode_skill_script_rules(common) for r in group}
        if default_effect == "allow"
        else set()
    )
    # 開けた場所への edit の確認は残す (以前は external_directory の確認が止めていた)。
    # deny の例外と交差する ask (`<dir>/*/.env.example` など) も同じ理由で残す
    opened = tuple(f"{d}/" for d in opencode_external_read_dirs(common))

    out: list[dict[str, str]] = []
    for rule in build_opencode_permissions(common):
        action, resource = rule["action"], rule["resource"]
        if action == "shell":
            if resource == "*":
                # 既定の反転。境界内なので列挙をやめる
                out.append({**rule, "effect": default_effect})
                continue
            if any(p.match(resource) for p in drop_shell) or resource in skill_rules:
                continue
        elif (
            action in ("read", "edit")
            and resource.startswith(drop_prefixes)
            and not (action == "edit" and rule["effect"] == "ask" and resource.startswith(opened))
        ):
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
        {"action": "permission", "resource": str(r), "effect": "deny"} for r in cfg.get("deny", [])
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
    skill_allow, skill_deny = opencode_skill_script_rules(common)

    rules += opencode_rules("shell", "allow", [f"{cmd} *" for cmd in shell_allow])
    rules += opencode_rules("shell", "allow", skill_allow)
    rules += opencode_rules("shell", "ask", [f"{cmd} *" for cmd in bash.get("ask", [])])
    rules += opencode_rules("shell", "ask", opencode_skill_script_asks(common))
    rules += opencode_rules("shell", "deny", skill_deny)
    rules += opencode_rules("shell", "deny", [f"{cmd} *" for cmd in bash.get("deny", [])])

    # read / edit の ask・deny より前に置く (秘密の deny を後勝ちで効かせる)
    rules += opencode_external_read_rules(common)

    for action, key, effect in (
        ("read", "read_ask_globs", "ask"),
        ("edit", "write_ask_globs", "ask"),
    ):
        resources: list[str] = []
        for glob in file_.get(key, []):
            resources += opencode_path_patterns(glob)
        rules += opencode_rules(action, effect, resources)

    # deny。例外のある glob を先頭に出し、その直後に例外の allow を置く。後勝ちなので、
    # 例外は対の deny にだけ勝ち、後ろの deny (.ssh/** や *secret* など) には負ける。
    # 例外の allow は、それより前の ask (作業ツリー外の edit の確認など) も潰すので、
    # ask と例外の交差を ask として直後に戻す
    exceptions = file_deny_exceptions(common)
    for action, key in (("read", "read_deny_globs"), ("edit", "write_deny_globs")):
        globs = [str(g) for g in file_.get(key, [])]
        paired = [e for e in exceptions if e["deny"] in globs]
        asked = [r["resource"] for r in rules if r["action"] == action and r["effect"] == "ask"]
        for entry in paired:
            rules += opencode_rules(action, "deny", opencode_path_patterns(entry["deny"]))
            allow: list[str] = []
            for glob in entry["except"]:
                allow += opencode_path_patterns(glob)
            rules += opencode_rules(action, "allow", allow)
            rules += opencode_rules(
                action,
                "ask",
                [i for a in asked for e in _uniq(allow) for i in wildcard_intersection(a, e)],
            )
        resources: list[str] = []
        for glob in globs:
            if any(glob == e["deny"] for e in paired):
                continue
            resources += opencode_path_patterns(glob)
        rules += opencode_rules(action, "deny", resources)

    rules += opencode_subagent_guards(common)
    return rules


def wildcard_intersection(a: str, b: str) -> list[str]:
    """OpenCode の 2 つの resource パターン (``*`` は ``/`` を含む 0 文字以上) の交差。

    扱えるのは ``*`` が 0 個か 1 個のパターンだけ (``?`` と複数の ``*`` は ``ValueError``)。
    交差を作れないものを黙って落とすと、ask が allow に化けるので止める。
    返すのは「両方に当たる文字列」の集合を表すパターン (空なら交差なし)。
    """
    for p in (a, b):
        if "?" in p or p.count("*") > 1:
            raise ValueError(f"resource の交差を作れないパターン: {p!r}")

    def matches(pattern: str, value: str) -> bool:
        head, star, tail = pattern.partition("*")
        if not star:
            return value == pattern
        return (
            len(value) >= len(head) + len(tail) and value.startswith(head) and value.endswith(tail)
        )

    if "*" not in a:
        return [a] if matches(b, a) else []
    if "*" not in b:
        return [b] if matches(a, b) else []
    (p1, _, s1), (p2, _, s2) = a.partition("*"), b.partition("*")
    if not (p1.startswith(p2) or p2.startswith(p1)) or not (s1.endswith(s2) or s2.endswith(s1)):
        return []
    prefix, suffix = max(p1, p2, key=len), max(s1, s2, key=len)
    out = [f"{prefix}*{suffix}"]
    # prefix と suffix が重なる短い文字列 (`D/*` ∩ `*/L` の `D/L` など)
    for k in range(1, min(len(prefix), len(suffix)) + 1):
        merged = prefix + suffix[k:]
        if prefix.endswith(suffix[:k]) and matches(a, merged) and matches(b, merged):
            out.append(merged)
    return out


def file_deny_exceptions(common: dict[str, Any]) -> list[dict[str, Any]]:
    """``[[file.deny_exceptions]]`` を検査して返す (deny の glob とその例外の対)。

    ``deny`` は ``read_deny_globs`` か ``write_deny_globs`` の項目と同じ文字列でなければならない
    (対の相手が無い例外は黙って効かないので、生成を止める)。
    """
    file_ = common.get("file", {})
    known = {str(g) for k in ("read_deny_globs", "write_deny_globs") for g in file_.get(k, [])}
    out: list[dict[str, Any]] = []
    for entry in file_.get("deny_exceptions") or []:
        deny, globs = entry.get("deny"), entry.get("except")
        if (
            set(entry) != {"deny", "except"}
            or not isinstance(deny, str)
            or not isinstance(globs, list)
            or not globs
            or not all(isinstance(g, str) for g in globs)
        ):
            raise ValueError(
                f"[[file.deny_exceptions]] は deny (文字列) と except (文字列の配列): {entry}"
            )
        if deny not in known:
            raise ValueError(f"[[file.deny_exceptions]] の deny が deny の一覧に無い: {deny}")
        out.append({"deny": deny, "except": [str(g) for g in globs]})
    return out


def opencode_guide_rules(common: dict[str, Any]) -> list[dict[str, Any]]:
    """誘導 plugin が読む判定表 (``rules.json``)。

    ``early = true`` の規則は ``tool.execute.before`` でも判定する (静的 deny の前に止める)。

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
        if rule.get("early") is True:
            entry["early"] = True
        out.append(entry)
    return out


# 前段停止の「セグメント先頭」と語境界 (単一の空白・区切り・末尾)。
# 引用符・括弧・``#``・``\``・``<<``・単語の ``{`` を含むコマンドは前段で止めない。
# see docs/spec/agent-command-policy.md#opencode-の-deny-の説明前段停止
DENY_GUIDE_SEGMENT_START = r"(^|&&|\|\||[;|\n])[ \t]*"
DENY_GUIDE_COMMAND_END = r"(?= |$|[;|\n]|&&)"
DENY_GUIDE_UNLESS = r"""['"`\\#()]|<<|(^|[\s;&|])\{(\s|$)"""

# 全体の規則だけで動き、``permission`` を組み込みの既定のまま使う組み込みエージェント。
# 利用者が opencode.json で上書きしていても生成器は知らない (既知の限界)。
OPENCODE_BUILTIN_SHELL_AGENTS = ("build", "plan", "general", "explore")


def _regex_escape(token: str) -> str:
    return re.sub(r"([.*+?^${}()|\[\]\\])", r"\\\1", token)


def _static_shell_denies(rules: list[dict[str, str]]) -> set[str]:
    return {r["resource"] for r in rules if r["action"] == "shell" and r["effect"] == "deny"}


def _agent_shell_overrides(agent: dict[str, Any]) -> list[str]:
    """エージェントの規則のうち、全体の shell deny を覆しうる (deny 以外の) resource。

    V2 の ``permissions`` (リスト) と V1 の ``permission`` (文字列または表。キーは
    ``bash`` / ``shell`` / ``*``) の両方を見る。読めない形は ``*`` (全部を覆す) とする。
    """
    out: list[str] = []
    for rule in agent.get("permissions") or []:
        if rule.get("action") in ("shell", "*") and rule.get("effect") != "deny":
            out.append(str(rule.get("resource", "*")))
    legacy = agent.get("permission")
    if isinstance(legacy, str):
        legacy = {"*": legacy}
    for key, value in (legacy if isinstance(legacy, dict) else {}).items():
        if key not in ("bash", "shell", "*"):
            continue
        if isinstance(value, str):
            value = {"*": value}
        if not isinstance(value, dict):
            out.append("*")
            continue
        out += [str(res) for res, eff in value.items() if eff != "deny"]
    return out


def opencode_deny_guide_agents(common: dict[str, Any]) -> list[str]:
    """前段停止を効かせるエージェント (permission を生成器が把握しているものだけ)。

    宣言済み (V1 / V2) + 組み込み。宣言外 (利用者が opencode.json に直接書いたもの) は含めず、
    plugin は見送って静的 deny に任せる。
    """
    return sorted({*_declared_agents(common), *OPENCODE_BUILTIN_SHELL_AGENTS})


def _deny_guide_exempt_agents(common: dict[str, Any], command: str) -> list[str]:
    """``command`` の静的 deny を、エージェントの規則 (後勝ち) で覆しうる宣言済みエージェント。

    交差を作れない形は覆しうるものとして扱う (止めない側に倒す)。
    """
    opencode = common.get("opencode", {})
    out: list[str] = []
    for source in ("agents", "agent"):
        for name, agent in (opencode.get(source) or {}).items():
            for resource in _agent_shell_overrides(agent):
                try:
                    hit = any(wildcard_intersection(p, resource) for p in (command, f"{command} *"))
                except ValueError:
                    hit = True
                if hit:
                    out.append(str(name))
                    break
    return sorted(set(out))


def opencode_deny_guide_rules(common: dict[str, Any]) -> list[dict[str, Any]]:
    """``rules.json`` の ``deny_guide`` (静的 deny を説明付きで止める前段の規則)。"""
    return _bash_deny_guide_rules(common) + _skill_script_deny_guide_rules(common)


# 前方一致の先頭の後ろで、セグメントを越えずに > / < へ届く形。
# & の手前で打ち切る (2>&1 は > が先に来るので当たる。&> は静的 deny に任せる)。
SKILL_REDIRECT_TAIL = r" [^;|&\n]*[<>]"


def _skill_script_deny_guide_rules(common: dict[str, Any]) -> list[dict[str, Any]]:
    """スキルのスクリプトのリダイレクトの静的 deny に説明を付ける。

    静的 deny (``{head} *>*`` / ``{head} *<*``) と同じ範囲だけを止める。``exact`` と
    ``subcommands`` に無い形は静的 deny に無いので対象にしない。
    see docs/spec/agent-config-generation.md#スキルのスクリプト
    """
    _, heads = _skill_script_allow_and_heads(common)
    if not heads:
        return []
    message = str(common.get("opencode", {}).get("skill_scripts", {}).get("redirect_message") or "")
    if not message:
        raise SystemExit("[opencode.skill_scripts] は redirect_message が要る")

    normal = _static_shell_denies(build_opencode_permissions(common))
    isolated = (
        _static_shell_denies(build_opencode_sandbox_permissions(common))
        if common.get("opencode", {}).get("sandbox")
        else normal
    )
    merged: dict[tuple[bool, tuple[str, ...]], list[str]] = {}
    for head in heads:
        resource = f"{head} *>*"
        if resource not in normal:
            continue
        exempt = tuple(_deny_guide_exempt_agents(common, head))
        merged.setdefault((resource not in isolated, exempt), []).append(head)

    out: list[dict[str, Any]] = []
    for (not_isolated, exempt), group in merged.items():
        names = "|".join(_regex_escape(h) for h in group)
        entry: dict[str, Any] = {
            "pattern": f"{DENY_GUIDE_SEGMENT_START}(?:{names}){SKILL_REDIRECT_TAIL}",
            "unless": DENY_GUIDE_UNLESS,
            "message": message,
        }
        if not_isolated:
            entry["not_isolated"] = True
        if exempt:
            entry["except_agents"] = list(exempt)
        out.append(entry)
    return out


def _bash_deny_guide_rules(common: dict[str, Any]) -> list[dict[str, Any]]:
    """``[bash.deny_guide]`` から ``rules.json`` の ``deny_guide`` (前段の停止規則) を作る。

    全 deny が分類のどれか 1 つに属さないと生成を止める。通常版と隔離版の最終の静的 deny から
    決め、隔離版で捨てた項目に ``not_isolated``、覆しうるエージェントに ``except_agents`` を付ける。
    see docs/spec/agent-command-policy.md#opencode-の-deny-の説明前段停止
    """
    bash = common.get("bash", {})
    cfg = bash.get("deny_guide")
    if not cfg:
        return []
    deny = [str(c) for c in bash.get("deny", [])]
    unknown_keys = set(cfg) - {"user_message", "user_only", "elsewhere", "alternative"}
    if unknown_keys:
        raise SystemExit(f"[bash.deny_guide] の未知のキー: {sorted(unknown_keys)}")

    groups: list[tuple[str, list[str]]] = []
    user_only = [str(c) for c in cfg.get("user_only") or []]
    if user_only:
        message = str(cfg.get("user_message") or "")
        if not message:
            raise SystemExit("[bash.deny_guide] は user_only に user_message が要る")
        groups.append((message, user_only))
    for entry in cfg.get("alternative") or []:
        commands = [str(c) for c in entry.get("commands") or []]
        message = str(entry.get("message") or "")
        if not commands or not message:
            raise SystemExit(
                f"[[bash.deny_guide.alternative]] は commands と message が要る: {entry}"
            )
        groups.append((message, commands))
    elsewhere = [str(c) for c in cfg.get("elsewhere") or []]

    classified = [c for _, commands in groups for c in commands] + elsewhere
    dup = sorted({c for c in classified if classified.count(c) > 1})
    if dup:
        raise SystemExit(f"[bash.deny_guide] で複数の分類に属する項目: {dup}")
    missing = [c for c in deny if c not in classified]
    if missing:
        raise SystemExit(f"[bash] deny に対して [bash.deny_guide] の分類が無い項目: {missing}")
    extra = [c for c in classified if c not in deny]
    if extra:
        raise SystemExit(f"[bash.deny_guide] にあって [bash] deny に無い項目: {extra}")

    # elsewhere は個別の early 規則が実際に止めること (二重にしない代わりに、外れたら気付く)
    early = [r for r in opencode_guide_rules(common) if r.get("early")]
    for c in elsewhere:
        probe = f"{c} x"
        if not any(
            re.search(r["pattern"], probe)
            and not (r.get("unless") and re.search(r["unless"], probe))
            for r in early
        ):
            raise SystemExit(
                f"[bash.deny_guide] elsewhere の {c!r} を止める early の guide 規則が無い"
            )

    normal = _static_shell_denies(build_opencode_permissions(common))
    isolated = (
        _static_shell_denies(build_opencode_sandbox_permissions(common))
        if common.get("opencode", {}).get("sandbox")
        else normal
    )

    # 同じ説明・同じ印の項目を 1 つの規則にまとめる (宣言の順を保つ)
    merged: dict[tuple[str, bool, tuple[str, ...]], list[str]] = {}
    for message, commands in groups:
        for command in commands:
            resource = f"{command} *"
            if resource not in normal:
                continue
            exempt = tuple(_deny_guide_exempt_agents(common, command))
            merged.setdefault((message, resource not in isolated, exempt), []).append(command)

    out: list[dict[str, Any]] = []
    for (message, not_isolated, exempt), commands in merged.items():
        names = "|".join(" ".join(_regex_escape(t) for t in c.split(" ")) for c in commands)
        entry: dict[str, Any] = {
            "pattern": f"{DENY_GUIDE_SEGMENT_START}(?:{names}){DENY_GUIDE_COMMAND_END}",
            "unless": DENY_GUIDE_UNLESS,
            "message": message,
        }
        if not_isolated:
            entry["not_isolated"] = True
        if exempt:
            entry["except_agents"] = list(exempt)
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
    out: dict[str, Any] = {
        "min_command_length": int(cfg.get("min_command_length", 60)),
        "duration_ms": int(cfg.get("duration_ms", 20000)),
        "timeout_ms": int(cfg.get("timeout_ms", 5000)),
        "models": models,
    }
    # git commit はモデルを呼ばず、コマンドから抜き出した件名と本文を出す。
    # see docs/spec/agent-config-generation.md#git-commit-の件名と本文
    commit = cfg.get("commit") or {}
    if commit.get("enabled", True):
        out["commit"] = {
            "line_width": int(commit.get("line_width", 72)),
            "max_lines": int(commit.get("max_lines", 8)),
        }
    return out


def opencode_bypass_agents(common: dict[str, Any]) -> list[str]:
    """bypass 扱いのエージェント名 (``bypass = true`` の印があるもの)。

    通常と同じ permission のまま、guide-plugin が ``ask`` を ``allow`` に引き上げる対象。
    ``permission.evaluate`` に ``agent`` が載ることを実測したので名前で見る。
    see docs/adr/0014-bypass-as-ask-upgrade.md
    """
    return sorted(n for n, a in _declared_agents(common).items() if _is_bypass(a))


def _declared_agents(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """V1 の ``[opencode.agent]`` と V2 の ``[opencode.agents]`` を合わせた宣言。"""
    opencode = common.get("opencode", {})
    return {**(opencode.get("agents") or {}), **(opencode.get("agent") or {})}


def _is_bypass(agent: dict[str, Any]) -> bool:
    """``bypass = true`` の印があるか (``true`` 以外の値は印と認めない)。"""
    return agent.get("bypass") is True


def opencode_guarded_subagents(common: dict[str, Any]) -> list[str]:
    """bypass からだけ起動させる子エージェント名 (bypass の印があり、子として使えるもの)。

    ``opencode.json`` の全体の deny と ``rules.json`` の ``guarded_subagents`` の元。
    see docs/spec/agent-config-generation.md#bypass-から呼べる子エージェント
    """
    return [
        name
        for name, agent in sorted(_declared_agents(common).items())
        if _is_bypass(agent) and agent.get("mode") in ("subagent", "all")
    ]


def opencode_subagent_guards(common: dict[str, Any]) -> list[dict[str, str]]:
    """bypass の子エージェントを、bypass 以外から呼ばせない。

    全体の permission で起動を deny する。エージェントごとの規則は全体の規則の
    後ろに付き、最後に一致した規則が勝つので、``task`` の ``*`` を allow にした
    エージェント (``bypass``) の中でだけこの deny が上書きされる (実測)。
    see docs/spec/agent-config-generation.md#bypass-から呼べる子エージェント
    """
    return [
        {"action": "subagent", "resource": name, "effect": "deny"}
        for name in opencode_guarded_subagents(common)
    ]


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
    展開した形は ``/`` 区切りに揃える。Windows では ``C:\\Users\\x/.ssh`` と
    混ざるが、plugin は照合の前に ``\\`` を ``/`` へ揃えるため。
    """
    if not glob.startswith("~/"):
        return [glob]
    return [glob, expand_user(glob).replace("\\", "/")]


def opencode_read_deny_regexes(common: dict[str, Any]) -> list[str]:
    """``grep`` / ``glob`` の結果を濾すためのパターン。

    ``read`` の deny glob と同じものを使う。両ツールは permission の
    ``read`` deny を迂回するので、保護は plugin 側で自作するしかない。
    see docs/research/opencode/permission/gaps.md
    """
    globs = common.get("file", {}).get("read_deny_globs") or []
    return [glob_to_regex(v) for g in globs for v in _home_variants(str(g))]


def opencode_read_deny_except_rules(common: dict[str, Any]) -> list[dict[str, list[str]]]:
    """``[[file.deny_exceptions]]`` の正規表現版 (``rules.json`` の ``read_deny_except``)。

    ``deny`` は ``read_deny`` と同じ変換の結果なので、plugin は文字列の一致で
    「例外の対の deny」を見分ける。例外は対の deny にだけ効き、ほかの deny に当たれば伏せる。
    """
    read = {str(g) for g in common.get("file", {}).get("read_deny_globs") or []}
    return [
        {
            "deny": [glob_to_regex(v) for v in _home_variants(e["deny"])],
            "except": [glob_to_regex(v) for g in e["except"] for v in _home_variants(g)],
        }
        for e in file_deny_exceptions(common)
        if e["deny"] in read
    ]


def opencode_deny_path_regexes(common: dict[str, Any]) -> list[str]:
    """コマンド文字列に載ったパスへ当てるパターン (出力全体を伏せる判定)。

    ``read`` の deny glob から作るが、``**/*secret*`` のような**部分一致**は
    除く。``docs/secret-handling.md`` のような正当なパスまで当たり、
    無関係な出力を丸ごと伏せてしまうため。
    末尾の ``/**`` を落としてから最終要素で判定する
    (``**/.ssh/**`` の最終要素は ``**`` になり、素の判定では落ちる)。
    """
    out: list[str] = []
    for g in common.get("file", {}).get("read_deny_globs") or []:
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


def provider_domains(common: dict[str, Any], names: Any) -> list[str]:
    """``[provider.*]`` の ``network_allow`` を名前で引いて合算する。

    ★未知の名前は **例外**にする。``.get(name, {})`` で黙って空を返すと、
    綴り間違いが「境界内からモデルへ到達できない」という形でしか現れない。
    そのときの症状は proxy が CONNECT を 403 で落とすだけの「応答が来ない」で、
    原因に辿り着けない。
    """
    if not names:
        return []
    providers = common.get("provider") or {}
    out: list[str] = []
    for name in names:
        entry = providers.get(name)
        if entry is None:
            known = ", ".join(sorted(providers)) or "(なし)"
            raise ValueError(
                f"未知の provider: {name!r}。[provider.{name}] が無い。定義済み: {known}"
            )
        out += list(entry.get("network_allow", []))
    return out


def opencode_sandbox(common: dict[str, Any]) -> dict[str, Any] | None:
    """OpenCode を丸ごと囲う境界の**素材**。

    ランチャー (``ocs``) が起動ディレクトリと合わせて Fence の設定を組み立てる。
    ここでは共通の許可リストだけを出す。

    **Fence の有無に関係なく返す。** 実体が無いときはランチャーが起動を断る。
    see docs/spec/opencode-sandbox.md#境界の中身
    """
    cfg = common.get("opencode", {}).get("sandbox")
    if not cfg or not cfg.get("enabled"):
        return None
    runtime = expand_user(str(cfg.get("runtime_path", "")))
    if not runtime:
        return None

    sandbox_cfg = common.get("sandbox", {})
    web = common.get("web", {})

    def paths(key: str) -> list[str]:
        return _uniq([expand_user(str(p)) for p in cfg.get(key) or []])

    # 共有の秘密の一覧 ([sandbox] deny) も隠す。glob は Fence へ渡さない。
    shared_secrets = [expand_user(str(p)) for p in sandbox_cfg.get("deny", []) if "*" not in str(p)]
    out: dict[str, Any] = {
        "runtime_path": runtime,
        "base": {
            "read": paths("read"),
            "work_read": paths("work_read"),
            "write": paths("write"),
            "deny_read": _uniq([*paths("deny_read"), *shared_secrets]),
            "unsafe_workspace": paths("unsafe_workspace"),
            "control_dirs": paths("control_dirs"),
            # 相対のまま渡す。ランチャーが起動ディレクトリとリポジトリの根に合わせる。
            "protected": [str(p) for p in cfg.get("protected") or []],
            "network": {
                "allowedDomains": _uniq(
                    list(web.get("allow_domains", []))
                    + list(sandbox_cfg.get("shell_network_allow", []))
                    + list(cfg.get("network_allow", []))
                    + provider_domains(common, cfg.get("providers", []))
                ),
                "deniedDomains": _uniq(list(web.get("deny_domains", []))),
                "allowLocalBinding": False,
            },
        },
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
    # ocs は cli.json を渡さないので TUI 側は読まれない (tui=False)。
    if opencode_guide_server_needed(common, tui=False):
        out["plugins"] = [opencode_guide_plugin_path()]
    # 隔離版でも圧縮は起きる。checkpoint plugin を載せないと、境界の内側でだけ
    # 文脈が失われる。読むのは plugin 本体とスキルの CLI だけで、書き込みは
    # ワークスペース内の .tmp/ に閉じる。
    out.setdefault("plugins", []).append(opencode_checkpoint_plugin_path())
    policies = opencode_sandbox_policies(common)
    if policies:
        out["policies"] = policies
    out.update(opencode_sandbox_agents(common, cfg.get("providers") or []))
    prompt = cfg.get("system_prompt")
    if prompt:
        out["system_prompt"] = str(prompt).strip()
    preference = cfg.get("model_preference") or []
    if preference:
        out["model_preference"] = [
            {"provider": str(p.get("provider", "")), "model": str(p.get("model", ""))}
            for p in preference
            if p.get("provider") and p.get("model")
        ]
    return out


def opencode_sandbox_agents(common: dict[str, Any], reachable: list[str]) -> dict[str, Any]:
    """隔離版のエージェント・コマンド。通常版の ``opencode.json`` と同じ関数で作る。

    **通常版の ``opencode.json`` からは引き継がない**（空の既存に対して組む）。
    モデルの割り当てと接続設定は、この PC のプロバイダが境界の内から届くときだけ出す。
    see docs/spec/opencode-sandbox.md#エージェントとコマンド
    """
    out: dict[str, Any] = {}
    agent = merge_opencode_agents({}, common)
    if agent:
        out["agent"] = agent
    agents = merge_opencode_v2_agents({}, common)
    models = opencode_models(common)
    if models and models["provider"] in reachable:
        agents = merge_opencode_agent_models(agents, models)
        providers = merge_opencode_providers({}, common, models)
        if providers:
            out["providers"] = providers
    if agents:
        out["agents"] = agents
    commands = merge_opencode_commands({}, common)
    if commands:
        out["commands"] = commands
    return out


AGENT_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def agent_env(common: dict[str, Any]) -> dict[str, str]:
    """``[agent_env]``: AI CLI のシェルへ未設定のときだけ入れる環境変数。

    ``rules.json`` の ``agent_env`` になる。
    キーは環境変数名、値は文字列 (空文字可)。不正なら生成を止める。
    """
    table = common.get("agent_env", {})
    if not isinstance(table, dict):
        raise SystemExit("[agent_env] は表でなければならない")
    for key, value in table.items():
        if not AGENT_ENV_NAME.fullmatch(key):
            raise SystemExit(f"[agent_env] のキーが環境変数名として不正: {key!r}")
        if not isinstance(value, str) or "\0" in value:
            raise SystemExit(f"[agent_env] の値は NUL を含まない文字列: {key} = {value!r}")
    return dict(table)


def build_opencode_guide(_existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "agent_env": agent_env(common),
        "guide": opencode_guide_rules(common),
        "deny_guide": opencode_deny_guide_rules(common),
        "deny_guide_agents": opencode_deny_guide_agents(common),
        "bypass_agents": opencode_bypass_agents(common),
        "guarded_subagents": opencode_guarded_subagents(common),
        "read_deny": opencode_read_deny_regexes(common),
        "read_deny_except": opencode_read_deny_except_rules(common),
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

# checkpoint plugin の置き場。命名の制約は guide-plugin と同じ。
# 圧縮の直前に機械節を書き、直後に checkpoint をシステム側へ戻す。
# see docs/change/closed/0001-compaction-context-handover.md
OPENCODE_CHECKPOINT_PLUGIN = "~/.config/opencode/checkpoint-plugin"


# skill の置き場。**明示しないと読まれない。**
# 公式ドキュメントは ~/.config/opencode/skills を Global の探索先として挙げるが、
# v2.0.14 はここを走査しない (実測: 監視対象は ~/.opencode/skills で、
# ~/.config/opencode/skills に置いた skill は登録されない)。未文書の
# ~/.opencode/skills へ移すより、文書化されている `skills` 設定で名指しする。
# see docs/change/closed/0001-compaction-context-handover.md 「skill が読まれない」
OPENCODE_SKILLS = "~/.config/opencode/skills"


def opencode_checkpoint_plugin_path() -> str:
    return os.path.expanduser(OPENCODE_CHECKPOINT_PLUGIN)


def opencode_skills_path() -> str:
    return os.path.expanduser(OPENCODE_SKILLS)


def merge_opencode_skills(existing_skills: Any) -> list[Any]:
    """``skills`` を更新する (宣言外のエントリは残す)。"""
    path = opencode_skills_path()
    known = (path, OPENCODE_SKILLS)
    out = [s for s in (existing_skills or []) if s not in known]
    out.append(path)
    return out


def opencode_guide_plugin_path() -> str:
    return os.path.expanduser(OPENCODE_GUIDE_PLUGIN)


def opencode_guide_server_needed(common: dict[str, Any], *, tui: bool) -> bool:
    """サーバ側の guide plugin (``index.js``) を読み込むか。

    ``index.js`` の役割 (誘導・``grep`` / ``glob`` の結果フィルタ・伏字化・
    子エージェントの起動元の検査・説明の生成) が 1 つでも有効なら要る。説明は
    TUI 側の toast でしか見えないので、``tui`` が偽 (TUI plugin が読まれない
    隔離版) なら数えない。
    see docs/spec/agent-config-generation.md#plugin-層-guide-plugin
    """
    return bool(
        opencode_guide_rules(common)
        or opencode_deny_guide_rules(common)
        or opencode_read_deny_regexes(common)
        or opencode_redact(common)
        or opencode_guarded_subagents(common)
        or (tui and opencode_guide_tui_needed(common))
    )


def opencode_guide_tui_needed(common: dict[str, Any]) -> bool:
    """TUI 側の guide plugin (``tui.ts``) を読み込むか。役割は説明の toast だけ。"""
    return opencode_ask_description(common) is not None


def merge_opencode_plugins(existing_plugins: Any, common: dict[str, Any]) -> list[Any]:
    """``plugins`` を更新する (宣言外のエントリは残す)。"""
    path = opencode_guide_plugin_path()
    checkpoint = opencode_checkpoint_plugin_path()
    known = (path, OPENCODE_GUIDE_PLUGIN, checkpoint, OPENCODE_CHECKPOINT_PLUGIN)
    out = [p for p in (existing_plugins or []) if p not in known]
    if opencode_guide_server_needed(common, tui=True):
        out.append(path)
    # checkpoint plugin は常に読み込む。common.toml に切り替えは置かない
    # (圧縮は設定と無関係に起きるため)。
    out.append(checkpoint)
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
        # bypass は生成側の印。OpenCode の設定には出さない
        entry.update({k: v for k, v in agent.items() if k != "bypass"})
        out[name] = entry
    return out


# [provider.*] のうち OpenCode の ``providers.<id>.settings`` へ写すキー。
OPENCODE_PROVIDER_SETTINGS = ("profile", "region")


def opencode_models(common: dict[str, Any]) -> dict[str, Any] | None:
    """``[opencode.model]`` を、この PC のプロバイダでのモデル参照へ解決する。

    階層名 (``default`` / ``worker`` など) を ``provider/model[#variant]`` に直す。
    未知のプロバイダ・階層は ``apply`` を止める。黙って落とすと、存在しない
    モデルを指したまま「応答が来ない」形でしか現れない。
    see docs/spec/agent-config-generation.md#モデルの割り当て
    """
    cfg = common.get("opencode", {}).get("model")
    if not cfg:
        return None
    provider = str(cfg.get("provider", ""))
    all_tiers = cfg.get("tier") or {}
    tiers = all_tiers.get(provider)
    if not tiers:
        known = ", ".join(sorted(all_tiers)) or "(なし)"
        raise SystemExit(f"opencode.model.tier.{provider} が無い。定義済み: {known}")

    def ref(tier: str) -> str:
        if tier not in tiers:
            raise SystemExit(
                f"opencode.model.tier.{provider} に {tier!r} が無い。定義済み: "
                + ", ".join(sorted(tiers))
            )
        return f"{provider}/{tiers[tier]}"

    default = ref("default")
    if "#" in default:
        # see docs/research/opencode/agent-models.md 記録 E2
        raise SystemExit(f"opencode.model の default に #variant は付けられない: {default}")
    assigned = {str(a): ref(str(t)) for a, t in (cfg.get("agents") or {}).items()}
    # V1 の agent と V2 の agents に同じ ID を書いたときの結合順は未確認
    both = sorted(set(assigned) & set(common.get("opencode", {}).get("agent") or {}))
    if both:
        raise SystemExit(
            "opencode.model.agents に [opencode.agent] のエージェントは書けない: " + ", ".join(both)
        )
    return {
        "provider": provider,
        "model": default,
        "agents": assigned,
        # 割り当てを外したときに消してよい値 (どのプロバイダの階層でも)
        "managed": {f"{p}/{m}" for p, ts in all_tiers.items() for m in ts.values()},
    }


# [opencode.agents.<id>] に書けるキー。model は [opencode.model.agents] が持つ。
# system_from / bypass は生成時だけのキー (system_from は別のエージェントの system を写し、
# bypass は guide-plugin の ask→allow の対象にする。opencode.json には出さない)。
OPENCODE_AGENT_KEYS = frozenset(
    {
        "description",
        "mode",
        "system",
        "system_from",
        "bypass",
        "permissions",
        "steps",
        "hidden",
        "color",
        "disabled",
    }
)
OPENCODE_PERMISSION_EFFECTS = frozenset({"allow", "ask", "deny"})


def _expand_home_in_shell_rules(rules: list[dict[str, str]]) -> list[dict[str, str]]:
    """shell の resource に書いた `` ~/`` を、展開した形の規則でも並べる。

    shell の resource は生のコマンド文字列で ``~`` を展開しない。モデルは ``~/`` と
    絶対パスのどちらでも書くので、両方に当てる (スキルのスクリプトの規則と同じ扱い)。
    """
    home = expand_user("~/").replace("\\", "/")
    out: list[dict[str, str]] = []
    for rule in rules:
        out.append(rule)
        resource = str(rule["resource"])
        if rule["action"] == "shell" and " ~/" in resource:
            out.append({**rule, "resource": resource.replace(" ~/", f" {home}")})
    return out


def opencode_v2_agents(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``[opencode.agents]`` (V2 形式のエージェント定義) を検査して返す。

    V1 の ``[opencode.agent]`` と同じ ID は禁止する (両方に書いたときの結合順は未確認)。
    ``model`` はここでは受けない。PC ごとのプロバイダで変わるので階層で割り当てる。
    see docs/spec/agent-config-generation.md#子エージェント
    """
    opencode = common.get("opencode", {})
    declared = opencode.get("agents") or {}
    v1 = set(opencode.get("agent") or {})
    out: dict[str, dict[str, Any]] = {}
    for name, agent in declared.items():
        section = f"opencode.agents.{name}"
        if name in v1:
            raise ValueError(f"[{section}] は [opencode.agent.{name}] と重複している")
        if "model" in agent:
            raise ValueError(
                f"[{section}] に model は書けない。[opencode.model.agents] で階層を割り当てる"
            )
        _reject_unknown(section, set(agent), OPENCODE_AGENT_KEYS)
        if not agent.get("description"):
            raise ValueError(f"[{section}] は description が要る (モデルが起動先を選ぶ手がかり)")
        for rule in agent.get("permissions") or []:
            if set(rule) != {"action", "resource", "effect"}:
                raise ValueError(
                    f"[{section}] の permissions は action / resource / effect だけで書く: {rule}"
                )
            if rule["effect"] not in OPENCODE_PERMISSION_EFFECTS:
                raise ValueError(f"[{section}] の effect が不正: {rule}")
        entry = dict(agent)
        if entry.get("permissions"):
            entry["permissions"] = _expand_home_in_shell_rules(entry["permissions"])
        if "bypass" in entry and not isinstance(entry["bypass"], bool):
            raise ValueError(f"[{section}] の bypass は true / false で書く")
        entry.pop("bypass", None)
        source = entry.pop("system_from", None)
        if source is not None:
            if "system" in entry:
                raise ValueError(f"[{section}] は system と system_from を両方は書けない")
            base = declared.get(source)
            if not base or "system" not in base or "system_from" in base:
                raise ValueError(
                    f"[{section}] の system_from は system を直接持つ"
                    f" [opencode.agents] を指す: {source!r}"
                )
            entry["system"] = base["system"]
        if "system" in entry:
            entry["system"] = str(entry["system"]).strip()
        out[str(name)] = entry
    return out


def merge_opencode_v2_agents(existing: Any, common: dict[str, Any]) -> dict[str, Any]:
    """V2 の ``agents`` に、宣言したエージェントの定義を書く。

    宣言したキーだけを差し替え、他のエージェント・キー (``model`` など) は残す。
    """
    out = {
        name: dict(entry)
        for name, entry in (existing if isinstance(existing, dict) else {}).items()
        if isinstance(entry, dict)
    }
    for name, agent in opencode_v2_agents(common).items():
        out[name] = {**out.get(name, {}), **agent}
    return out


# [opencode.commands.<name>] に書けるキー。model は PC ごとに変わるので受けない。
OPENCODE_COMMAND_KEYS = frozenset({"template", "description", "agent", "subagent"})
# template の中でシェルとして実行される記法 (権限の確認を通らない)
OPENCODE_COMMAND_SHELL_BLOCK = re.compile(r"!`")


def opencode_commands(common: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``[opencode.commands]`` を検査して返す。

    ``!`` + バッククォートはコマンドの展開時にシェルとして実行され、権限の確認を
    通らない (公式)。引数を混ぜると任意コードの入口になるので、書かせない。
    see docs/spec/agent-config-generation.md#並列作業fleet
    """
    out: dict[str, dict[str, Any]] = {}
    for name, command in (common.get("opencode", {}).get("commands") or {}).items():
        section = f"opencode.commands.{name}"
        _reject_unknown(section, set(command), OPENCODE_COMMAND_KEYS)
        template = str(command.get("template") or "").strip()
        if not template:
            raise ValueError(f"[{section}] は template が要る")
        if OPENCODE_COMMAND_SHELL_BLOCK.search(template):
            raise ValueError(f"[{section}] の template にシェルの埋め込み (!`...`) は書けない")
        if "subagent" in command and not isinstance(command["subagent"], bool):
            raise ValueError(f"[{section}] の subagent は true / false で書く")
        out[str(name)] = {**command, "template": template}
    return out


def merge_opencode_commands(existing: Any, common: dict[str, Any]) -> dict[str, Any]:
    """``commands`` に宣言したコマンドを書く (他のコマンド・キーは残す)。"""
    out = {
        name: dict(entry)
        for name, entry in (existing if isinstance(existing, dict) else {}).items()
        if isinstance(entry, dict)
    }
    for name, command in opencode_commands(common).items():
        out[name] = {**out.get(name, {}), **command}
    return out


def merge_opencode_agent_models(existing: Any, models: dict[str, Any]) -> dict[str, Any]:
    """V2 の ``agents.<id>.model`` を割り当てどおりにする。

    V1 の ``agent`` キーへは書かない。``#variant`` 付きの指定が黙って無視され、
    親のモデルで動く (実測)。
    割り当てから外したエージェントは、値が階層のモデルのときだけ消す
    (手で書いた別のモデルは残す)。空になったエントリは消す。
    see docs/spec/agent-config-generation.md#モデルの割り当て
    """
    source = existing if isinstance(existing, dict) else {}
    out = {name: dict(entry) for name, entry in source.items() if isinstance(entry, dict)}
    for name, entry in out.items():
        if name not in models["agents"] and entry.get("model") in models["managed"]:
            del entry["model"]
    for name, model in models["agents"].items():
        out.setdefault(name, {})["model"] = model
    return {name: entry for name, entry in out.items() if entry}


def merge_opencode_providers(
    existing: Any, common: dict[str, Any], models: dict[str, Any]
) -> dict[str, Any]:
    """この PC のプロバイダの接続設定を ``providers.<id>.settings`` へ書く。

    宣言外のプロバイダ・キーは残す。Bedrock は ``profile`` が無いと有効に
    ならない (region だけでは足りない) ので、``[provider.*]`` から写す。
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    provider = models["provider"]
    declared = (common.get("provider") or {}).get(provider) or {}
    settings = {k: declared[k] for k in OPENCODE_PROVIDER_SETTINGS if k in declared}
    if settings:
        entry = dict(out.get(provider) or {})
        entry["settings"] = {**(entry.get("settings") or {}), **settings}
        out[provider] = entry
    return out


def merge_opencode_provider_policies(existing: Any, models: dict[str, Any]) -> dict[str, Any]:
    """``experimental.policies`` で、この PC のプロバイダ以外を使えなくする。

    policies はグローバル設定がプロジェクト設定に勝つので、リポジトリ側から
    別のプロバイダを有効にされない。``provider.use`` の文だけを差し替え、
    ほかの文と ``experimental`` のほかのキーは残す。後勝ちなので末尾に置く。
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    kept = [
        s
        for s in (out.get("policies") or [])
        if not (isinstance(s, dict) and s.get("action") == "provider.use")
    ]
    out["policies"] = [
        *kept,
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": models["provider"], "effect": "allow"},
    ]
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
    for name, server in mcp_servers(common, "opencode"):
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
        _reject_unknown(f"opencode.keybinds.{command}", set(binding), OPENCODE_KEYBIND_OBJECT_KEYS)
        key = binding.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"{where} はテーブルで書くなら key が要る")
        return binding
    raise ValueError(f"{where} は文字列・リスト・テーブル・false のどれかで書く")


def build_opencode_keybinds(common: dict[str, Any]) -> dict[str, Any] | None:
    """``[opencode.keybinds]`` を検査して ``cli.json`` の ``keybinds`` にする。

    キーバインドは **``cli.json`` 側にしか無い**。``opencode.json`` へ書いても
    読まれないので、誤配置に気づけない。
    未宣言は None、空テーブルは ``{}`` (既存を空で置き換える) と区別する。
    see docs/spec/agent-config-generation.md 「キーバインド」
    """
    keybinds = common.get("opencode", {}).get("keybinds")
    if keybinds is None:
        return None
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
    if keybinds is not None:
        # 宣言したら keybinds テーブルごと common.toml 側の持ち物にする。
        # 1 件消したときに配備先へ残らないようにするため。
        out["keybinds"] = keybinds
    path = opencode_guide_plugin_path()
    plugins = [p for p in (out.get("plugins") or []) if p not in (path, OPENCODE_GUIDE_PLUGIN)]
    if opencode_guide_tui_needed(common):
        plugins.append(path)
    if plugins:
        out["plugins"] = plugins
    else:
        out.pop("plugins", None)
    return out


def merge_opencode_service(existing: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    """``~/.config/opencode/service.json`` (常駐サービスの設定) の ``port`` だけを揃える。

    ``password`` などは OpenCode が書くので触らない。
    see docs/spec/agent-config-generation.md#常駐サービスのポート
    """
    out = dict(existing)
    service = (common.get("opencode") or {}).get("service") or {}
    _reject_unknown("opencode.service", set(service), frozenset({"port"}))
    if "port" in service:
        port = service["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"[opencode.service] port は 1〜65535 の整数にする: {port!r}")
        out["port"] = port
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
    if "websearch" in opencode:
        if opencode["websearch"] is not False:
            raise ValueError("[opencode] websearch は false だけ書ける (検索先の選択は TUI で行う)")
        out["websearch"] = False

    formatter = build_opencode_formatter(common)
    if formatter is not None:
        out["formatter"] = formatter

    out["permissions"] = build_opencode_permissions(common)
    plugins = merge_opencode_plugins(existing.get("plugins"), common)
    if plugins:
        out["plugins"] = plugins
    agent = merge_opencode_agents(existing.get("agent"), common)
    if agent:
        out["agent"] = agent
    agents = merge_opencode_v2_agents(existing.get("agents"), common)
    models = opencode_models(common)
    if models:
        out["model"] = models["model"]
        agents = merge_opencode_agent_models(agents, models)
        providers = merge_opencode_providers(existing.get("providers"), common, models)
        if providers:
            out["providers"] = providers
        else:
            out.pop("providers", None)
        out["experimental"] = merge_opencode_provider_policies(existing.get("experimental"), models)
    if agents:
        out["agents"] = agents
    else:
        out.pop("agents", None)
    commands = merge_opencode_commands(existing.get("commands"), common)
    if commands:
        out["commands"] = commands
    else:
        out.pop("commands", None)
    out["skills"] = merge_opencode_skills(existing.get("skills"))
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
    "opencode-service": merge_opencode_service,
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
# また ~/.config/agents は [sandbox] claude_write_deny に入っており
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


def _merge_local_sandbox(merged: dict[str, Any], local_sandbox: dict[str, Any]) -> None:
    """local.toml の ``[sandbox]`` を追記する (既存エントリは消さない)。"""
    ignored = sorted(set(local_sandbox) - set(LOCAL_SANDBOX_KEYS))
    if ignored:
        print(
            "warning: local.toml の [sandbox] で追記できないキーを無視しました: "
            + ", ".join(ignored)
            + " (使えるキー: "
            + ", ".join(LOCAL_SANDBOX_KEYS)
            + ")",
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
                "キーを無視しました: "
                + ", ".join(ignored)
                + " (使えるキー: "
                + ", ".join(LOCAL_LOCATION_KEYS)
                + ")",
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


def apply_local_overlay(common: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
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
