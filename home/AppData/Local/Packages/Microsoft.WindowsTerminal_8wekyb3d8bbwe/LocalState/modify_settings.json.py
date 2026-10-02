#!/usr/bin/env python3
# Windows Terminal の settings.json に LANG2 (VK_IME_OFF) の無効化を 1 件だけ足す。
# see docs/spec/structure.md#windows-terminal
from __future__ import annotations

import json
import sys
from typing import Any

ACTION_ID = "User.ignoreImeOff"
KEYS = "vk(26)"
COMMAND = {"action": "adjustOpacity", "opacity": 0, "relative": True}
BOM = "\ufeff"
WHITESPACE = " \t\r\n"


class JsoncError(ValueError):
    pass


def _skip_ws(text: str, i: int) -> int:
    """空白とコメントを読み飛ばす。"""
    while i < len(text):
        if text[i] in WHITESPACE:
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise JsoncError("unterminated comment")
            i = end + 2
        else:
            break
    return i


def _skip_string(text: str, i: int) -> int:
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    raise JsoncError("unterminated string")


def _scan_container(text: str, i: int) -> tuple[int, list[tuple[int, int, int]]]:
    """``{`` / ``[`` から始まる値を読み、終端の位置と要素の (開始, 値の開始, 終端) を返す。"""
    close = "}" if text[i] == "{" else "]"
    items: list[tuple[int, int, int]] = []
    i = _skip_ws(text, i + 1)
    while True:
        if i >= len(text):
            raise JsoncError("unterminated container")
        if text[i] == close:
            return i + 1, items
        start = i
        if close == "}":
            if text[i] != '"':
                raise JsoncError(f"expected key at {i}")
            i = _skip_ws(text, _skip_string(text, i))
            if i >= len(text) or text[i] != ":":
                raise JsoncError(f"expected ':' at {i}")
            i = _skip_ws(text, i + 1)
        value_start = i
        i = _skip_value(text, i)
        items.append((start, value_start, i))
        i = _skip_ws(text, i)
        if i < len(text) and text[i] == ",":
            i = _skip_ws(text, i + 1)
        elif i >= len(text) or text[i] != close:
            raise JsoncError(f"expected ',' or '{close}' at {i}")


def _skip_value(text: str, i: int) -> int:
    if i >= len(text):
        raise JsoncError("unexpected end")
    if text[i] == '"':
        return _skip_string(text, i)
    if text[i] in "{[":
        return _scan_container(text, i)[0]
    start = i
    while i < len(text) and text[i] not in WHITESPACE + ",]}/":
        i += 1
    if i == start:
        raise JsoncError(f"unexpected character at {i}")
    return i


def _parse(text: str, start: int, end: int) -> Any:
    """コメントと末尾カンマを除いて JSON として読む。"""
    out: list[str] = []
    i = start
    while i < end:
        j = _skip_ws(text, i)
        if j > i:
            out.append(" ")
            i = j
            continue
        if text[i] == '"':
            j = _skip_string(text, i)
            out.append(text[i:j])
            i = j
        elif text[i] == ",":
            nxt = _skip_ws(text, i + 1)
            if nxt >= end or text[nxt] not in "]}":
                out.append(",")
            i += 1
        else:
            out.append(text[i])
            i += 1
    return json.loads("".join(out))


def _line_head(text: str, pos: int) -> str:
    return text[text.rfind("\n", 0, pos) + 1 : pos]


def _line_indent(text: str, pos: int) -> str:
    head = _line_head(text, pos)
    return head[: len(head) - len(head.lstrip(" \t"))]


def _insert(
    text: str,
    open_pos: int,
    close_end: int,
    items: list[tuple[int, int, int]],
    value: str,
    unit: str,
    newline: str,
) -> str:
    """コンテナの末尾へ ``value`` を足す。既存の要素・コメント・書式は変えない。"""
    close_pos = close_end - 1
    close_indent = _line_indent(text, close_pos)
    if items and _line_head(text, items[0][0]).strip(" \t") == "":
        indent = _line_head(text, items[0][0])
    else:
        indent = close_indent + unit

    pos = close_pos
    while pos > open_pos + 1 and text[pos - 1] in WHITESPACE:
        pos -= 1
    inserted = newline + indent + (newline + indent).join(value.split("\n"))
    if "\n" not in text[pos:close_pos]:
        inserted += newline + close_indent

    needs_comma = bool(items) and text[_skip_ws(text, items[-1][2])] != ","
    text = text[:pos] + inserted + text[pos:]
    if needs_comma:
        last_end = items[-1][2]
        text = text[:last_end] + "," + text[last_end:]
    return text


