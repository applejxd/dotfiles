#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: Bash コマンドの安全性チェック

危険なパターンを検出して deny (拒否) または ask (ユーザー承認を要求) を返す。

  - deny: 承認の余地なく拒否する。センシティブ情報の露出や壊滅的な削除など
  - ask : エージェントが提案し、ユーザーが承認すればそのまま実行される。
          ファイル削除のような「危険だが承認すれば妥当」な操作に使う

判定の主軸は common.toml の [bash] deny / ask。同じリストから Claude の
permission も生成されるので、ルールは 1 箇所に書けばよい。
permission リストは Claude にしか効かないが、この hook は Copilot にも効く。

出力規約は ``agent_compat.emit_pretool_deny`` / ``emit_pretool_ask`` に委譲する
(両ツール対応)。

fail-closed: ポリシー設定を読めない場合は素通りさせず deny する。
"""
from __future__ import annotations

import ipaddress
import os
import re
import shlex
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit

# 検査の上限。これを超えるコマンドは内容を確認できないので拒否する
_MAX_COMMAND_LEN = 10000
# 自前のタイムアウト秒。hook の timeout (30s) より十分手前で打ち切る
_SELF_TIMEOUT_SEC = 10

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_ask,
    emit_pretool_deny,
    get_command,
    normalize_tool_kind,
    read_input,
)

# ~/.config/agents/ (chezmoi 管理) にあるポリシーモジュールを import
# AGENTS_CONFIG_DIR で差し替え可能 (テスト・コンテナから repo の実体を指すため)
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
_POLICY_IMPORT_ERROR: str | None = None
try:
    import command_policy as _policy  # noqa: E402
except Exception as _exc:  # pragma: no cover - 構文エラー等も拾う
    _policy = None  # type: ignore[assignment]
    _POLICY_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

# ─── センシティブパスの判定 ──────────────────────────────────────────
# コマンド文字列全体への部分一致は誤検知が多い
# (`grep -rn token .` の token は検索語であってパスではない、
#  `git commit -m "fix token refresh"` の token はメッセージの一部)。
# 引数トークンを 1 つずつ見て「パスらしいか」→「センシティブか」の順で判定する。

# ファイル名そのものが秘密を意味するもの (basename の完全一致 / 前方一致)
_SENSITIVE_BASENAMES = {
    ".env", ".netrc", ".pypirc", ".npmrc", "credentials", "key.txt",
    "keys.txt", "shadow", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
_SENSITIVE_BASENAME_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
_SENSITIVE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".asc",
)
# パスに含まれると秘密領域とみなすディレクトリ
_SENSITIVE_DIRS = (".ssh", ".gnupg", ".aws", ".config/gh", ".config/sops",
                   "sops/age", "secrets")
# basename に含まれると秘密とみなす語 (パスらしいトークンにのみ適用)
_SENSITIVE_WORD_RE = re.compile(
    r"(?:secret|password|passwd|credential|api[_-]?key|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
# 明示的に除外する (サンプル・テンプレート)
_SENSITIVE_EXEMPT_RE = re.compile(
    r"(?:\.example$|\.sample$|\.template$|\.tmpl$|\.md$|\.rst$|\.txt\.example$)",
    re.IGNORECASE,
)
# /etc 配下の特定ファイル
_SENSITIVE_ABS_PATHS = {"/etc/shadow", "/etc/passwd", "/etc/sudoers"}
# プロセスの環境変数を覗くパス
_PROC_ENVIRON_RE = re.compile(r"/proc/(?:\d+|self)/environ")
# シェル履歴
_HISTORY_BASENAMES = {
    ".bash_history", ".zsh_history", ".sh_history", ".python_history",
    ".psql_history", ".mysql_history", ".node_repl_history",
}
# CLI の認証情報を保持するファイル
_CREDENTIAL_PATHS = ("/.config/gh/hosts.yml", "/.docker/config.json",
                     "/.git-credentials", "/.kube/config",
                     "/.config/gcloud/credentials.db", "/.azure/msal_token_cache.json",
                     "/.terraform.d/credentials.tfrc.json")

# grep 系は最初の非フラグ引数が検索語なのでパス判定から除外する
_PATTERN_FIRST_COMMANDS = {"grep", "rg", "ag", "ack", "egrep", "fgrep", "sed", "awk"}
# 末尾の引数が書き込み先になるコマンド (コピー先が .env でも読み取りではない)
_DEST_LAST_COMMANDS = {"cp", "mv", "install", "ln", "rsync", "scp"}
# ファイル内容を表示する git サブコマンド
_GIT_FILE_SUBCOMMANDS = {"diff", "show", "log", "blame", "cat-file", "grep"}


def _looks_like_path(token: str) -> bool:
    """引数がパスらしいか。検索語や通常の単語を除外するための判定。"""
    if "/" in token or token.startswith("~"):
        return True
    if token.startswith(".") and len(token) > 1:
        return True
    # foo.pem のように既知の拡張子を持つもの
    return token.lower().endswith(_SENSITIVE_SUFFIXES)


def _is_sensitive_token(token: str) -> str | None:
    """パスらしいトークンがセンシティブなら、その理由を返す。"""
    cleaned = token.strip("'\"")
    if not cleaned:
        return None

    expanded = cleaned.replace("~", os.path.expanduser("~"), 1)
    normalized = os.path.normpath(expanded)
    base = os.path.basename(normalized)

    if _SENSITIVE_EXEMPT_RE.search(base):
        return None
    # `.env.example` のようにサンプルであることが接尾辞で分かるもの
    if base.startswith(".env.") and base != ".env.local":
        return None
    # credentials のような既知の basename は slash や拡張子がなくても
    # ファイル名そのものが秘密を意味する。
    if base in _SENSITIVE_BASENAMES or base.startswith(_SENSITIVE_BASENAME_PREFIXES):
        return base
    if base in _HISTORY_BASENAMES:
        return f"シェル履歴 ({base})"
    if not _looks_like_path(cleaned):
        return None

    if normalized in _SENSITIVE_ABS_PATHS:
        return normalized
    if _PROC_ENVIRON_RE.search(normalized):
        return "プロセスの環境変数"
    for cred in _CREDENTIAL_PATHS:
        if normalized.endswith(cred):
            return base
    parts = normalized.split("/")
    for d in _SENSITIVE_DIRS:
        if d in parts or (d.count("/") and d in normalized):
            return f"{d} 配下"
    if base.lower().endswith(_SENSITIVE_SUFFIXES):
        return base
    if _SENSITIVE_WORD_RE.search(base):
        return base
    return None


def is_sensitive_path(text: str) -> str | None:
    """コマンド文字列にセンシティブなパス引数が含まれていれば理由を返す。

    ``cp .env.example .env`` のように「サンプルから作る」形は正当なので、
    cp / mv の最終引数 (コピー先) は判定対象から外す。
    """
    tokens = text.split()
    if not tokens:
        return None
    head = _basename(tokens[0].strip("'\""))
    args = tokens[1:]
    if head in _DEST_LAST_COMMANDS and len(args) >= 2:
        # 末尾は書き込み先。読み取り元だけを見る
        args = args[:-1]
    skip_pattern_arg = head in _PATTERN_FIRST_COMMANDS
    for token in args:
        if token.startswith("-"):
            continue
        if skip_pattern_arg:
            # 最初の非フラグ引数は検索語なので飛ばす
            skip_pattern_arg = False
            continue
        reason = _is_sensitive_token(token)
        if reason:
            return reason
    return None

# ─── ファイル内容を読むコマンド ──────────────────────────────────────
FILE_READ_COMMANDS = [
    "grep", "rg", "ag", "ack", "cat", "tac", "head", "tail", "nl",
    "sed", "awk", "less", "more", "sort", "uniq", "cut", "column",
    "strings", "xxd", "hexdump", "jq", "yq",
    "base64", "od", "xxd", "diff", "vimdiff",
    # ファイルを開く / 情報を出すもの
    "vim", "vi", "nvim", "emacs", "nano", "code", "codium", "subl",
    "wc", "file", "stat", "realpath", "readlink",
    # ディレクトリの中身を列挙するもの (鍵ファイル名が漏れる)
    "ls", "tree", "find", "fd",
    # 内容を別の場所へ複製・転送するもの (読み取りと同じ露出リスク)
    "cp", "mv", "install", "rsync", "scp", "sftp", "dd", "tee",
    "ln", "shred", "split", "gpg", "openssl",
]

# ─── 環境変数を露出するコマンド ─────────────────────────────────────
# 引数なしの全件露出に加え、`printenv AWS_SECRET_ACCESS_KEY` のような
# 個別参照や `env | grep key` のような絞り込みも対象にする。
ENV_EXPOSURE_BINS = {"env", "printenv", "export", "set", "declare", "typeset"}
# 環境変数名としてセンシティブなもの
_SENSITIVE_ENV_RE = re.compile(
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|SESSION)",
    re.IGNORECASE,
)

# ─── アーカイブコマンド ───────────────────────────────────────────────
ARCHIVE_COMMANDS = ["tar", "zip", "gzip", "bzip2", "7z", "xz"]

# ─── インラインコードを受け取るインタプリタ ─────────────────────────
_INLINE_CODE_BINS = {"python", "perl", "ruby", "node", "php", "awk", "gawk", "mawk"}
_INLINE_CODE_FLAGS = {"-c", "-e", "-E", "-r", "-p", "--eval", "--print"}
# コード片から外部コマンドを起動する形
_INLINE_EXEC_RE = re.compile(
    r"(?:os\.system|subprocess\.|popen|execSync|spawnSync|child_process|"
    r"\bsystem\s*\(|\bexec\s*\(|\bqx\s*[({/]|`[^`]+`|\bshell_exec\b|\bpassthru\b)",
    re.IGNORECASE,
)

# ─── curl/wget の request / transfer 判定 ───────────────────────────
_HTTP_READ_METHODS = {"GET", "HEAD"}
_CURL_DATA_FLAGS = {
    "-d", "--data", "--data-ascii", "--data-binary", "--data-raw",
    "--data-urlencode", "--json",
}
_CURL_FORM_FLAGS = {"-F", "--form", "--form-string"}
_CURL_UPLOAD_FLAGS = {"-T", "--upload-file"}
_CURL_OUTPUT_FLAGS = {
    "-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar",
    "--stderr", "--trace", "--trace-ascii",
}
_CURL_VALUE_FLAGS = {
    "-A", "--user-agent", "-b", "--cookie",
    "--connect-timeout", "--connect-to", "-C", "--continue-at",
    "-D", "--dump-header", "--dns-interface", "--dns-ipv4-addr",
    "--dns-ipv6-addr", "--dns-servers",
    "-e", "--referer", "-E", "--cert", "--cert-type", "--key",
    "--key-type", "-H", "--header", "--hostpubmd5", "--hostpubsha256",
    "--interface", "--limit-rate", "--local-port", "--max-filesize",
    "-m", "--max-time", "--noproxy", "--output-dir", "--preproxy",
    "--proxy", "--proxy1.0", "--proxy-header",
    "--proxy-user", "-Q", "--quote", "-r", "--range", "--rate",
    "--resolve", "--retry", "--retry-delay", "--retry-max-time",
    "--socks4", "--socks4a", "--socks5", "--socks5-hostname",
    "--speed-limit", "--speed-time", "--tls-max", "--tls13-ciphers",
    "-u", "--user", "--unix-socket", "--abstract-unix-socket",
    "--url", "-w", "--write-out", "-x", "--proxy",
    "-y", "--speed-time", "-Y", "--speed-limit",
}
# localhost 例外を無効化するオプション。
# 接続先を URL から読み取れなくする (proxy / socket / 名前解決の差し替え) か、
# リダイレクト追従で URL 以外のホストへ到達しうるもの。
_CURL_LOCAL_BLOCKING_FLAGS = {
    "-x", "--proxy", "--proxy1.0", "--preproxy",
    "--socks4", "--socks4a", "--socks5", "--socks5-hostname",
    "--unix-socket", "--abstract-unix-socket",
    "--connect-to", "--resolve", "--interface",
    "--dns-interface", "--dns-servers",
    "-L", "--location", "--location-trusted",
    "-K", "--config",
}

_CURL_NO_VALUE_SHORT_FLAGS = set("012346#BaJMRZfFsSLIikvVqgGNnO")
_CURL_CONFIG_FLAGS = {"-K", "--config"}
_WGET_BODY_FLAGS = {
    "--post-data", "--post-file", "--body-data", "--body-file",
}
_WGET_OUTPUT_FLAGS = {"-O", "--output-document"}
_WGET_CONFIG_FLAGS = {"-e", "--execute", "--config"}
_NON_EXECUTING_HTTP_PREFIXES = {
    "cat", "echo", "file", "find", "grep", "ls", "rg", "sed", "stat",
    "touch", "wc", "awk", "gawk", "printf",
}


def _resolve_http_long_option(
    token: str, options: set[str]
) -> tuple[str, bool]:
    """Resolve an unambiguous curl/wget long-option prefix."""
    if not token.startswith("--"):
        return token, False
    name, separator, value = token.partition("=")
    if name in options:
        return token, False
    matches = [option for option in options if option.startswith(name)]
    if len(matches) != 1:
        return token, len(matches) > 1
    resolved = matches[0]
    if separator:
        resolved = f"{resolved}={value}"
    return resolved, False


def _take_option_value(
    args: list[str], index: int, token: str, short: str | None, long: str
) -> tuple[str | None, int]:
    """Return an attached/separate option value and the next index."""
    if token.startswith(f"{long}="):
        return token[len(long) + 1:], index + 1
    if short and token.startswith(short) and token != short:
        return token[len(short):], index + 1
    if token == long or (short and token == short):
        if index + 1 >= len(args):
            return None, index + 1
        return args[index + 1], index + 2
    return None, index


def _payload_source(kind: str, value: str) -> str | None:
    """Extract a local file referenced by a curl/wget payload option."""
    if kind in _CURL_UPLOAD_FLAGS or kind in {"--post-file", "--body-file"}:
        return value
    if kind in _CURL_FORM_FLAGS:
        candidate = value.split("=", 1)[-1]
        if candidate.startswith("@") or candidate.startswith("<"):
            return candidate[1:].split(";", 1)[0]
        return None
    if value.startswith("@"):
        return value[1:]
    if kind == "--data-urlencode" and "@" in value:
        return value.split("@", 1)[1]
    return None


def _new_http_call(tool: str) -> dict[str, object]:
    return {
        "tool": tool,
        "method": None,
        "body_kinds": [],
        "payload_sources": [],
        "output_targets": [],
        "output_dir": None,
        "remote_name": False,
        "urls": [],
        "get_mode": False,
        "ambiguous": False,
        # localhost 例外を無効化する要因があるか (proxy / socket / redirect 等)。
        # wget は既定でリダイレクトを追うため常に無効化する。
        "blocks_local": tool != "curl",
    }


def _apply_curl_no_value_flags(
    call: dict[str, object], flags: str
) -> None:
    """Apply request/output semantics from curl short flags without values."""
    if "I" in flags:
        call["method"] = "HEAD"
    if "G" in flags:
        call["get_mode"] = True
    if "O" in flags:
        call["remote_name"] = True
    if "L" in flags:
        call["blocks_local"] = True


def _parse_curl_tokens(tokens: list[str], command_index: int) -> list[dict[str, object]]:
    """Parse one curl command, including transfers separated by ``--next``."""
    calls: list[dict[str, object]] = []
    call = _new_http_call("curl")
    args = tokens[command_index + 1:]
    i = 0
    while i < len(args):
        token = args[i]
        token, ambiguous_prefix = _resolve_http_long_option(
            token,
            {
                "--request", "--data", "--data-ascii", "--data-binary",
                "--data-raw", "--data-urlencode", "--json", "--form",
                "--form-string", "--upload-file", "--output", "--dump-header",
                "--cookie-jar", "--stderr", "--trace", "--trace-ascii",
                "--config", "--get", "--head", "--next", "--output-dir",
                "--remote-name", "--remote-name-all", "--url",
            }
            # 短縮形で書かれても localhost 例外の無効化を取りこぼさない
            | {flag for flag in _CURL_LOCAL_BLOCKING_FLAGS if flag.startswith("--")},
        )
        if ambiguous_prefix:
            call["ambiguous"] = True
            i += 1
            continue
        if token.split("=", 1)[0] in _CURL_LOCAL_BLOCKING_FLAGS:
            call["blocks_local"] = True
        if token in {"-:", "--next"}:
            calls.append(call)
            call = _new_http_call("curl")
            i += 1
            continue

        cluster = re.fullmatch(r"-([fFsSLIikvVqgGNnO]*)([XdFToDc])(.*)", token)
        if cluster:
            prefix, option, attached = cluster.groups()
            _apply_curl_no_value_flags(call, prefix)
            value = attached
            if not value:
                if i + 1 >= len(args):
                    call["ambiguous"] = True
                    i += 1
                    continue
                value = args[i + 1]
                i += 1
            kind = {
                "X": "-X", "d": "-d", "F": "-F", "T": "-T",
                "o": "-o", "D": "-D", "c": "-c",
            }[option]
            if kind == "-X":
                call["method"] = value
            elif kind in _CURL_OUTPUT_FLAGS:
                call["output_targets"].append(value)
            else:
                call["body_kinds"].append(kind)
                source = _payload_source(kind, value)
                if source:
                    call["payload_sources"].append(source)
            i += 1
            continue

        value, next_i = _take_option_value(args, i, token, "-X", "--request")
        if next_i != i:
            if value is None:
                call["ambiguous"] = True
            else:
                call["method"] = value
            i = next_i
            continue
        if token in {"-I", "--head"}:
            call["method"] = "HEAD"
            i += 1
            continue
        if token in {"-G", "--get"}:
            call["get_mode"] = True
            i += 1
            continue
        if token in {"-O", "--remote-name", "--remote-name-all"}:
            call["remote_name"] = True
            i += 1
            continue

        matched_kind: str | None = None
        matched_value: str | None = None
        for short, long in (
            ("-d", "--data"), (None, "--data-ascii"),
            (None, "--data-binary"), (None, "--data-raw"),
            (None, "--data-urlencode"), (None, "--json"),
            ("-F", "--form"), (None, "--form-string"),
            ("-T", "--upload-file"), ("-o", "--output"),
            ("-D", "--dump-header"), ("-c", "--cookie-jar"),
            (None, "--stderr"), (None, "--trace"), (None, "--trace-ascii"),
            (None, "--output-dir"), (None, "--url"),
        ):
            value, next_i = _take_option_value(args, i, token, short, long)
            if next_i != i:
                matched_kind = token.split("=", 1)[0]
                if short and matched_kind.startswith(short):
                    matched_kind = short
                else:
                    matched_kind = long
                matched_value = value
                break
        if matched_kind is not None:
            if matched_value is None:
                call["ambiguous"] = True
            elif matched_kind in _CURL_OUTPUT_FLAGS:
                call["output_targets"].append(matched_value)
            elif matched_kind == "--output-dir":
                call["output_dir"] = matched_value
            elif matched_kind == "--url":
                call["urls"].append(matched_value)
            else:
                call["body_kinds"].append(matched_kind)
                source = _payload_source(matched_kind, matched_value)
                if source:
                    call["payload_sources"].append(source)
            i = next_i
            continue

        if any(
            token == flag or token.startswith(f"{flag}=")
            for flag in _CURL_CONFIG_FLAGS
        ):
            call["ambiguous"] = True
            if token in _CURL_CONFIG_FLAGS and "=" not in token:
                i += 2
            else:
                i += 1
            continue

        value_flag = next(
            (
                flag for flag in _CURL_VALUE_FLAGS
                if (
                    token == flag
                    or token.startswith(f"{flag}=")
                    or (len(flag) == 2 and token.startswith(flag) and token != flag)
                )
            ),
            None,
        )
        if value_flag:
            if value_flag in _CURL_LOCAL_BLOCKING_FLAGS:
                call["blocks_local"] = True
            i += 2 if token == value_flag else 1
            if i > len(args):
                call["ambiguous"] = True
            continue
        short_value_flags = {
            flag[1] for flag in _CURL_VALUE_FLAGS
            if len(flag) == 2 and flag.startswith("-")
        }
        value_cluster = re.fullmatch(
            rf"-([fFsSLIikvVqgGNnO]*)([{''.join(sorted(short_value_flags))}])(.*)",
            token,
        )
        if value_cluster:
            prefix, option, attached = value_cluster.groups()
            _apply_curl_no_value_flags(call, prefix)
            if f"-{option}" in _CURL_LOCAL_BLOCKING_FLAGS:
                call["blocks_local"] = True
            if not attached:
                i += 2
                if i > len(args):
                    call["ambiguous"] = True
            else:
                i += 1
            continue
        if token.startswith("--"):
            i += 1
            continue
        if token.startswith("-") and len(token) > 1:
            short_flags = set(token[1:])
            if short_flags.issubset(_CURL_NO_VALUE_SHORT_FLAGS):
                _apply_curl_no_value_flags(call, token[1:])
            else:
                call["ambiguous"] = True
            i += 1
            continue
        call["urls"].append(token)
        i += 1
    calls.append(call)
    return calls


def _parse_wget_tokens(tokens: list[str], command_index: int) -> list[dict[str, object]]:
    """Parse one wget command into its request-relevant fields."""
    call = _new_http_call("wget")
    args = tokens[command_index + 1:]
    i = 0
    while i < len(args):
        token = args[i]
        token, ambiguous_prefix = _resolve_http_long_option(
            token,
            {
                "--method", "--post-data", "--post-file", "--body-data",
                "--body-file", "--output-document", "--execute", "--config",
                "--directory-prefix",
            },
        )
        if ambiguous_prefix:
            call["ambiguous"] = True
            i += 1
            continue
        output_cluster = re.fullmatch(r"-[A-Za-z]*O(.*)", token)
        if output_cluster and not token.startswith("--"):
            output = output_cluster.group(1)
            if not output:
                if i + 1 >= len(args):
                    call["ambiguous"] = True
                    i += 1
                    continue
                output = args[i + 1]
                i += 1
            call["output_targets"].append(output)
            i += 1
            continue
        value, next_i = _take_option_value(args, i, token, None, "--method")
        if next_i != i:
            if value is None:
                call["ambiguous"] = True
            else:
                call["method"] = value
            i = next_i
            continue

        matched_kind: str | None = None
        matched_value: str | None = None
        for short, long in (
            (None, "--post-data"), (None, "--post-file"),
            (None, "--body-data"), (None, "--body-file"),
            ("-O", "--output-document"),
            ("-P", "--directory-prefix"),
        ):
            value, next_i = _take_option_value(args, i, token, short, long)
            if next_i != i:
                matched_kind = short if short and token.startswith(short) else long
                matched_value = value
                break
        if matched_kind is not None:
            if matched_value is None:
                call["ambiguous"] = True
            elif matched_kind in _WGET_OUTPUT_FLAGS:
                call["output_targets"].append(matched_value)
            elif matched_kind == "-P":
                call["output_dir"] = matched_value
            else:
                call["body_kinds"].append(matched_kind)
                source = _payload_source(matched_kind, matched_value)
                if source:
                    call["payload_sources"].append(source)
            i = next_i
            continue

        if any(
            token == flag or token.startswith(f"{flag}=")
            for flag in _WGET_CONFIG_FLAGS
        ):
            call["ambiguous"] = True
            if token in _WGET_CONFIG_FLAGS and "=" not in token:
                i += 2
            else:
                i += 1
            continue
        if not token.startswith("-"):
            call["urls"].append(token)
        i += 1
    return [call]


# localhost であっても特権的な制御 API が動くポート。
# ここへの mutation は localhost 例外の対象外にする。
_UNSAFE_LOCAL_PORTS = {
    2375, 2376, 4243,        # Docker daemon
    2379, 2380,              # etcd
    6443, 8443,              # Kubernetes API server
    10250, 10255, 10256,     # kubelet
    6379,                    # Redis
    11211,                   # memcached
}
# curl は scheme 省略時に http を補う。ここに無い scheme は localhost 例外の対象外
# (gopher:// や dict:// はループバック宛でも任意プロトコルの送信に使えるため)。
_LOCAL_URL_SCHEMES = {"http", "https"}
# 静的にホストを確定できなくなる文字 (変数展開・コマンド置換・curl の glob)
_UNRESOLVABLE_URL_CHARS = "$`{}[]"


def _is_local_url(url: str) -> bool:
    """Report whether a URL provably targets this machine's loopback interface.

    Returns ``False`` whenever the host cannot be determined statically, so the
    caller keeps its default (stricter) behaviour.
    """
    if not isinstance(url, str) or not url:
        return False
    candidate = url.strip().strip("'\"")
    if not candidate:
        return False
    # IPv6 リテラルの [] は例外的に許す (ホスト全体が括られている形のみ)
    stripped = re.sub(r"^(\w+://)?\[[0-9A-Fa-f:.]+\]", r"\1", candidate)
    if any(char in stripped for char in _UNRESOLVABLE_URL_CHARS):
        return False
    scheme, separator, _ = candidate.partition("://")
    if separator:
        if scheme.lower() not in _LOCAL_URL_SCHEMES:
            return False
    else:
        # scheme 省略形。`gopher:127.0.0.1` のような scheme 付きの別形式は弾く
        head = candidate.split("/", 1)[0]
        if ":" in head and not re.fullmatch(r"[^:/]+:\d*", head):
            return False
        candidate = f"http://{candidate}"
    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    if not host:
        return False
    if port is not None and port in _UNSAFE_LOCAL_PORTS:
        return False
    host = host.rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        # 10 進・16 進表記 (2130706433 / 0x7f000001) は ip_address が拒否するため
        # 自動的に対象外になる
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_http_tokens(
    tokens: list[str], command_index: int
) -> list[dict[str, object]]:
    tool = _basename(tokens[command_index])
    if tool == "curl":
        return _parse_curl_tokens(tokens, command_index)
    return _parse_wget_tokens(tokens, command_index)


def _http_transfer_calls(cmd: str) -> list[dict[str, object]]:
    """Find curl/wget transfers through wrappers, substitutions, and functions."""
    calls: list[dict[str, object]] = []
    if _policy is None:
        return calls
    for body in _policy.extract_function_bodies(cmd):
        calls.extend(_http_transfer_calls(body))
    for raw_segment in _policy.split_command_segments(cmd):
        try:
            raw_tokens = shlex.split(raw_segment)
        except ValueError:
            raw_tokens = []
        command_index = None
        if (
            raw_tokens
            and _basename(raw_tokens[0]) not in _NON_EXECUTING_HTTP_PREFIXES
        ):
            command_index = next(
                (
                    i for i, token in enumerate(raw_tokens)
                    if _basename(token) in {"curl", "wget"}
                ),
                None,
            )
        if command_index is not None:
            calls.extend(_parse_http_tokens(raw_tokens, command_index))
            for inner in _policy.extract_command_substitutions(raw_segment):
                calls.extend(_http_transfer_calls(inner))
            continue

        normalized_segments = [
            segment
            for segment in _policy.normalize(raw_segment)
            if segment.startswith(("curl ", "wget ")) or segment in {"curl", "wget"}
        ]
        if not normalized_segments:
            continue
        if not raw_tokens:
            calls.append({**_new_http_call("unknown"), "ambiguous": True})
            continue
        for normalized_segment in normalized_segments:
            try:
                normalized_tokens = shlex.split(normalized_segment)
            except ValueError:
                calls.append({**_new_http_call("unknown"), "ambiguous": True})
                continue
            calls.extend(_parse_http_tokens(normalized_tokens, 0))
    return calls


# ─── GitHub CLI API の method / operation 判定 ─────────────────────
_GH_API_METHOD_FLAGS = {"-X", "--method"}
_GH_API_FIELD_FLAGS = {"-f", "--raw-field", "-F", "--field"}
_GH_API_INPUT_FLAGS = {"--input"}
_GH_API_VALUE_FLAGS = {
    "--cache", "-H", "--header", "--hostname", "-q", "--jq",
    "-p", "--preview", "-t", "--template",
}
_GH_API_READ_METHODS = {"GET", "HEAD"}


def _option_value(token: str, short: str, long: str) -> str | None:
    """Return an attached option value, or None when the token does not match."""
    if token.startswith(f"{long}="):
        return token[len(long) + 1:]
    if token.startswith(short) and token != short:
        return token[len(short):]
    return None


def _parse_gh_api_tokens(
    raw_tokens: list[str], gh_index: int
) -> dict[str, object]:
    """Parse one tokenized ``gh api`` invocation."""
    endpoint: str | None = None
    method: str | None = None
    fields: list[tuple[str, str]] = []
    input_path: str | None = None
    ambiguous = False
    args = raw_tokens[gh_index + 2:]
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            if i + 1 < len(args) and endpoint is None:
                endpoint = args[i + 1]
                i += 2
                continue
            ambiguous = True
            i += 1
            continue

        attached = _option_value(token, "-X", "--method")
        if attached is not None:
            method = attached
            i += 1
            continue
        if token in _GH_API_METHOD_FLAGS:
            if i + 1 >= len(args):
                ambiguous = True
                i += 1
                continue
            method = args[i + 1]
            i += 2
            continue

        field_kind = None
        field_value = None
        for short, long in (("-f", "--raw-field"), ("-F", "--field")):
            attached = _option_value(token, short, long)
            if attached is not None:
                field_kind = short
                field_value = attached
                break
            if token in {short, long}:
                field_kind = short
                if i + 1 < len(args):
                    field_value = args[i + 1]
                    i += 1
                else:
                    ambiguous = True
                break
        if field_kind is not None:
            if field_value is not None:
                fields.append((field_kind, field_value))
            i += 1
            continue

        if token.startswith("--input="):
            input_path = token.split("=", 1)[1]
            i += 1
            continue
        if token in _GH_API_INPUT_FLAGS:
            if i + 1 >= len(args):
                ambiguous = True
                i += 1
                continue
            input_path = args[i + 1]
            i += 2
            continue

        value_flag = next(
            (
                flag for flag in _GH_API_VALUE_FLAGS
                if token == flag or token.startswith(f"{flag}=")
            ),
            None,
        )
        if value_flag:
            if token == value_flag:
                if i + 1 >= len(args):
                    ambiguous = True
                    i += 1
                    continue
                i += 2
            else:
                i += 1
            continue

        if token.startswith("-"):
            i += 1
            continue
        if endpoint is None:
            endpoint = token
        else:
            ambiguous = True
        i += 1

    return {
        "endpoint": endpoint,
        "method": method,
        "fields": fields,
        "input": input_path,
        "ambiguous": ambiguous,
    }


def _ambiguous_gh_api_call() -> dict[str, object]:
    return {
        "endpoint": None,
        "method": None,
        "fields": [],
        "input": None,
        "ambiguous": True,
    }


def _gh_api_calls(cmd: str) -> list[dict[str, object]]:
    """Parse normalized ``gh api`` segments into the fields needed by policy."""
    calls: list[dict[str, object]] = []
    if _policy is None:
        return calls

    for body in _policy.extract_function_bodies(cmd):
        calls.extend(_gh_api_calls(body))

    for raw_segment in _policy.split_command_segments(cmd):
        normalized_segments = [
            segment
            for segment in _policy.normalize(raw_segment)
            if segment.startswith("gh api")
        ]
        if not normalized_segments:
            continue
        try:
            raw_tokens = shlex.split(raw_segment)
        except ValueError:
            calls.append(_ambiguous_gh_api_call())
            continue
        gh_index = next(
            (
                i for i in range(len(raw_tokens) - 1)
                if _basename(raw_tokens[i]) == "gh" and raw_tokens[i + 1] == "api"
            ),
            None,
        )
        if gh_index is not None:
            calls.append(_parse_gh_api_tokens(raw_tokens, gh_index))
            for inner in _policy.extract_command_substitutions(raw_segment):
                calls.extend(_gh_api_calls(inner))
            continue

        for normalized_segment in normalized_segments:
            try:
                normalized_tokens = shlex.split(normalized_segment)
            except ValueError:
                calls.append(_ambiguous_gh_api_call())
                continue
            calls.append(_parse_gh_api_tokens(normalized_tokens, 0))
    return calls


def _graphql_query(fields: list[tuple[str, str]]) -> tuple[str | None, bool]:
    """Return an inline GraphQL query and whether its source is inspectable."""
    queries: list[str] = []
    for kind, field in fields:
        if "=" not in field:
            continue
        key, value = field.split("=", 1)
        if key != "query":
            continue
        if kind == "-F" and value.startswith("@"):
            return None, False
        queries.append(value)
    if len(queries) != 1:
        return None, False
    query = queries[0].lstrip("\ufeff")
    if re.search(r"(?:\$\(|\$\{|`)", query):
        return None, False
    query = re.sub(r"(?m)^\s*#.*$", "", query).strip()
    return query, bool(query)


def check_gh_token_exposure(cmd: str) -> str | None:
    """Block ``gh auth status`` variants that print the active token."""
    if _policy is None:
        return None
    for segment in _policy.normalize(cmd):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        if (
            len(tokens) >= 3
            and _basename(tokens[0]) == "gh"
            and tokens[1:3] == ["auth", "status"]
            and any(token in {"-t", "--show-token"} for token in tokens[3:])
        ):
            return "`gh auth status --show-token` による token 表示は禁止されています。"
    return None


def check_gh_api_sensitive_input(cmd: str) -> str | None:
    """Block sensitive local files used as a ``gh api`` request payload."""
    for call in _gh_api_calls(cmd):
        input_path = call["input"]
        if isinstance(input_path, str) and input_path != "-":
            matched = _is_sensitive_token(input_path)
            if matched:
                return f"`gh api --input` がセンシティブなファイルを送信します ({matched})。"
        fields = call["fields"]
        if not isinstance(fields, list):
            continue
        for kind, field in fields:
            if kind != "-F" or "=" not in field:
                continue
            value = field.split("=", 1)[1]
            if not value.startswith("@") or value == "@-":
                continue
            matched = _is_sensitive_token(value[1:])
            if matched:
                return f"`gh api -F` がセンシティブなファイルを送信します ({matched})。"
    return None


def check_gh_api_mutation(cmd: str) -> str | None:
    """Ask for API writes while leaving proven reads to auto / assisted."""
    for call in _gh_api_calls(cmd):
        endpoint = call["endpoint"]
        method = call["method"]
        fields = call["fields"]
        input_path = call["input"]
        ambiguous = call["ambiguous"]
        if (
            not isinstance(endpoint, str)
            or not isinstance(fields, list)
            or ambiguous is True
        ):
            return "`gh api` の endpoint または引数を静的に判定できません。"

        if endpoint == "graphql":
            if input_path is not None:
                return "`gh api graphql` の input 内容を静的に判定できません。"
            query, inspectable = _graphql_query(fields)
            if not inspectable or query is None:
                return "`gh api graphql` の query 内容を静的に判定できません。"
            if re.search(r"(?i)\bmutation\b", query):
                return "`gh api graphql` が mutation を実行しようとしています。"
            if not (re.match(r"(?is)^query(?:\s|\()", query) or query.startswith("{")):
                return "`gh api graphql` が読み取り query であることを確認できません。"
            continue

        explicit_method = method.upper() if isinstance(method, str) else None
        if explicit_method is not None and not re.fullmatch(r"[A-Za-z]+", explicit_method):
            return "`gh api` の HTTP method を静的に判定できません。"
        if input_path is not None:
            return "`gh api --input` は request body を送信します。"
        if explicit_method in _GH_API_READ_METHODS:
            continue
        if explicit_method is None and not fields:
            continue
        effective_method = explicit_method or "POST"
        return f"`gh api` が読み取り以外の HTTP method ({effective_method}) を使用します。"
    return None


def _segments(cmd: str) -> list[str]:
    """normalize 済みセグメント + 元の文字列を返す。

    normalize は shlex を通るのでクォートや ``${VAR}`` の形が変わる。
    パターン照合では元の文字列も併せて見て取りこぼさないようにする。
    """
    segs = list(_policy.normalize(cmd)) if _policy is not None else []
    segs.append(cmd)
    return segs


def check_file_read(cmd: str) -> str | None:
    """ファイル読み込み・複製コマンドがセンシティブパスを対象にしていないか。

    `git diff <path>` のように、許可済みコマンドでも引数がセンシティブなら止める。
    """
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "git" and len(tokens) > 2 and tokens[1] in _GIT_FILE_SUBCOMMANDS:
            matched = is_sensitive_path(" ".join(tokens[1:]))
            if matched:
                return (
                    f"`git {tokens[1]}` がセンシティブなパスを対象にしています "
                    f"(パターン: {matched})"
                )
            continue
        if head not in FILE_READ_COMMANDS:
            continue
        matched = is_sensitive_path(segment)
        if matched:
            return (
                f"`{head}` がセンシティブなパスを対象にしています "
                f"(パターン: {matched})"
            )
    return None


def check_env_exposure(cmd: str) -> str | None:
    """環境変数を露出するコマンドを検出。

    引数なしの全件出力に加え、`printenv AWS_SECRET_ACCESS_KEY` のような
    個別参照や `env | grep -i key` のような絞り込みも拒否する。
    `env FOO=1 cmd` は normalize がラッパーとして剥がすのでここには来ない。
    """
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in ENV_EXPOSURE_BINS:
            continue
        args = [t for t in tokens[1:] if not t.startswith("-")]
        if not args:
            return (
                f"環境変数を全件出力するコマンドは許可されていません: `{segment.strip()}`\n"
                "特定の変数を確認する場合は `echo $VAR_NAME` を使用してください。"
            )
        if any(_SENSITIVE_ENV_RE.search(a) for a in args):
            return (
                f"センシティブな環境変数を出力しようとしています: `{segment.strip()}`"
            )
    # `env | grep -i key` のように絞り込む形
    if re.search(r"\b(?:env|printenv)\b\s*(?:\||$)", cmd) and _SENSITIVE_ENV_RE.search(cmd):
        return (
            f"環境変数からセンシティブな値を抽出しようとしています: `{cmd.strip()[:200]}`"
        )
    return None


def check_archive(cmd: str) -> str | None:
    """アーカイブコマンドがセンシティブパスを含んでいないか"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in ARCHIVE_COMMANDS:
            continue
        matched = is_sensitive_path(segment)
        if matched:
            return (
                f"`{head}` でセンシティブなパスをアーカイブしようとしています "
                f"(パターン: {matched})"
            )
    return None


