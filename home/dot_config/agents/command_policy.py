#!/usr/bin/env python3
"""Shell command normalization + policy matcher for AI CLI hooks.

Designed to back the hook layer of the permission system (Claude Code /
Copilot CLI). The CLI-side permission list is best-effort and has known bypass
bugs such as:

    cd /elsewhere && git push       # bypasses Bash(git push:*) ask/deny
    git -C /elsewhere commit ...    # bypasses Bash(git commit *) deny
    echo ok; rm -rf important       # second segment not evaluated separately

This module normalizes a raw bash command into a list of logical command
segments and checks each segment against the ``bash.deny`` / ``bash.ask``
patterns from ``common.toml``. The same lists drive both the generated
permission rules and the hook, so a rule only has to be written once.

Public API:
    load_deny(common_toml_path)             -> list[str]
    load_ask(common_toml_path)              -> list[str]
    normalize(command_str)                  -> list[str]
    find_match(command_str, patterns) -> str | None

The module is intentionally dependency-free (Python stdlib only) so it can
be imported from hooks running in minimal environments.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


# Common location for the source of truth managed by chezmoi.
# ``AGENTS_CONFIG_DIR`` can point at a different directory, which lets tests and
# containers exercise the hook against the repository copy instead of the
# deployed one.
def _default_config_dir() -> str:
    override = os.environ.get("AGENTS_CONFIG_DIR")
    if override:
        return override
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_home, "agents")


DEFAULT_COMMON_PATH = os.path.join(_default_config_dir(), "common.toml")


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _load_bash_list(key: str, path: str) -> list[str]:
    """Return ``bash.<key>`` from common.toml, or an empty list if missing."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("bash", {}).get(key, []))


def load_deny(path: str = DEFAULT_COMMON_PATH) -> list[str]:
    """Return the ``bash.deny`` list, or an empty list if missing.

    Patterns here are hard-blocked by the hook: there is no way to approve them.
    """
    return _load_bash_list("deny", path)


def load_ask(path: str = DEFAULT_COMMON_PATH) -> list[str]:
    """Return the ``bash.ask`` list, or an empty list if missing.

    Patterns here make the hook return ``ask`` instead of ``deny``: the agent
    proposes the command, the user approves it, and the command then runs.
    ``deny`` is evaluated first, so a more specific deny pattern (for example
    ``git reset --hard``) can carve an exception out of a broader ask pattern
    (``git reset``).
    """
    return _load_bash_list("ask", path)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Compound operators that introduce a new logical command.
_COMPOUND_OPS = ("&&", "||", ";", "|")


def _split_compound(command: str) -> list[str]:
    """Split a shell string at compound operators outside of quotes.

    The split is intentionally conservative: it walks the string char by char,
    honoring single and double quotes and backslash escapes. It is not a full
    shell parser, but it is sufficient for the bypass patterns observed in
    Claude Code bugs (#59498, #20085 etc.).
    """
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n and not in_single:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            matched_op = None
            for op in _COMPOUND_OPS:
                if command.startswith(op, i):
                    matched_op = op
                    break
            if matched_op:
                seg = "".join(buf).strip()
                if seg:
                    segments.append(seg)
                buf = []
                i += len(matched_op)
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _strip_cd_prefix(segment: str) -> str:
    """Strip a leading ``cd <path>`` (with optional &&) that prefixes a command.

    Examples:
        ``cd /foo && git push``    -> ``git push``
        ``cd ~/repo ; ls``         -> ``ls`` (caller already split at ``;``;
                                       this also covers the rare in-segment cd)
        ``cd /foo``                -> ``cd /foo`` (no command after, leave alone)
    """
    m = re.match(r"^\s*cd\s+\S+\s*(?:&&|;)\s*(.+)$", segment)
    if m:
        return m.group(1).strip()
    return segment


_GIT_C_RE = re.compile(r"^\s*git\s+(?:-C\s+\S+\s+)+(.+)$")


def _strip_git_dash_c(segment: str) -> str:
    """Strip ``git -C <path>`` and yield a bare ``git <subcommand>`` form.

    Examples:
        ``git -C /foo commit``                 -> ``git commit``
        ``git -C /foo -C /bar status``         -> ``git status``
    """
    m = _GIT_C_RE.match(segment)
    if m:
        return f"git {m.group(1).strip()}"
    return segment


