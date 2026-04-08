#!/usr/bin/env python3
"""
Claude Code PreToolUse hook: Bash コマンドの安全性チェック

危険なパターンを検出してブロックする。
exit 0: 許可
exit 2: ブロック（Claude にメッセージが表示される）
"""
from __future__ import annotations

import json
import re
import sys

# ─── センシティブパスのパターン ──────────────────────────────────────
SENSITIVE_PATH_PATTERNS = [
    r"\.env(?!\w)",        # .env（.env.example は除外）
    r"\.ssh[/\\]",
    r"id_rsa",
    r"id_ed25519",
    r"id_ecdsa",
    r"['\"/\s]secret",
    r"['\"/\s]password",
    r"['\"/\s]credential",
    r"['\"/\s]token",
    r"['\"/\s]api[_-]?key",
    r"\.pem$",
    r"\.key$",
    r"/etc/shadow",
    r"/etc/passwd",
    r"~/.netrc",
    r"\.gnupg[/\\]",
]

# ─── ファイル内容を読むコマンド ──────────────────────────────────────
FILE_READ_COMMANDS = [
    "grep", "cat", "head", "tail",
    "sed", "awk", "less", "more",
    "strings", "xxd", "hexdump",
    "base64", "od",
]

# ─── 環境変数を全件露出するコマンド（引数なし） ─────────────────────
ENV_EXPOSURE_COMMANDS = [
    r"^\s*env\s*$",
    r"^\s*printenv\s*$",
    r"^\s*export\s*$",
    r"^\s*set\s*$",
]

# ─── アーカイブコマンド ───────────────────────────────────────────────
ARCHIVE_COMMANDS = ["tar", "zip", "gzip", "bzip2", "7z", "xz"]

# ─── curl/wget でのファイル送信パターン ──────────────────────────────
CURL_FILE_SEND_PATTERN = re.compile(
    r"\b(curl|wget)\b.*(?:-d\s*@|-F\s*['\"]?[^=]+=@|--data-binary\s*@)",
    re.IGNORECASE,
)


def is_sensitive_path(text: str) -> str | None:
    """センシティブなパスパターンにマッチする最初のパターンを返す"""
    for pattern in SENSITIVE_PATH_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def check_file_read(cmd: str) -> str | None:
    """ファイル読み込みコマンドがセンシティブパスを対象にしていないか"""
    for command in FILE_READ_COMMANDS:
        if re.search(rf"\b{re.escape(command)}\b", cmd):
            matched = is_sensitive_path(cmd)
            if matched:
                return (
                    f"`{command}` がセンシティブなパスを対象にしています "
                    f"(パターン: {matched})"
                )
    return None


def check_env_exposure(cmd: str) -> str | None:
    """環境変数を全件露出するコマンドを検出"""
    for pattern in ENV_EXPOSURE_COMMANDS:
        if re.search(pattern, cmd):
            return (
                f"環境変数を全件出力するコマンドは許可されていません: `{cmd.strip()}`\n"
                "特定の変数を確認する場合は `echo $VAR_NAME` を使用してください。"
            )
    return None


def check_archive(cmd: str) -> str | None:
    """アーカイブコマンドがセンシティブパスを含んでいないか"""
    for command in ARCHIVE_COMMANDS:
        if re.search(rf"\b{re.escape(command)}\b", cmd):
            matched = is_sensitive_path(cmd)
            if matched:
                return (
                    f"`{command}` でセンシティブなパスをアーカイブしようとしています "
                    f"(パターン: {matched})"
                )
    return None


def check_curl_file_send(cmd: str) -> str | None:
    """curl/wget でセンシティブファイルの内容を送信しようとしていないか"""
    if CURL_FILE_SEND_PATTERN.search(cmd):
        matched = is_sensitive_path(cmd)
        if matched:
            return (
                f"curl/wget でセンシティブなファイルを送信しようとしています "
                f"(パターン: {matched})"
            )
    return None


def check_xargs_pipe(cmd: str) -> str | None:
    """find | xargs cat/grep のような組み合わせを検出"""
    if "xargs" in cmd:
        for read_cmd in FILE_READ_COMMANDS:
            if re.search(rf"\bxargs\b.*\b{re.escape(read_cmd)}\b", cmd):
                matched = is_sensitive_path(cmd)
                if matched:
                    return (
                        f"xargs + `{read_cmd}` でセンシティブなパスを読み込もうとしています "
                        f"(パターン: {matched})"
                    )
    return None


def _pip_suggestion(cmd: str) -> str:
    """pip コマンドに対応する uv/uvx の代替案を返す"""
    if re.search(r"\binstall\b", cmd):
        return "代替: `uv add <package>` または `uvx <package>`"
    if re.search(r"\buninstall\b", cmd):
        return "代替: `uv remove <package>`"
    if re.search(r"\blist\b", cmd):
        return "代替: `uv pip list`"
    if re.search(r"\bshow\b", cmd):
        return "代替: `uv pip show <package>`"
    if re.search(r"\bfreeze\b", cmd):
        return "代替: `uv pip freeze`"
    return "代替: `uv <subcommand>` または `uvx <tool>`"


def check_pip_redirect(cmd: str) -> str | None:
    """pip / python -m pip の直接使用を uv/uvx にリダイレクト"""
    # 直接 pip コマンド
    if re.match(r"\s*pip\b", cmd):
        suggestion = _pip_suggestion(cmd)
        return (
            "pip の直接使用は禁止されています。uv / uvx を使用してください。\n"
            f"{suggestion}"
        )
    # python -m pip
    if re.search(r"\bpython\b.*\s-m\s+pip\b", cmd):
        suggestion = _pip_suggestion(cmd)
        return (
            "`python -m pip` は禁止されています。uv / uvx を使用してください。\n"
            f"{suggestion}"
        )
    return None


CHECKS = [
    check_env_exposure,    # 引数なし環境変数露出は問答無用でブロック
    check_pip_redirect,    # pip → uv/uvx へのリダイレクト
    check_file_read,
    check_archive,
    check_curl_file_send,
    check_xargs_pipe,
]


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # 解析失敗時はブロックしない

    tool_name = data.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    cmd: str = data.get("tool_input", {}).get("command", "")
    if not cmd:
        sys.exit(0)

    for check in CHECKS:
        reason = check(cmd)
        if reason:
            print(f"[hook blocked] {reason}", file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