def check_curl_file_send(cmd: str) -> str | None:
    """curl/wget でセンシティブファイルの内容を送信しようとしていないか"""
    for call in _http_transfer_calls(cmd):
        sources = call["payload_sources"]
        if not isinstance(sources, list):
            continue
        reads_stdin = any(
            source in {"-", "/dev/stdin"} for source in sources
        )
        for source in sources:
            if not isinstance(source, str) or source == "-":
                continue
            matched = _is_sensitive_token(source)
            if matched:
                tool = call["tool"]
                return (
                    f"{tool} でセンシティブなファイルを送信しようとしています "
                    f"(パターン: {matched})"
                )
        if reads_stdin:
            for match in re.finditer(r"(?<!<)<(?!<)\s*([^\s;&|]+)", cmd):
                source = match.group(1).strip("'\"")
                matched = _is_sensitive_token(source)
                if matched:
                    return (
                        f"{call['tool']} が標準入力からセンシティブなファイルを"
                        f"送信しようとしています (パターン: {matched})"
                    )
    return None


def check_http_dangerous_output(cmd: str) -> str | None:
    """Block curl/wget output that overwrites startup or authentication files."""
    targets = (
        ".bashrc", ".bash_profile", ".bash_login", ".zshrc", ".zshenv",
        ".zprofile", ".profile", ".login", ".cshrc", ".kshrc",
        "authorized_keys", "known_hosts", ".ssh/config", ".netrc",
        "crontab", ".gitconfig",
    )
    for call in _http_transfer_calls(cmd):
        output_targets = call["output_targets"]
        urls = call["urls"]
        if not isinstance(output_targets, list) or not isinstance(urls, list):
            continue
        output_dir = call["output_dir"]
        remote_name = call["remote_name"]
        if call["tool"] == "wget" and output_targets:
            urls = []
        if call["tool"] == "wget" or remote_name is True:
            for url in urls:
                if not isinstance(url, str):
                    continue
                path = url.split("?", 1)[0].rstrip("/")
                name = path.rsplit("/", 1)[-1]
                if name:
                    if isinstance(output_dir, str):
                        output_targets.append(f"{output_dir.rstrip('/')}/{name}")
                    elif remote_name is True:
                        output_targets.append(name)
        for output in output_targets:
            if not isinstance(output, str):
                continue
            cleaned = output.strip("'\"")
            if any(
                cleaned.endswith(target) or f"/{target}" in cleaned
                for target in targets
            ):
                return (
                    f"`{call['tool']}` が起動・認証設定ファイル `{output}` を"
                    "上書きしようとしています。"
                )
    return None


