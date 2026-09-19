"""``gh api`` の REST method / GraphQL operation を解析する。

読み取り (GET / HEAD / query) は通し、mutation と判定不能な形式だけを
承認対象にする。
"""
from __future__ import annotations

import re
import shlex

from . import tables
from ._shared import _basename, _normalize, _option_value, _policy
from .sensitive import _is_sensitive_token

_GH_API_METHOD_FLAGS = tables.as_set("ghapi", "gh_api_method_flags")


_GH_API_FIELD_FLAGS = tables.as_set("ghapi", "gh_api_field_flags")


_GH_API_INPUT_FLAGS = tables.as_set("ghapi", "gh_api_input_flags")


_GH_API_VALUE_FLAGS = tables.as_set("ghapi", "gh_api_value_flags")


_GH_API_READ_METHODS = tables.as_set("ghapi", "gh_api_read_methods")


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
            for segment in _normalize(raw_segment)
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
    for segment in _normalize(cmd):
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