_CD_ONLY_RE = re.compile(r"^\s*cd(\s+\S+)?\s*$")

# 先頭の環境変数代入 (FOO=1 BAR=2 cmd ...)
_ENV_ASSIGN_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S*)\s+)+(.+)$")

# 値をフラグ以外の位置引数として取るラッパー。
# 例: timeout 5 CMD / nice -n 5 CMD / stdbuf -oL CMD
# 数値やサイズ指定はコマンド名ではないので読み飛ばす。
_WRAPPER_POSITIONAL_ARG_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?[smhd]?$")

# コマンドをそのまま実行するラッパー。後続を評価対象に引き上げる。
# 値は「コマンド名までに読み飛ばすオプションの取り方」を表す:
#   "flags"      -> -x 形式のフラグを読み飛ばす
#   "flags+args" -> フラグとその引数 (-u user, -I{} 等) も読み飛ばす
#   "duration"   -> flags+args に加えて先頭の数値引数 (timeout 5) も読み飛ばす
_WRAPPERS: dict[str, str] = {
    "env": "flags",
    "command": "flags",
    "builtin": "flags",
    "exec": "flags",
    "nohup": "flags",
    "setsid": "flags",
    "stdbuf": "flags+args",
    "nice": "flags+args",
    "ionice": "flags+args",
    "timeout": "duration",
    "time": "flags",
    "xargs": "flags+args",
    "doas": "flags+args",
    "proot": "flags+args",
}

# シェルを起動して文字列を実行するもの。-c の引数を再帰的に評価する。
_SHELL_BINS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "ash"}

# 文字列をそのままコードとして実行するもの
_EVAL_BINS = {"eval", "source", "."}

# グループ化・リダイレクトの飾りを落とすための文字
_GROUPING_PREFIX = "({"
_GROUPING_SUFFIX = ")}"


def _basename(token: str) -> str:
    """``/usr/bin/git`` -> ``git``. パス指定でポリシーを回避させない。"""
    if "/" in token:
        return token.rsplit("/", 1)[-1]
    return token


def _strip_grouping(segment: str) -> str:
    """``(git push)`` や ``{ git push; }`` の飾りを落とす。"""
    seg = segment.strip()
    changed = True
    while changed and seg:
        changed = False
        if seg[0] in _GROUPING_PREFIX:
            seg = seg[1:].strip()
            changed = True
        while seg and seg[-1] in _GROUPING_SUFFIX + ";&":
            seg = seg[:-1].strip()
            changed = True
    return seg


def _strip_env_assignments(segment: str) -> str:
    """``GIT_DIR=/x git push`` -> ``git push``"""
    m = _ENV_ASSIGN_RE.match(segment.strip())
    if m:
        return m.group(1).strip()
    return segment