def check_curl_wget_mutation(cmd: str) -> str | None:
    """Ask for HTTP writes while delegating proven reads to auto / assisted."""
    for call in _http_transfer_calls(cmd):
        tool = call["tool"]
        method = call["method"]
        body_kinds = call["body_kinds"]
        payload_sources = call["payload_sources"]
        get_mode = call["get_mode"]
        ambiguous = call["ambiguous"]
        if (
            not isinstance(body_kinds, list)
            or not isinstance(payload_sources, list)
            or ambiguous is True
        ):
            return f"`{tool}` の request method または引数を静的に判定できません。"
        # ループバック宛だと確証できる transfer は mutation でも承認を求めない。
        # DENY_CHECKS は ASK_CHECKS より前に走るので、秘密情報の送信・起動ファイル
        # の上書き・取得結果の直接実行はこの例外を通らず deny のまま。
        urls = call["urls"]
        if (
            call["blocks_local"] is False
            and isinstance(urls, list)
            and urls
            and all(_is_local_url(url) for url in urls)
        ):
            continue
        explicit_method = method.upper() if isinstance(method, str) else None
        if explicit_method is not None and not re.fullmatch(r"[A-Za-z]+", explicit_method):
            return f"`{tool}` の HTTP method を静的に判定できません。"
        if explicit_method is not None and explicit_method not in _HTTP_READ_METHODS:
            return f"`{tool}` が読み取り以外の HTTP method ({explicit_method}) を使用します。"
        if body_kinds:
            query_only = (
                tool == "curl"
                and get_mode is True
                and explicit_method is None
                and not payload_sources
                and all(kind in _CURL_DATA_FLAGS for kind in body_kinds)
            )
            if not query_only:
                return f"`{tool}` が request body または upload payload を送信します。"
        if explicit_method in _HTTP_READ_METHODS or get_mode is True or not body_kinds:
            continue
        return f"`{tool}` の request を読み取り専用と確認できません。"
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
    """`find -exec rm` や `find -delete` でファイルを削除しようとしていないか。

    削除対象がホームやシステム全体なら承認の余地なく deny する。
    """
    if not re.search(r"\bfind\b", cmd):
        return None
    if not _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return None
    # find の探索起点が壊滅的なら deny (check_rm_root_guard 相当の扱い)
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens or _basename(tokens[0]) != "find":
            continue
        for token in tokens[1:]:
            if token.startswith("-"):
                break
            if _is_catastrophic_rm_target(token):
                return None  # deny 側で処理する
    return (
        "`find` コマンドによるファイル削除操作（-exec rm / -delete 等）です。\n"
        f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
        "削除対象を確認して問題なければ承認してください。"
    )


