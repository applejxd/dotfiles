"""curl / wget の字句解析と、HTTP 転送に関する判定。

curl のオプションは短縮・連結・``--long=value`` と形が多いため、ここだけ
本格的なトークン解析を持つ。フラグ名の一覧は ``tables.toml`` にある。
"""
from __future__ import annotations

import ipaddress
import os
import re
import shlex
from urllib.parse import urlsplit

from . import tables
from ._shared import (
    _FETCH_COMMAND_RE,
    _basename,
    _normalize,
    _payload_source,
    _policy,
    _take_option_value,
)
from .sensitive import _is_sensitive_token

_HTTP_READ_METHODS = tables.as_set("http", "http_read_methods")


_CURL_DATA_FLAGS = tables.as_set("http", "curl_data_flags")


_CURL_OUTPUT_FLAGS = tables.as_set("http", "curl_output_flags")


_CURL_VALUE_FLAGS = tables.as_set("http", "curl_value_flags")


_CURL_LOCAL_BLOCKING_FLAGS = tables.as_set("http", "curl_local_blocking_flags")


_CURL_NO_VALUE_SHORT_FLAGS = set("012346#BaJMRZfFsSLIikvVqgGNnO")


_CURL_CONFIG_FLAGS = tables.as_set("http", "curl_config_flags")


_WGET_BODY_FLAGS = tables.as_set("http", "wget_body_flags")


_WGET_OUTPUT_FLAGS = tables.as_set("http", "wget_output_flags")


_WGET_CONFIG_FLAGS = tables.as_set("http", "wget_config_flags")


_NON_EXECUTING_HTTP_PREFIXES = tables.as_set("http", "non_executing_http_prefixes")


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
                matched_kind = short if short and matched_kind.startswith(short) else long
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


_LOCAL_URL_SCHEMES = tables.as_set("http", "local_url_schemes")


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
            for segment in _normalize(raw_segment)
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
        # call は他のチェックとも共有されるので、派生した出力先はコピーへ足す
        output_targets = list(output_targets)
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


def _fetched_output_paths(cmd: str) -> set[str]:
    """curl / wget が書き出すローカルパスと、その basename を返す。

    `-o` / `-O` / `--output-dir` に加えて、`curl URL > a.sh` のような
    リダイレクトと、`wget URL` が URL の basename に保存する既定動作も見る。
    """
    paths: set[str] = set()

    def _add(value: str) -> None:
        cleaned = value.strip("'\"")
        if cleaned and cleaned not in {"-", "/dev/stdout", "/dev/null"}:
            paths.add(cleaned)

    for call in _http_transfer_calls(cmd):
        outputs = call["output_targets"]
        if isinstance(outputs, list):
            for output in outputs:
                if isinstance(output, str):
                    _add(output)
        urls = call["urls"] if isinstance(call["urls"], list) else []
        # `curl -O` と、出力先を指定しない `wget` は URL の basename に保存する
        derives_name = call["remote_name"] is True or (
            call["tool"] == "wget" and not outputs
        )
        if derives_name:
            for url in urls:
                if not isinstance(url, str):
                    continue
                name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
                if name:
                    _add(name)

    # 取得と同じセグメント内のリダイレクト先
    if _policy is not None:
        for segment in _policy.split_command_segments(cmd):
            if not _FETCH_COMMAND_RE.search(segment):
                continue
            for m in re.finditer(r"[0-9]*>{1,2}\|?\s*([^\s&][^\s;&|)<>]*)", segment):
                _add(m.group(1))

    return set(paths) | {os.path.basename(p) for p in paths}
