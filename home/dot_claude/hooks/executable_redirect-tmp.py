#!/usr/bin/env python3
"""
Agent (Claude Code / Copilot CLI) PreToolUse hook: /tmp への書き込みを ./.tmp へリダイレクト

対象 kind:
  - bash          : コマンドが /tmp/ (または $TMPDIR/$TEMP/$TMP) へ「書き込もう」
                     としている場合のみ block する。``cat``/``ls``/``grep``/``df``
                     のような読み取り専用コマンドはそのまま通す (副作用が無いため)。
  - create / edit : path が /tmp/ で始まる場合 (新規作成・編集は常に書き込みなので
                     無条件で block)

view (Read) は kind として扱わない (常に許可): 読み取りには副作用が無く、
``./.tmp`` へ誘導する理由 (書き込みの分離・承認プロンプト削減) が当てはまらない。

例外 (allowlist):
  - ``/tmp/claude-*/...`` 配下のパスは Claude Code のバックグラウンドタスクや
    shell snapshot などが利用するため通過させる (read/write 問わず)。

出力規約は ``agent_compat.emit_pretool_deny`` に委譲する (両ツール対応)。
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

# 同一ディレクトリの lib/ にあるヘルパを import
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from agent_compat import (  # noqa: E402
    emit_pretool_deny,
    get_command,
    get_path,
    normalize_tool_kind,
    read_input,
)

# ~/.config/agents/ (chezmoi 管理) の command_policy.normalize() を使い、
# bash コマンドを `&&`/`;`/`|` 等で分割してから read/write を判定する。
# check_bash.py と同じ import 方法 (AGENTS_CONFIG_DIR で差し替え可能)。
# 読み込めない場合は read/write を判定できないため fail-safe で block する。
_AGENTS_DIR = os.environ.get("AGENTS_CONFIG_DIR")
if not _AGENTS_DIR:
    _CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    _AGENTS_DIR = os.path.join(_CONFIG_HOME, "agents")
sys.path.insert(0, _AGENTS_DIR)
try:
    import command_policy as _policy  # noqa: E402
except Exception:  # noqa: BLE001 - 読み込めなくても hook 自体は動かす (fail-safe で block)
    _policy = None  # type: ignore[assignment]

# /tmp/ リテラル使用を検出するためのパターン群

_TMP_PATH_PREFIX = "/tmp/"

# allowlist: Claude Code が使う /tmp/claude-* 配下 (claude-<uid>/ や
# claude-shell-snapshot-* など) は通過させる
_ALLOWED_TMP_PATTERN = re.compile(r"^/tmp/claude-[^/]+(?:/|$)")

# bash コマンド中の /tmp/ トークン抽出用 (空白や区切り文字までを 1 トークンとみなす)
_TMP_BASH_TOKEN = re.compile(r"/tmp/[^\s;|&'\"`)>{}<]*")

# `>`/`>>` によるリダイレクト先を拾う (check_bash.py の
# check_shell_startup_write と同じ考え方)
_REDIRECT_TARGET_RE = re.compile(r"[0-9]*>{1,2}\s*(\S+)")

# ─── bash コマンドの read-only / write 判定 ─────────────────────────
# 常に書き込みとみなすコマンド (/tmp を対象にしていたら無条件で block)
# 転送先が最後の引数になるもの (cp / mv / install / rsync / ln) は
# _DEST_LAST_COMMANDS で個別に判定するのでここには含めない。
_ALWAYS_WRITE_COMMANDS = {
    "mkdir", "touch", "rm", "rmdir", "unlink", "dd", "tee",
    "truncate", "mktemp",
    "tar", "zip", "unzip", "gzip", "gunzip", "split",
    "chmod", "chown", "chgrp", "git",
}
# 転送先が最後の引数になるコマンド。/tmp が転送元にあるだけなら読み取り。
# (`cp /tmp/x ./y` は /tmp から読み出してリポジトリへ書くので block しない)
_DEST_LAST_COMMANDS = {"cp", "mv", "install", "rsync", "ln"}
# 読み取り専用とみなすコマンド (副作用が無ければ /tmp を対象にしても許可)
_READ_ONLY_BASH_COMMANDS = {
    "cat", "less", "more", "head", "tail",
    "grep", "egrep", "fgrep", "rg", "ag",
    "ls", "tree",
    "wc", "file", "stat", "du", "df",
    "diff", "cmp",
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "b2sum", "cksum",
    "xxd", "hexdump", "od", "strings",
    "readlink", "realpath", "basename", "dirname",
    "nl", "column",
    "jq",
}
# find の書き込み系フラグ (これが無ければ read-only)
_FIND_WRITE_FLAGS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprintf"}

_REDIRECT_MESSAGE = """\
[hook blocked] /tmp/ への書き込みが検出されました。
プロジェクトローカルの一時ディレクトリ ./.tmp/ を代わりに使用してください。

  対処手順:
    1. mkdir -p ./.tmp
    2. /tmp/... のパスを ./.tmp/... に置き換えて再実行

  例: /tmp/result.json  →  ./.tmp/result.json

  例外:
    - /tmp/claude-*/ 配下 (Claude Code バックグラウンドタスク等) は許可されます。
    - 読み取り専用の操作 (cat, ls, grep, df 等) は /tmp でもそのまま許可されます。