def check_find_root_guard(cmd: str) -> str | None:
    """`find ~ -delete` のように壊滅的な範囲を一括削除していないか。"""
    if not _FIND_DANGEROUS_EXEC_RE.search(cmd):
        return None
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens or _basename(tokens[0]) != "find":
            continue
        for token in tokens[1:]:
            if token.startswith("-"):
                break
            if _is_catastrophic_rm_target(token):
                return (
                    f"`find` が壊滅的なパス `{token}` を起点に削除しようとしています。\n"
                    "システム全体・ホーム・親ディレクトリの一括削除は承認の対象外です。"
                )
    return None


_PIP_BIN_RE = re.compile(r"^(?:/\S*/)?pip[0-9.]*$")
_PYTHON_BIN_RE = re.compile(r"^(?:/\S*/)?python[0-9.]*$")
# -mpip のように -m と値がくっついた形
_PYTHON_DASH_M_RE = re.compile(r"^-m(.+)$")
# uvx / uv tool run / pipx など、pip を間接的に起動しうるランナー
_PIP_RUNNERS = {"uvx", "pipx"}
# 上記ランナーで値を取るオプション。値を実行対象と誤認しないよう読み飛ばす
_PIP_RUNNER_VALUE_OPTS = {
    "--from", "--with", "--with-editable", "--spec", "--index", "--index-url",
    "--extra-index-url", "--constraint", "--python", "-p", "--pip-args",
    "--find-links", "-f", "--refresh-package",
}


