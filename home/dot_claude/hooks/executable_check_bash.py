#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: Bash コマンドの安全性チェック

危険なパターンを検出して deny (拒否) または ask (ユーザー承認を要求) を返す。

  - deny: 承認の余地なく拒否する。センシティブ情報の露出や壊滅的な削除など
  - ask : エージェントが提案し、ユーザーが承認すればそのまま実行される。
          ファイル削除のような「危険だが承認すれば妥当」な操作に使う

出力規約は ``agent_compat.emit_pretool_deny`` / ``emit_pretool_ask`` に委譲する
(両ツール対応)。

注意: Claude Code では ``permissions.deny`` が hook の判定より優先される。
ask を返したいコマンドを common.toml の [bash.deny] に書くとプロンプトすら
出ないので、[bash.critical_ask] 側に書くこと。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_ask,
    emit_pretool_deny,
    get_command,
    normalize_tool_kind,
    read_input,
)

# ~/.config/agents/ (chezmoi 管理) にある critical_deny を import
# AGENTS_CONFIG_DIR で差し替え可能 (テスト・コンテナから repo の実体を指すため)
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
try:
    import critical_deny as _critical_deny  # noqa: E402
except ImportError:  # pragma: no cover
    _critical_deny = None  # type: ignore[assignment]

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


def check_git_c_dangerous(cmd: str) -> str | None:
    """`git -C <dir>` 経由で deny 対象のサブコマンドを実行しようとしていないか"""
    # git -C <path> [options] <subcommand> の形を検出
    if not re.search(r"\bgit\b\s+-C\b", cmd):
        return None
    dangerous = ("push", "reset", "rebase", "config")
    for sub in dangerous:
        if re.search(rf"\bgit\b.*\s-C\s.*\b{sub}\b", cmd, re.IGNORECASE):
            return (
                f"`git -C` で禁止されたサブコマンド `{sub}` の実行を検出しました。\n"
                f"このコマンドはセキュリティポリシーによりブロックされています。"
            )
    return None


_FIND_DANGEROUS_EXEC_RE = re.compile(
    r"\bfind\b.+?"
    r"(?:"
    r"-exec\s+(?:rm|unlink|shred|rmdir)\b"  # -exec rm/unlink/shred/rmdir
    r"|-delete\b"                            # -delete フラグ
    r")",
    re.IGNORECASE | re.DOTALL,
)


def check_find_dangerous(cmd: str) -> str | None:
    """`find -exec rm` や `find -delete` でファイルを削除しようとしていないか"""
    if not re.search(r"\bfind\b", cmd):
        return None
    if _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return (
            "`find` コマンドによるファイル削除操作（-exec rm / -delete 等）です。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "削除対象を確認して問題なければ承認してください。"
        )
    return None


_PIP_BIN_RE = re.compile(r"^(?:/\S*/)?pip[0-9.]*$")
_PYTHON_BIN_RE = re.compile(r"^(?:/\S*/)?python[0-9.]*$")


def check_pip_redirect(cmd: str) -> str | None:
    """pip / python -m pip の直接使用を uv/uvx にリダイレクトする。

    critical_deny と同じ normalize を通してから各セグメントの先頭トークンを見るので、
    以下の既知の抜け道をすべて塞ぐ:

      * ``cd foo && pip install x``  (生文字列の先頭アンカーだと素通りしていた)
      * ``pip3 install x``           (``pip\\b`` が ``pip3`` に一致しなかった)
      * ``python3 -m pip install x`` (``\\bpython\\b`` が ``python3`` に一致しなかった)
      * ``/usr/bin/pip install x``   (絶対パス指定)
    """
    segments = (
        _critical_deny.normalize(cmd) if _critical_deny is not None else [cmd]
    )
    for segment in segments:
        tokens = segment.split()
        if not tokens:
            continue
        head = tokens[0]
        if _PIP_BIN_RE.match(head):
            return (
                "pip の直接使用は禁止されています。uv / uvx を使用してください。\n"
                f"{_pip_suggestion(segment)}"
            )
        if _PYTHON_BIN_RE.match(head):
            for i, token in enumerate(tokens[1:-1], start=1):
                if token == "-m" and _PIP_BIN_RE.match(tokens[i + 1]):
                    return (
                        f"`{head} -m pip` は禁止されています。uv / uvx を使用してください。\n"
                        f"{_pip_suggestion(segment)}"
                    )
    return None


def check_critical_deny(cmd: str) -> str | None:
    """common.toml の bash.critical_deny に該当すれば block する.

    Claude Code permission リストの既知バグ (cd && bypass, git -C bypass,
    compound 命令の個別評価欠如) に対する最終防波堤。shell command を
    normalize (cd, git -C, compound 分割) してから pattern match する。
    """
    if _critical_deny is None:
        return None
    patterns = _critical_deny.load_critical_deny()
    if not patterns:
        return None
    matched = _critical_deny.find_critical_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は critical_deny パターンに一致するためブロックされました。\n"
            "このコマンドは common.toml の [bash.critical_deny] で禁止されています。"
        )
    return None