def _norm_keys(keys: Any) -> list[str]:
    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list):
        return []
    return [k.replace(" ", "").lower() for k in keys if isinstance(k, str)]


def _dumps(value: Any, unit: str) -> str:
    return json.dumps(value, ensure_ascii=False, indent=unit or None)


def update(text: str) -> tuple[str, str | None]:
    """更新後の本文と、変更しなかった理由 (警告) を返す。"""
    newline = "\r\n" if "\r\n" in text else "\n"
    if text.strip() == "":
        text = "{" + newline + "}" + newline

    root_open = _skip_ws(text, 0)
    if root_open >= len(text) or text[root_open] != "{":
        raise JsoncError("top level is not an object")
    root_end, members = _scan_container(text, root_open)

    spans: dict[str, tuple[int, int]] = {}
    for start, value_start, end in members:
        spans[_parse(text, start, _skip_string(text, start))] = (value_start, end)

    def value_of(key: str) -> Any:
        if key not in spans:
            return None
        return _parse(text, *spans[key])

    actions = value_of("actions")
    keybindings = value_of("keybindings")
    if actions is not None and not isinstance(actions, list):
        return text, "'actions' is not an array"
    if keybindings is not None and not isinstance(keybindings, list):
        return text, "'keybindings' is not an array"
    actions = actions or []
    new_format = isinstance(keybindings, list) or not members

    action_ids = {a.get("id"): a for a in actions if isinstance(a, dict)}
    ours_bound = False
    for entry in actions + (keybindings or []):
        if not isinstance(entry, dict) or KEYS not in _norm_keys(entry.get("keys")):
            continue
        is_ours = entry.get("id") == ACTION_ID or (
            "id" not in entry and entry.get("command") == COMMAND
        )
        if not is_ours:
            target = entry.get("id", entry.get("command"))
            return text, f"{KEYS} is already bound to {json.dumps(target)}"
        ours_bound = True

    if ACTION_ID in action_ids and action_ids[ACTION_ID].get("command") != COMMAND:
        return text, f"action id {ACTION_ID} already exists with another command"

    unit = (_line_indent(text, members[0][0]) if members else "") or "    "

    if not new_format:
        if ours_bound:
            return text, None
        additions = [("actions", {"command": COMMAND, "keys": KEYS})]
    else:
        additions = []
        if ACTION_ID not in action_ids:
            additions.append(("actions", {"command": COMMAND, "id": ACTION_ID}))
        if not ours_bound:
            additions.append(("keybindings", {"id": ACTION_ID, "keys": KEYS}))

    # 後ろのコンテナから足して、前のコンテナの位置をずらさない
    def position(item: tuple[str, Any]) -> int:
        return spans[item[0]][0] if item[0] in spans else len(text)

    for key, entry in sorted(additions, key=position, reverse=True):
        if key in spans:
            value_start, value_end = spans[key]
            _, items = _scan_container(text, value_start)
            text = _insert(text, value_start, value_end, items, _dumps(entry, unit), unit, newline)
        else:
            member = f"{json.dumps(key)}: " + _dumps([entry], unit)
            root_end, members = _scan_container(text, root_open)
            text = _insert(text, root_open, root_end, members, member, unit, newline)
    return text, None


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8")
    bom = BOM if raw.startswith(BOM) else ""
    try:
        updated, warning = update(raw[len(bom) :])
    except (JsoncError, ValueError) as error:
        updated, warning = raw[len(bom) :], f"cannot parse settings.json ({error})"
    if warning:
        print(
            f"warning: Windows Terminal: {warning}; left settings.json unchanged",
            file=sys.stderr,
        )
        sys.stdout.buffer.write(raw.encode("utf-8"))
        return 0
    sys.stdout.buffer.write((bom + updated).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