def check_pip_redirect(cmd: str) -> str | None:
    """pip / python -m pip の直接使用を uv/uvx にリダイレクトする。

    ポリシー照合と同じ normalize を通してから各セグメントの先頭トークンを見るので、
    以下の抜け道をすべて塞ぐ:

      * ``cd foo && pip install x``  (生文字列の先頭アンカーだと素通りしていた)
      * ``pip3 install x``           (``pip\\b`` が ``pip3`` に一致しなかった)
      * ``python3 -m pip install x`` (``\\bpython\\b`` が ``python3`` に一致しなかった)
      * ``python3 -mpip install x``  (``-m`` と値がくっついた形)
      * ``/usr/bin/pip install x``   (絶対パス指定)
      * ``uvx pip install x``        (ランナー経由)
      * ``uv pip install x`` は許可 (uv のサブコマンドであり pip 本体ではない)
    """
    segments = (
        _policy.normalize(cmd) if _policy is not None else [cmd]
    )
    for segment in segments:
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if _PIP_BIN_RE.match(head):
            return (
                "pip の直接使用は禁止されています。uv / uvx を使用してください。\n"
                f"{_pip_suggestion(segment)}"
            )
        if head in _PIP_RUNNERS and len(tokens) > 1:
            # uvx pip install ... / pipx run pip ...
            # `--from pkg` のように値を取るオプションは、その値ごと読み飛ばす
            # (読み飛ばさないと値を実行対象と誤認して検査が止まる)
            i = 1
            # `pipx run pkg` の run のように、実行対象の前に挟まるサブコマンド
            if head == "pipx" and i < len(tokens) and tokens[i] == "run":
                i += 1
            while i < len(tokens):
                token = tokens[i]
                if token.startswith("-"):
                    if "=" not in token and token in _PIP_RUNNER_VALUE_OPTS:
                        i += 2
                    else:
                        i += 1
                    continue
                if _PIP_BIN_RE.match(_basename(token)):
                    return (
                        f"`{head}` 経由の pip 実行は禁止されています。"
                        "uv / uvx を使用してください。\n"
                        f"{_pip_suggestion(segment)}"
                    )
                break
        if _PYTHON_BIN_RE.match(head):
            for i, token in enumerate(tokens[1:], start=1):
                # -m pip (値が別トークン)
                if token == "-m" and i + 1 < len(tokens):
                    if _PIP_BIN_RE.match(_basename(tokens[i + 1])):
                        return (
                            f"`{head} -m pip` は禁止されています。"
                            "uv / uvx を使用してください。\n"
                            f"{_pip_suggestion(segment)}"
                        )
                # -mpip (値がくっついた形)
                m = _PYTHON_DASH_M_RE.match(token)
                if m and _PIP_BIN_RE.match(_basename(m.group(1))):
                    return (
                        f"`{head} -m pip` は禁止されています。"
                        "uv / uvx を使用してください。\n"
                        f"{_pip_suggestion(segment)}"
                    )
    return None