def check_critical_ask(cmd: str) -> str | None:
    """common.toml の bash.critical_ask に該当すればユーザー承認を要求する.

    deny と違い、ユーザーが承認すればそのまま実行される。
    critical_deny と同じ normalize / 照合を通す。
    """
    if _critical_deny is None:
        return None
    patterns = _critical_deny.load_critical_ask()
    if not patterns:
        return None
    matched = _critical_deny.find_critical_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は承認が必要な操作です (common.toml の [bash.critical_ask])。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "内容を確認して問題なければ承認してください。"
        )
    return None


# ─── rm の壊滅的ターゲット (承認の余地なく deny) ──────────────────────
# critical_ask で `rm -rf` を承認可能にする代わりに、取り返しのつかない
# ターゲットだけはここで hard-deny する。
# cwd 配下 (`.` / `./*` / `*`) は critical_ask 側に任せる (プロジェクト内は
# ユーザーが承認して消せるべきなので、ここでは落とさない)。
_CATASTROPHIC_DIRS = {
    "/",
    "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64", "/opt",
    "/proc", "/root", "/sbin", "/srv", "/sys", "/usr", "/var",
    "/Applications", "/Library", "/System", "/Users", "/Volumes",
}
_HOME_TOKENS = {"~", "$HOME", "${HOME}"}
# /home/<user> や /Users/<user> のようなホームディレクトリそのもの
_HOME_DIR_RE = re.compile(r"^/(?:home|Users)/[^/]+$")
_RM_BIN_RE = re.compile(r"^(?:/\S*/)?rm$")


def _canonical_rm_target(raw: str) -> str | None:
    """rm の引数を guard 比較用の正準形にする。

    末尾の ``/*`` と ``/`` を畳む (``/etc/*`` は ``/etc`` と同じ危険度)。
    """
    token = raw.strip().strip("'\"")
    if not token:
        return None
    while token.endswith("/*"):
        token = token[:-2] or "/"
    while len(token) > 1 and token.endswith("/"):
        token = token[:-1]
    return token or None


def _is_catastrophic_rm_target(token: str) -> bool:
    canonical = _canonical_rm_target(token)
    if canonical is None:
        return False
    if canonical in _HOME_TOKENS or canonical == "..":
        return True
    if canonical in _CATASTROPHIC_DIRS:
        return True
    if _HOME_DIR_RE.match(canonical):
        return True
    if canonical == os.path.expanduser("~"):
        return True
    return False


def check_rm_root_guard(cmd: str) -> str | None:
    """`rm` がシステム全体・ホーム・親ディレクトリを対象にしていないか。

    `cd /elsewhere && rm -rf /` のような回避を防ぐため、critical_deny と同じ
    normalize を通してから各セグメントを検査する。
    """
    segments = (
        _critical_deny.normalize(cmd) if _critical_deny is not None else [cmd]
    )
    for segment in segments:
        tokens = segment.split()
        if not tokens or not _RM_BIN_RE.match(tokens[0]):
            continue
        if any(t == "--no-preserve-root" for t in tokens):
            return (
                "`rm --no-preserve-root` は許可されていません。\n"
                "ルートディレクトリの削除は承認の対象外です。"
            )
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            if _is_catastrophic_rm_target(token):
                return (
                    f"`rm` が壊滅的なパス `{token}` を対象にしています。\n"
                    "システム全体・ホーム・親ディレクトリの削除は承認の対象外です。\n"
                    "削除したい対象を具体的なパスで指定し直してください。"
                )
    return None


# uv 非依存のチェック（常時有効）
#
# DENY_CHECKS が先に評価される。ASK_CHECKS は deny に該当しなかったものだけを
# 対象にするので、例えば `rm -rf /` は root guard (deny) が critical_ask より
# 優先される。
DENY_CHECKS = [
    check_rm_root_guard,      # ★最初に実行: 壊滅的な削除は承認の余地なし
    check_critical_deny,      # common.toml の critical_deny を強制
    check_env_exposure,       # 引数なし環境変数露出は問答無用でブロック
    check_git_c_dangerous,    # git -C 経由の deny サブコマンド実行をブロック
    check_pip_redirect,       # pip → uv/uvx (プロジェクト種別を問わず全面禁止)
    check_file_read,
    check_archive,
    check_curl_file_send,
    check_xargs_pipe,
]

# 承認を求めるチェック（ユーザーが許可すればそのまま実行される）
ASK_CHECKS = [
    check_critical_ask,       # common.toml の critical_ask
    check_find_dangerous,     # find -exec rm / -delete によるファイル削除
]


def main() -> None:
    data = read_input()

    if normalize_tool_kind(data.get("tool_name", "")) != "bash":
        sys.exit(0)

    cmd = get_command(data.get("tool_input", {}))
    if not cmd:
        sys.exit(0)

    for check in DENY_CHECKS:
        reason = check(cmd)
        if reason:
            emit_pretool_deny(f"[hook blocked] {reason}")

    for check in ASK_CHECKS:
        reason = check(cmd)
        if reason:
            emit_pretool_ask(f"[hook] 承認が必要です\n{reason}")

    sys.exit(0)


if __name__ == "__main__":
    main()