"""


def _blocked(path_hint: str) -> None:
    emit_pretool_deny(f"{_REDIRECT_MESSAGE}\n  検出パス/コマンド: {path_hint}")


def _is_allowed_tmp_path(path: str) -> bool:
    return bool(_ALLOWED_TMP_PATTERN.match(path))


def _has_unallowed_tmp_token(text: str) -> bool:
    return any(
        not _is_allowed_tmp_path(match.group(0))
        for match in _TMP_BASH_TOKEN.finditer(text)
    )


def _redirect_targets_tmp(cmd: str) -> bool:
    """`>`/`>>` のリダイレクト先が /tmp なら True (コマンド種別を問わず書き込み)。"""
    for match in _REDIRECT_TARGET_RE.finditer(cmd):
        target = match.group(1).strip("'\"")
        if target.startswith(_TMP_PATH_PREFIX) and not _is_allowed_tmp_path(target):
            return True
    return False


def _segment_head_and_tokens(segment: str) -> tuple[str, list[str]] | None:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if not tokens:
        return None
    return tokens[0].rsplit("/", 1)[-1], tokens


def _classify_segment(head: str, tokens: list[str]) -> str:
    """このセグメントが /tmp に対して "read" / "write" / "unknown" のどれかを返す。

    "unknown" (未知のコマンドや判定できないもの) は呼び出し側で block 扱いにする
    (fail-safe)。
    """
    if head in _DEST_LAST_COMMANDS:
        # 転送先 (最後の非フラグ引数) が /tmp のときだけ書き込み。
        # /tmp が転送元にあるだけなら読み出しなので許可する。
        operands = [t for t in tokens[1:] if not t.startswith("-")]
        if len(operands) < 2:
            # 引数が足りない / 判定できない形は安全側に倒す
            return "write"
        dest = operands[-1].strip("'\"")
        if dest.startswith(_TMP_PATH_PREFIX) and not _is_allowed_tmp_path(dest):
            return "write"
        return "read"
    if head in _ALWAYS_WRITE_COMMANDS:
        return "write"
    if head == "sed":
        # `-i` (in-place) が無ければ標準出力への変換のみで書き込みは無い
        return "write" if any(t.startswith("-i") for t in tokens[1:]) else "read"
    if head == "curl":
        is_write = any(
            t == "-O" or t.startswith("-o") or t.startswith("--output") or t == "--remote-name"
            for t in tokens[1:]
        )
        return "write" if is_write else "unknown"
    if head == "wget":
        is_write = any(t == "-O" or t.startswith("--output-document") for t in tokens[1:])
        return "write" if is_write else "unknown"
    if head == "find":
        return "write" if any(t in _FIND_WRITE_FLAGS for t in tokens[1:]) else "read"
    if head == "sort":
        is_write = any(t == "-o" or t.startswith("--output") for t in tokens[1:])
        return "write" if is_write else "read"
    if head in _READ_ONLY_BASH_COMMANDS:
        return "read"
    return "unknown"


def _check_bash(tool_input: dict[str, Any]) -> None:
    cmd = get_command(tool_input)

    # $TMPDIR / $TEMP / $TMP は展開先が静的解析で分からないため read/write を
    # 問わず一律 block する (mktemp 等が既定でここへ書き込むため安全側に倒す)
    if re.search(r"\$\{?(?:TMPDIR|TEMP|TMP)\}?", cmd):
        _blocked(cmd.strip()[:120])
        return

    # `>`/`>>` で /tmp へ書き込もうとしている場合はコマンド種別に関係なく block
    if _redirect_targets_tmp(cmd):
        _blocked(cmd.strip()[:120])
        return

    # /tmp/ トークンが無ければ何もしない (早期リターン)
    if not _has_unallowed_tmp_token(cmd):
        return

    # command_policy が読めない場合は read/write を判定できないため block
    if _policy is None:
        _blocked(cmd.strip()[:120])
        return

    # `&&`/`;`/`|` 等でセグメントに分割し、/tmp に触れるセグメントだけを
    # read-only かどうか判定する。normalize 後に /tmp トークンを再現できな
    # かった場合 (稀な展開の食い違い) も fail-safe で block する。
    segments = _policy.normalize(cmd) or [cmd]
    saw_tmp_segment = False
    for segment in segments:
        if not _has_unallowed_tmp_token(segment):
            continue
        saw_tmp_segment = True
        parsed = _segment_head_and_tokens(segment)
        if parsed is None or _classify_segment(*parsed) != "read":
            _blocked(cmd.strip()[:120])
            return
    if not saw_tmp_segment:
        _blocked(cmd.strip()[:120])


def _check_file_path(tool_input: dict[str, Any]) -> None:
    path = get_path(tool_input)
    if path.startswith(_TMP_PATH_PREFIX) and not _is_allowed_tmp_path(path):
        _blocked(path)


_HANDLERS = {
    "bash": _check_bash,
    "create": _check_file_path,
    "edit": _check_file_path,
}


def main() -> None:
    data = read_input()
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        sys.exit(0)

    kind = normalize_tool_kind(tool_name)
    handler = _HANDLERS.get(kind)
    if handler is None:
        sys.exit(0)

    handler(tool_input)
    sys.exit(0)


if __name__ == "__main__":
    main()