def check_policy_loaded(cmd: str) -> str | None:
    """ポリシー設定を読めないときは fail-closed で拒否する。

    以前は import 失敗時に ``_policy = None`` として全チェックを
    素通りさせていたため、``~/.config/agents/`` の破損 (docs のトラブルシュートに
    ある ``__pycache__`` 由来の import 失敗など) で **全ガードが無言で消えて**いた。
    ここで止めることで、壊れていることが必ず表面化する。

    モジュールが読めても、期待する API やポリシーの中身が欠けていれば同様に拒否する。
    """
    if _policy is None or _POLICY_IMPORT_ERROR is not None:
        detail = f": {_POLICY_IMPORT_ERROR}" if _POLICY_IMPORT_ERROR else ""
        return (
            f"ポリシーモジュールを読み込めませんでした ({_AGENTS_DIR}/command_policy.py){detail}。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行し、"
            f"`{_AGENTS_DIR}/__pycache__/` が残っていれば削除してください。"
        )
    for name in ("normalize", "find_match", "load_deny", "load_ask"):
        if not callable(getattr(_policy, name, None)):
            return (
                f"ポリシーモジュールに `{name}` がありません。\n"
                "安全のため bash コマンドを拒否しています。\n"
                "対処: `chezmoi apply ~/.config/agents` を実行してください。"
            )
    if not Path(_policy.DEFAULT_COMMON_PATH).is_file():
        return (
            f"ポリシー定義が見つかりません ({_policy.DEFAULT_COMMON_PATH})。\n"
            "安全のため bash コマンドを拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
    # deny / ask が空なら、設定が壊れているか読めていない
    try:
        deny = _policy.load_deny()
        ask = _policy.load_ask()
    except Exception as exc:
        return (
            f"ポリシー定義を解釈できませんでした ({exc})。\n"
            "安全のため bash コマンドを拒否しています。"
        )
    if not isinstance(deny, list) or not isinstance(ask, list):
        return (
            "ポリシー定義の deny / ask がリストではありません。\n"
            "安全のため bash コマンドを拒否しています。"
        )
    if not deny:
        return (
            f"ポリシー定義に [bash] deny がありません ({_policy.DEFAULT_COMMON_PATH})。\n"
            "設定が壊れている可能性があるため、安全のため拒否しています。\n"
            "対処: `chezmoi apply ~/.config/agents` を実行してください。"
        )
    return None


_PIPE_TO_SHELL_RE = re.compile(
    r"\|\s*(?:sudo\s+)?(?:/\S*/)?(?:sh|bash|zsh|dash|ksh|fish|ash|python[0-9.]*|perl|ruby|node)\b"
    r"(?!\s+[^\s|&;<>-])",
)


def check_pipe_to_shell(cmd: str) -> str | None:
    """`curl ... | sh` のように取得したものをそのまま実行していないか。

    引数付きの `| bash script.sh` は対象外 (スクリプトを渡しているだけで、
    パイプの内容をコードとして実行しているわけではない)。
    """
    if _PIPE_TO_SHELL_RE.search(cmd):
        return (
            "取得した内容をそのままシェル/インタプリタに流し込んでいます。\n"
            f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
            "内容を検証できないため許可されていません。\n"
            "一度ファイルに保存して内容を確認してから実行してください。"
        )
    return None


def check_git_add_sensitive(cmd: str) -> str | None:
    """`git add .env` のようにセンシティブファイルをバージョン管理に載せていないか"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if len(tokens) < 3:
            continue
        if _basename(tokens[0]) != "git" or tokens[1] not in ("add", "stage"):
            continue
        for token in tokens[2:]:
            if token.startswith("-"):
                continue
            reason = _is_sensitive_token(token)
            if reason:
                return (
                    f"センシティブなファイルを git に追加しようとしています ({reason})。\n"
                    "秘密情報はコミットせず、.gitignore に追加してください。"
                )
    return None


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# heredoc 本文がシェルコマンドとして実行されるもの
_HEREDOC_SHELL_BINS = {
    "bash", "sh", "zsh", "ksh", "dash", "ash", "fish", "csh", "tcsh",
    "env", "sudo", "eval", "source", ".",
}
# heredoc 本文がインタプリタのコードとして実行されるもの
_HEREDOC_CODE_BINS = {
    "python", "python2", "python3", "perl", "ruby", "node", "php",
    "Rscript", "osascript",
}


def split_heredoc_body(cmd: str) -> str:
    """heredoc 本文のうち実行されない部分を取り除いた検査対象を返す。

    `cat <<'EOF' > note.md` の本文はファイルに書かれるだけでシェルには
    渡らない。これをコマンドとして照合すると、ドキュメントに書いた
    危険なコマンドの例示で誤検知する。本文が実行される形のときだけ残す。
    インタプリタに渡る本文は `-c` 形式に組み替えて、インラインコードの
    チェックが効くようにする。
    """
    lines = cmd.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        matches = _HEREDOC_RE.findall(line)
        i += 1
        if not matches:
            continue

        kind = None
        for token in line.split():
            head = re.sub(r"[0-9.]+$", "", _basename(token.strip("'\"()`;|&")))
            if head in _HEREDOC_SHELL_BINS:
                kind = "shell"
                break
            if head in _HEREDOC_CODE_BINS:
                kind = "code"
                break

        delimiters = {delim for _, delim in matches}
        body: list[str] = []
        while i < len(lines) and lines[i].strip() not in delimiters:
            body.append(lines[i])
            i += 1
        if i < len(lines):
            terminator = lines[i]
            i += 1
        else:
            terminator = None

        if kind == "shell":
            kept.extend(body)
        elif kind == "code":
            kept.append("python3 -c " + " ".join(part.strip() for part in body))
        if terminator is not None:
            kept.append(terminator)
    return "\n".join(kept)


def expand_cd_targets(cmd: str) -> str:
    """`cd <dir> && <cmd> <relpath>` の相対パスを結合した変種を返す。

    `cd ~/.ssh && cat id_rsa` のように、作業ディレクトリを移してから
    相対パスで触ると、パス単体ではセンシティブ判定に掛からない。
    検査用に `cat ~/.ssh/id_rsa` 相当の文字列を組み立てて併せて見る。
    """
    variants: list[str] = []
    for chunk in re.split(r"\n+", cmd):
        parts = re.split(r"&&|\|\||;", chunk)
        cwd = None
        for part in parts:
            tokens = part.split()
            if not tokens:
                continue
            head = _basename(tokens[0])
            if head == "cd" and len(tokens) >= 2:
                cwd = tokens[1].strip("'\"")
                continue
            if cwd is None:
                continue
            rebuilt = [tokens[0]]
            for token in tokens[1:]:
                if token.startswith(("-", "/", "~", "$")):
                    rebuilt.append(token)
                else:
                    rebuilt.append(f"{cwd.rstrip('/')}/{token}")
            variants.append(" ".join(rebuilt))
    return "\n".join(variants)


def _is_inline_code_segment(segment: str) -> bool:
    """このセグメントがインタプリタへコード文字列を渡す形かどうか。

    `python3 -c "..."` / `perl -e '...'` のほか、
    `uv run python -c ...` のようにランナー経由の形も拾う。
    """
    return _inline_code_head(segment) is not None


def _inline_code_head(segment: str) -> str | None:
    """インラインコードを実行するインタプリタ名を返す (無ければ None)。"""
    tokens = segment.split()
    for i, token in enumerate(tokens):
        candidate = re.sub(r"[0-9.]+$", "", _basename(token))
        if candidate in _INLINE_CODE_BINS:
            rest = tokens[i + 1:]
            if any(t in _INLINE_CODE_FLAGS for t in rest):
                return candidate
            return None
    return None


def check_interpreter_inline_code(cmd: str) -> str | None:
    """`python3 -c "..."` / `perl -e "..."` の中でセンシティブな操作をしていないか。

    normalize は素のコマンド列 (`os.system('git push')` の中身など) を
    取り出せないことがあるため、コード文字列そのものを検査する。
    `uv run python -c ...` のようにランナー経由でも効くよう、元の文字列全体も見る。
    """
    for segment in _segments(cmd):
        head = _inline_code_head(segment)
        if head is None:
            continue
        # コード片にセンシティブなパスや外部実行が含まれていないか
        reason = is_sensitive_path(segment)
        if reason:
            return (
                f"`{head}` のインラインコードがセンシティブなパスを参照しています ({reason})。"
            )
        if _INLINE_EXEC_RE.search(segment):
            return (
                f"`{head}` のインラインコードから外部コマンドを実行しようとしています。\n"
                f"実行しようとしているコマンド: {segment.strip()[:200]}\n"
                "スクリプトファイルに書いて内容を確認できる形にしてください。"
            )
    return None


def check_secret_env_echo(cmd: str) -> str | None:
    """`echo $GITHUB_TOKEN` のようにセンシティブな環境変数を出力していないか。

    値をそのまま画面やファイル、外部へ出す形を止める。
    `echo $HOME` のような通常の変数は対象外。
    シングルクォート内はシェルが展開しないので対象から外す
    (コミットメッセージ等に変数名が出てくるだけのケースを誤検知しないため)。
    """
    unquoted = re.sub(r"'[^']*'", "", cmd)
    for m in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", unquoted):
        name = m.group(1)
        if _SENSITIVE_ENV_RE.search(name):
            return (
                f"センシティブな環境変数 `${name}` を展開しようとしています。\n"
                f"実行しようとしているコマンド: {cmd.strip()[:200]}\n"
                "値を画面や外部に出さない形で扱ってください。"
            )
    return None


def check_history_access(cmd: str) -> str | None:
    """`history` でシェル履歴を読み出していないか (過去の秘密が残っている)。"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        if _basename(tokens[0]) in ("history", "fc"):
            return (
                "シェル履歴には過去に入力した秘密が残っている可能性があるため、"
                "参照は許可されていません。"
            )
    return None


def check_guard_tampering(cmd: str) -> str | None:
    """hook や permission 設定そのものを無効化しようとしていないか。

    コマンドによる変更 (`rm` / `chmod` など) に加え、リダイレクトによる
    上書き (`> ~/.claude/settings.json`) も検出する。
    """
    targets = ("/.claude/hooks", "/.claude/settings.json", "/.copilot/hooks",
               "/.copilot/permissions-config.json", "/.config/agents",
               "/.git/config", "/.git/hooks", ".git/config", ".git/hooks")

    def _hits(token: str) -> bool:
        expanded = os.path.normpath(
            token.strip("'\"").replace("~", os.path.expanduser("~"), 1)
        )
        return any(t in expanded for t in targets)

    # リダイレクト先がガード設定なら、どのコマンドでも上書きになる
    for m in re.finditer(r"[0-9]*>{1,2}\s*(\S+)", cmd):
        if _hits(m.group(1)):
            return (
                f"エージェントのガード設定 (`{m.group(1)}`) を上書きしようとしています。\n"
                "hook や permission の無効化に繋がるため許可されていません。"
            )

    # インラインコードの中でパスを直接触る形 (`open('...', 'w')` など)。
    # インラインコードは読み書きの区別が静的に付かないので一律で止める。
    #
    # ★ この走査はコマンド全体ではなく、インタプリタのインラインコード
    #   セグメントに限定する。全体を走査すると、閉じ引用符と次の開き引用符の
    #   間 (実際にはクォートされていないシェルコード) を 1 つの引用文字列と
    #   誤認する。例: `echo "a"; ls ~/.config/agents; echo "b"` の
    #   `; ls ~/.config/agents; echo ` が引用文字列として一致してしまい、
    #   読み取りしかしていないコマンドが拒否されていた。
    for segment in _segments(cmd):
        if not _is_inline_code_segment(segment):
            continue
        for m in re.finditer(
            r"""['"]([^'"]*(?:\.claude|\.copilot|/agents|\.git/)[^'"]*)['"]""", segment
        ):
            if _hits(m.group(1)):
                return (
                    f"エージェントのガード設定 (`{m.group(1)}`) を操作しようとしています。\n"
                    "インラインコードは読み書きの区別が付かないため許可されていません。\n"
                    f"代替: 内容を見るだけなら `cat {m.group(1)}` や "
                    f"`grep <pattern> {m.group(1)}` を使ってください。\n"
                    "設定を変えたい場合は chezmoi のソースを編集してください。"
                )

    # 環境変数の差し替えで hook の読み込み先やモジュール解決を乗っ取る形
    for m in re.finditer(
        r"\b(AGENTS_CONFIG_DIR|PYTHONPATH|CLAUDE_[A-Z_]*HOOK[A-Z_]*)=(\S*)", cmd
    ):
        name, value = m.group(1), m.group(2)
        if name == "PYTHONPATH":
            expanded = value.strip("'\"").replace("~", os.path.expanduser("~"), 1)
            absolute = os.path.normpath(os.path.join(os.getcwd(), expanded))
            # プロジェクト内への追加は正当なので、外部を指す場合だけ止める
            if not absolute.startswith(os.getcwd() + os.sep):
                return (
                    f"`PYTHONPATH={value}` で hook のモジュール解決先を差し替えようと"
                    "しています。\nリポジトリ外のパスの指定は許可されていません。"
                )
            continue
        return (
            f"`{name}` を差し替えて hook の設定読み込み先を変えようとしています。\n"
            "hook や permission の無効化に繋がるため許可されていません。"
        )

    mutating = {
        "rm", "rmdir", "unlink", "mv", "cp", "chmod", "chown", "truncate",
        "shred", "ln", "sed", "tee", "dd", "install",
    }
    # chezmoi は破壊的サブコマンドのときだけ対象にする (diff / status は無害)
    chezmoi_mutating = {"forget", "destroy", "remove", "unmanage"}
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "chezmoi":
            if len(tokens) < 2 or tokens[1] not in chezmoi_mutating:
                continue
        elif head not in mutating:
            continue
        for token in tokens[1:]:
            if _hits(token):
                return (
                    f"エージェントのガード設定 (`{token}`) を変更しようとしています。\n"
                    "hook や permission の無効化に繋がるため許可されていません。\n"
                    "設定を変えたい場合は chezmoi のソースを編集してください。"
                )
    return None


def check_reverse_shell(cmd: str) -> str | None:
    """リバースシェル・待ち受けソケットの形を検出する。

    `/dev/tcp` は bash 組み込みなので外部コマンドの照合では捕まらない。
    `nc` などは疎通確認に使うため、実行系・待ち受け系フラグのときだけ止める。
    """
    m = re.search(r"/dev/(?:tcp|udp)/[^/\s]+/\d+", cmd)
    if m:
        return (
            f"`{m.group(0)}` へのシェルリダイレクトはリバースシェルの形です。\n"
            "外部への接続を伴うシェル実行は許可されていません。"
        )

    listeners = {"nc", "netcat", "ncat", "socat", "telnet"}
    exec_flags = ("-e", "-c", "--exec", "--sh-exec", "--lua-exec")
    listen_flags = ("-l", "-lp", "-lvp", "--listen", "-L")
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head not in listeners:
            continue
        for token in tokens[1:]:
            if token in exec_flags or token.startswith("EXEC:"):
                return (
                    f"`{head} {token}` はコマンドを外部接続に紐付ける形です。\n"
                    "リバースシェルに繋がるため許可されていません。"
                )
            if token in listen_flags:
                return (
                    f"`{head} {token}` は待ち受けソケットを開く形です。\n"
                    "外部からの侵入経路になるため許可されていません。"
                )
    return None


def check_shell_startup_write(cmd: str) -> str | None:
    """シェル起動ファイルや認証ファイルへの書き込みを検出する。

    追記されると以後のすべてのシェルで任意コードが走るため、永続化の
    典型的な足がかりになる。読み取りは許可する。
    """
    targets = (
        ".bashrc", ".bash_profile", ".bash_login", ".zshrc", ".zshenv",
        ".zprofile", ".profile", ".login", ".cshrc", ".kshrc",
        "authorized_keys", "known_hosts", ".ssh/config", ".netrc",
        "crontab", ".gitconfig",
    )

    def _hits(token: str) -> str | None:
        cleaned = token.strip("'\"")
        for target in targets:
            if cleaned.endswith(target) or f"/{target}" in cleaned:
                return target
        return None

    for m in re.finditer(r"[0-9]*>{1,2}\s*(\S+)", cmd):
        hit = _hits(m.group(1))
        if hit:
            return (
                f"シェル起動ファイル `{m.group(1)}` へ書き込もうとしています。\n"
                "以後のシェルで任意コードが走るため許可されていません。"
            )

    writers = {"tee", "sed", "dd", "install", "truncate", "ln", "cp", "mv"}
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "sed" and not any(t.startswith("-i") for t in tokens[1:]):
            continue
        if head not in writers:
            continue
        for token in tokens[1:]:
            hit = _hits(token)
            if hit:
                return (
                    f"シェル起動ファイル `{token}` を書き換えようとしています。\n"
                    "以後のシェルで任意コードが走るため許可されていません。"
                )
    return None


def check_privilege_escalation(cmd: str) -> str | None:
    """setuid 付与やアカウント/認証設定の変更を検出する。"""
    for segment in _segments(cmd):
        tokens = segment.split()
        if not tokens:
            continue
        head = _basename(tokens[0])
        if head == "chmod":
            for token in tokens[1:]:
                if re.fullmatch(r"[ugo]*\+s|[24][0-7]{3}", token):
                    return (
                        f"`chmod {token}` は setuid/setgid を付与する操作です。\n"
                        "権限昇格に繋がるため許可されていません。"
                    )
        if head in {"usermod", "useradd", "adduser", "groupadd", "passwd",
                    "chpasswd", "visudo", "gpasswd"}:
            return (
                f"`{head}` はアカウント・認証設定を変更する操作です。\n"
                "権限昇格に繋がるため許可されていません。"
            )
    if re.search(r"/etc/(?:sudoers|passwd|shadow|group)", cmd):
        return (
            "認証設定ファイル (/etc 配下) を操作しようとしています。\n"
            "権限昇格に繋がるため許可されていません。"
        )
    return None


def check_encoded_command(cmd: str) -> str | None:
    """デコード結果をそのままシェルへ流す形を検出する。

    `base64 -d | sh` のように、正規化では中身を判定できない経路を塞ぐ。
    """
    decoders = r"(?:base64\s+(?:-d|--decode|-D)|xxd\s+-r|uudecode|openssl\s+enc\s+-d)"
    shells = r"(?:ba|z|k|da)?sh\b|python3?\b|perl\b|ruby\b|node\b"
    if re.search(rf"{decoders}[^|]*\|\s*(?:{shells})", cmd):
        return (
            "デコード結果を直接シェルに渡そうとしています。\n"
            "内容を検査できないため許可されていません。"
            "デコード結果をファイルに書き出して確認してから実行してください。"
        )
    if re.search(r"printf\s+['\"][^'\"]*\\x[0-9a-fA-F]{2}[^'\"]*['\"]\s*\|\s*"
                 rf"(?:{shells})", cmd):
        return (
            "エスケープ列で組み立てたコマンドをシェルに渡そうとしています。\n"
            "内容を検査できないため許可されていません。"
        )
    return None


def check_git_config_write(cmd: str) -> str | None:
    """任意コマンド実行や資格情報の奪取に繋がる git config の書き込みを止める。

    `git config alias.p push` のように設定キーへ値を書くと、以後 `git p` で
    deny 対象のコマンドを実行できてしまう。キー名は接頭辞が可変なので、
    トークン完全一致のポリシー照合では拾えない。
    """
    dangerous = (
        "alias.", "core.hookspath", "core.editor", "core.pager",
        "core.sshcommand", "core.fsmonitor", "credential.", "url.",
        "filter.", "diff.external", "difftool.", "mergetool.", "pager.",
        "include.path", "includeif.", "sequence.editor", "gpg.program",
        "ssh.variant", "protocol.",
    )
    for segment in _segments(cmd):
        tokens = segment.split()
        if len(tokens) < 3:
            continue
        if _basename(tokens[0]) != "git" or tokens[1] != "config":
            continue
        rest = [t for t in tokens[2:] if not t.startswith("-")]
        if not rest:
            continue
        key = rest[0].lower()
        if any(key.startswith(prefix) for prefix in dangerous) and len(rest) > 1:
            return (
                f"`git config {rest[0]}` は任意コマンドの実行や資格情報の取得に"
                "繋がる設定です。\nエージェント経由での変更は許可されていません。"
            )
    return None


def check_block_device_write(cmd: str) -> str | None:
    """`dd of=/dev/sda` のようにブロックデバイスへ直接書き込んでいないか。"""
    for segment in _segments(cmd):
        m = re.search(r"\bof=(/dev/\S+)", segment)
        if m and not re.match(r"^/dev/(?:null|stdout|stderr|tty|zero)$", m.group(1)):
            return (
                f"ブロックデバイス `{m.group(1)}` へ直接書き込もうとしています。\n"
                "ディスクを破壊する操作は許可されていません。"
            )
    return None


def check_policy_deny(cmd: str) -> str | None:
    """common.toml の bash.deny に該当すれば block する.

    Claude Code permission リストの既知バグ (cd && bypass, git -C bypass,
    compound 命令の個別評価欠如) に対する最終防波堤。shell command を
    normalize (cd, git -C, compound 分割) してから pattern match する。
    """
    patterns = _policy.load_deny()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は deny パターンに一致するためブロックされました。\n"
            "このコマンドは common.toml の [bash] deny で禁止されています。"
        )
    return None