def _normalize_leading_path(segment: str) -> str:
    """``/usr/bin/git push`` -> ``git push``"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if not tokens:
        return segment
    head = _basename(tokens[0])
    if head == tokens[0]:
        return segment
    rest = segment.split(None, 1)
    return f"{head} {rest[1]}" if len(rest) > 1 else head


def _strip_wrapper(segment: str) -> str:
    """``timeout 5 git push`` -> ``git push``、``env FOO=1 git push`` -> ``git push``"""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return segment
    if not tokens:
        return segment
    head = _basename(tokens[0])
    style = _WRAPPERS.get(head)
    if style is None:
        return segment

    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == "--":
            i += 1
            break
        if token.startswith("-"):
            # -I{} や -u root のように値が別トークンのものを読み飛ばす
            if style in ("flags+args", "duration") and "=" not in token and len(token) == 2:
                i += 2
                continue
            i += 1
            continue
        if style == "duration" and _WRAPPER_POSITIONAL_ARG_RE.match(token):
            # timeout 5 CMD / timeout 1.5s CMD
            i += 1
            continue
        if "=" in token and not token.startswith("/"):
            # env FOO=1 のような代入
            i += 1
            continue
        break
    rest = tokens[i:]
    if not rest:
        return segment
    return " ".join(shlex.quote(t) if " " in t else t for t in rest)


def _expand_shell_invocation(segment: str) -> list[str] | None:
    """``bash -c "git push"`` の中身を取り出す。対象外なら None。

    ``eval 'git push'`` のように文字列をコードとして実行するものも同様に扱う。
    """
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    if not tokens:
        return None
    head = _basename(tokens[0])

    if head in _EVAL_BINS and len(tokens) > 1:
        return [" ".join(tokens[1:])]

    if head not in _SHELL_BINS:
        return None
    for i, token in enumerate(tokens[1:], start=1):
        # -c / -lc / -xc のように c を含む短縮フラグ
        if token.startswith("-") and not token.startswith("--") and "c" in token:
            if i + 1 < len(tokens):
                return [tokens[i + 1]]
            return None
    return None


def _normalize_segment(segment: str) -> str:
    """先頭トークンを変える飾りを繰り返し剥がす。"""
    seg = segment
    for _ in range(8):  # apply transformations repeatedly until fixed
        new = _strip_grouping(seg)
        new = _strip_cd_prefix(new)
        new = _strip_git_dash_c(new)
        new = _strip_env_assignments(new)
        new = _strip_wrapper(new)
        new = _normalize_leading_path(new)
        if new == seg:
            break
        seg = new
    return " ".join(seg.split())


def normalize(command: str, _depth: int = 0) -> list[str]:
    """Return a list of normalized command segments suitable for matching.

    Compound operators (``&&``, ``||``, ``;``, ``|``) split the command into
    logical segments. Each segment is then stripped of anything that merely
    changes the leading token without changing what actually runs:

      * ``cd <path> && X``            -> ``X``
      * ``git -C <path> <sub>``       -> ``git <sub>``
      * ``(X)`` / ``{ X; }``          -> ``X``
      * ``FOO=1 X``                   -> ``X``
      * ``env`` / ``timeout`` / ``nohup`` / ``xargs`` などのラッパー -> 後続コマンド
      * ``/usr/bin/X``                -> ``X``
      * ``bash -c "X"`` / ``eval "X"`` -> ``X`` を再帰的に評価

    Pure ``cd`` segments left over from compound splitting are dropped (they
    cannot match any deny pattern but would clutter the output).

    The shell wrapper itself is kept as a segment as well, so a rule targeting
    ``sh`` (for example ``curl x | sh``) still matches.
    """
    segments = _split_compound(command)
    out: list[str] = []
    for seg in segments:
        seg = _normalize_segment(seg)
        if not seg or _CD_ONLY_RE.match(seg):
            continue
        out.append(seg)
        if _depth < 3:
            inner = _expand_shell_invocation(seg)
            if inner:
                for chunk in inner:
                    out.extend(normalize(chunk, _depth + 1))
    return out


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _pattern_matches(segment: str, pattern: str) -> bool:
    """Return True if ``segment`` should be blocked by ``pattern``.

    Matching rules:
      * Pattern must appear as a contiguous run of whitespace-separated tokens
        at the start of the normalized segment. ``"git push"`` matches
        ``"git push origin main"`` but not ``"git push-fake"`` or
        ``"foo git push"``.
      * Single-token patterns (no spaces) match if the segment's first token
        equals the pattern OR if any subsequent token equals it after a path
        prefix (e.g. ``sudo`` matches ``/usr/bin/sudo`` is intentionally NOT
        supported -- patterns target logical command names).
    """
    try:
        seg_tokens = shlex.split(segment)
    except ValueError:
        seg_tokens = segment.split()
    pat_tokens = pattern.split()
    if not pat_tokens or not seg_tokens:
        return False
    if len(seg_tokens) < len(pat_tokens):
        return False
    return seg_tokens[: len(pat_tokens)] == pat_tokens


def find_match(command: str, patterns: Iterable[str]) -> str | None:
    """Return the first matching pattern, or None."""
    pats = list(patterns)
    if not pats:
        return None
    for segment in normalize(command):
        for pat in pats:
            if _pattern_matches(segment, pat):
                return pat
    return None


# ---------------------------------------------------------------------------
# CLI for quick inspection / hook integration
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help="bash command string to check")
    parser.add_argument(
        "--common",
        default=DEFAULT_COMMON_PATH,
        help=f"path to common.toml (default: {DEFAULT_COMMON_PATH})",
    )
    args = parser.parse_args(argv)

    patterns = load_deny(args.common)
    match = find_match(args.command, patterns)
    if match is None:
        print("OK")
        return 0
    print(f"BLOCK: matched deny pattern '{match}'")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
