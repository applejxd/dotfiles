#!/usr/bin/env python3
"""Shell command normalization + critical_deny matcher.

Designed to back the third defense layer for AI CLI permission systems
(Claude Code / Copilot CLI). The first two layers (CLI UI prompt and the
permission list) are best-effort and have known bypass bugs such as:

    cd /elsewhere && git push       # bypasses Bash(git push:*) ask/deny
    git -C /elsewhere commit ...    # bypasses Bash(git commit *) deny
    echo ok; rm -rf important       # second segment not evaluated separately

This module normalizes a raw bash command into a list of logical command
segments and checks each segment against the critical_deny patterns from
``common.toml``. Anything that matches must be hard-blocked by the hook.

Public API:
    load_critical_deny(common_toml_path)    -> list[str]
    normalize(command_str)                  -> list[str]
    find_critical_match(command_str, patterns) -> str | None

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
DEFAULT_COMMON_PATH = os.path.expanduser("~/.config/agents/common.toml")


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def load_critical_deny(path: str = DEFAULT_COMMON_PATH) -> list[str]:
    """Return the ``bash.critical_deny`` list, or an empty list if missing."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("bash", {}).get("critical_deny", []))


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


def normalize(command: str) -> list[str]:
    """Return a list of normalized command segments suitable for matching.

    Compound operators (``&&``, ``||``, ``;``, ``|``) split the command into
    logical segments. Each segment is further normalized:

      * Leading ``cd <path> && X`` (within a single segment) collapses to ``X``.
      * Leading ``git -C <path>`` is stripped from git invocations.
      * Pure ``cd`` segments left over from compound splitting are dropped
        (they cannot match any deny pattern but would clutter the output).
    """
    segments = _split_compound(command)
    out: list[str] = []
    for seg in segments:
        for _ in range(3):  # apply transformations repeatedly until fixed
            new = _strip_cd_prefix(seg)
            new = _strip_git_dash_c(new)
            if new == seg:
                break
            seg = new
        seg = " ".join(seg.split())
        if not seg:
            continue
        if _CD_ONLY_RE.match(seg):
            continue
        out.append(seg)
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


def find_critical_match(command: str, patterns: Iterable[str]) -> str | None:
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

    patterns = load_critical_deny(args.common)
    match = find_critical_match(args.command, patterns)
    if match is None:
        print("OK")
        return 0
    print(f"BLOCK: matched critical_deny pattern '{match}'")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