def check_policy_ask(cmd: str) -> str | None:
    """common.toml の bash.ask に該当すればユーザー承認を要求する.

    deny と違い、ユーザーが承認すればそのまま実行される。
    deny チェックの後に評価されるので、より具体的な deny パターン
    (例: ``git reset --hard``) が一般形の ask (``git reset``) に優先する。
    """
    patterns = _policy.load_ask()
    matched = _policy.find_match(cmd, patterns)
    if matched:
        return (
            f"`{matched}` は承認が必要な操作です (common.toml の [bash] ask)。\n"
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
_RM_BIN_RE = re.compile(r"^(?:/\S*/)?(?:rm|rmdir|unlink)$")


def _basename(token: str) -> str:
    """``/bin/rm`` -> ``rm``"""
    return token.rsplit("/", 1)[-1] if "/" in token else token


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
    # `~/.ssh` のような秘密領域そのものの削除も承認の対象外
    base = os.path.basename(canonical)
    if base in {".ssh", ".gnupg", ".aws", ".config", ".local", ".git"}:
        return True
    # `$PWD/../..` のように相対で上位へ抜ける形。
    # 実際の解決先は分からないので、`..` が 2 段以上あれば壊滅的とみなす。
    if canonical.count("..") >= 2:
        return True
    return False


def check_rm_root_guard(cmd: str) -> str | None:
    """`rm` がシステム全体・ホーム・親ディレクトリを対象にしていないか。

    `cd /elsewhere && rm -rf /` や `sh -c "rm -rf ~"` のような回避を防ぐため、
    ポリシー照合と同じ normalize を通してから各セグメントを検査する。
    normalize は shlex を通るため ``${HOME}`` の波括弧が落ちることがある。
    元の文字列も併せて検査して取りこぼさないようにする。
    """
    segments = list(_policy.normalize(cmd)) if _policy is not None else []
    segments.append(cmd)
    for segment in segments:
        tokens = segment.split()
        if not tokens or not _RM_BIN_RE.match(_basename(tokens[0])):
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
    check_policy_loaded,      # ★最初に実行: 設定が読めないなら fail-closed
    check_rm_root_guard,      # 壊滅的な削除は承認の余地なし
    # 具体的な代替案を返せるチェックは、汎用の policy_deny より先に置く
    # (先に一致したものがメッセージを決めるため)
    check_pip_redirect,       # pip → uv/uvx (プロジェクト種別を問わず全面禁止)
    check_pipe_to_shell,      # curl ... | sh の類
    check_interpreter_inline_code,  # python -c "os.system(...)" の類
    check_git_add_sensitive,  # git add .env の類
    check_secret_env_echo,    # echo $GITHUB_TOKEN の類
    check_gh_token_exposure,  # gh auth status --show-token
    check_gh_api_sensitive_input,  # gh api -F key=@.env / --input .env
    check_history_access,     # history / fc
    check_guard_tampering,    # hook や settings.json の改変
    check_reverse_shell,      # /dev/tcp や nc -e の類
    check_shell_startup_write,  # .bashrc / authorized_keys への追記
    check_http_dangerous_output,  # curl -o / wget -O で起動・認証設定を上書き
    check_privilege_escalation,  # setuid 付与・sudoers 変更
    check_encoded_command,    # base64 -d | sh の類
    check_git_config_write,   # git config alias.x / core.hooksPath の類
    check_block_device_write, # dd of=/dev/sda の類
    check_find_root_guard,    # find ~ -delete のような一括削除
    check_policy_deny,        # common.toml の [bash] deny を強制
    check_env_exposure,       # 引数なし環境変数露出は問答無用でブロック
    check_git_c_dangerous,    # -C 経由の deny サブコマンド実行をブロック
    check_file_read,
    check_archive,
    check_curl_file_send,
    check_xargs_pipe,
]

# パスだけを見るチェック。`cd` 展開版に対して二度目の適用をする
_PATH_CHECKS = [
    check_file_read,
    check_guard_tampering,
    check_shell_startup_write,
    check_archive,
    check_curl_file_send,
]

# 承認を求めるチェック（ユーザーが許可すればそのまま実行される）
ASK_CHECKS = [
    check_policy_ask,         # common.toml の [bash] ask
    check_gh_api_mutation,    # REST / GraphQL の mutation と判定不能形式
    check_curl_wget_mutation, # curl/wget の mutation と判定不能形式
    check_find_dangerous,     # find -exec rm / -delete によるファイル削除
]


def main() -> None:
    # ── 自前のタイムアウト ─────────────────────────────────────────
    # hook の実行が設定の timeout を超えると CLI 側は hook をスキップする
    # (= 素通り)。異常に長いコマンドや病的な入力でそうならないよう、
    # 余裕をもって自分で打ち切り、安全側 (deny) に倒す。
    def _on_timeout(signum: int, frame: object) -> None:  # pragma: no cover
        emit_pretool_deny(
            "[hook blocked] コマンドの検査が時間内に終わりませんでした。\n"
            "検査できない以上、安全のため拒否しています。\n"
            "コマンドを短く分割して実行してください。"
        )

    try:
        signal.signal(signal.SIGALRM, _on_timeout)
        signal.alarm(_SELF_TIMEOUT_SEC)
    except (AttributeError, ValueError):  # pragma: no cover - Windows など
        pass

    data = read_input()
    if not isinstance(data, dict):
        # 想定外のペイロードでも落とさない (CLI 側が hook 失敗を素通り扱いに
        # することがあるため、例外で終わらせない)
        sys.exit(0)

    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str):
        sys.exit(0)
    if normalize_tool_kind(tool_name) != "bash":
        sys.exit(0)

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)
    cmd = get_command(tool_input)
    if not isinstance(cmd, str) or not cmd:
        sys.exit(0)

    # 長すぎるコマンドは検査コストが跳ね上がる。内容を確認できないので拒否する
    if len(cmd) > _MAX_COMMAND_LEN:
        emit_pretool_deny(
            f"[hook blocked] コマンドが長すぎます ({len(cmd)} 文字)。\n"
            f"{_MAX_COMMAND_LEN} 文字以内に収めるか、スクリプトファイルに書いて"
            "内容を確認できる形にしてください。"
        )

    # heredoc 本文のうち、ファイルに書かれるだけで実行されない部分を外す。
    # ドキュメントに書いた危険なコマンド例で誤検知しないようにするため。
    try:
        cmd = split_heredoc_body(cmd)
    except Exception:  # pragma: no cover - 解析できないときは元の文字列で検査
        pass

    for check in DENY_CHECKS:
        try:
            reason = check(cmd)
        except Exception as exc:  # pragma: no cover - 判定不能なら安全側へ
            emit_pretool_deny(
                f"[hook blocked] コマンドの検査に失敗しました ({check.__name__}: {exc})。\n"
                "検査できない以上、安全のため拒否しています。"
            )
        if reason:
            emit_pretool_deny(f"[hook blocked] {reason}")

    # `cd <dir> && cat <relpath>` のように、作業ディレクトリ経由で相対参照する形。
    # パスを結合した変種を作り、パスを見るチェックだけ改めて適用する。
    try:
        cd_variant = expand_cd_targets(cmd)
    except Exception:  # pragma: no cover
        cd_variant = ""
    if cd_variant:
        for check in _PATH_CHECKS:
            try:
                reason = check(cd_variant)
            except Exception:  # pragma: no cover
                continue
            if reason:
                emit_pretool_deny(f"[hook blocked] {reason}")

    for check in ASK_CHECKS:
        try:
            reason = check(cmd)
        except Exception as exc:  # pragma: no cover
            emit_pretool_deny(
                f"[hook blocked] コマンドの検査に失敗しました ({check.__name__}: {exc})。\n"
                "検査できない以上、安全のため拒否しています。"
            )
        if reason:
            emit_pretool_ask(f"[hook] 承認が必要です\n{reason}")

    sys.exit(0)


if __name__ == "__main__":
    main()
