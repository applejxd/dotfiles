#!/usr/bin/env python3
"""develop へのマージ待ちの一覧（枝名・先行コミット数・最新の件名だけ）。

    python3 scripts/prs.py [--all] [--repo <パス>] [--target develop]

`feature/*`・`bugfix/*` のうち、統合先（既定 develop）より先に進んでいる枝を、最新のコミットが新しい順に出す。
他の未統合の枝に含まれる枝（bundle の取り込み元など）は、既定では隠す（`--all` で全部）。
詳細・統合・掃除は、エージェントに指示する（この道具は一覧だけ）。see docs/spec/operation-modes.md
終了コード: 0 = 出力した（待ちが無くても 0）、2 = git の失敗・使い方の誤り。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SUBJECT_MAX = 60


@dataclass(frozen=True)
class Item:
    name: str
    tip: str
    ts: int
    ahead: int
    subject: str


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _must(repo: Path, *args: str) -> str:
    r = _git(repo, *args)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def collect(repo: Path, target: str) -> list[Item]:
    """統合先より先行している枝を、最新のコミットが新しい順に返す。"""
    fmt = "%(refname:short)%09%(objectname)%09%(committerdate:unix)%09%(subject)"
    out = _must(repo, "for-each-ref", f"--format={fmt}", "refs/heads/feature", "refs/heads/bugfix")
    items: list[Item] = []
    for line in out.splitlines():
        name, tip, ts, subject = line.split("\t", 3)
        ahead = int(_must(repo, "rev-list", "--count", f"{target}..{name}").strip())
        if ahead > 0:
            items.append(Item(name, tip, int(ts), ahead, subject))
    return sorted(items, key=lambda i: (-i.ts, i.name))


def _is_ancestor(repo: Path, a: str, b: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def hide_contained(repo: Path, items: list[Item]) -> list[Item]:
    """他の未統合の枝に（先端が違う形で）含まれる枝を除く。"""
    return [
        i
        for i in items
        if not any(j.tip != i.tip and _is_ancestor(repo, i.tip, j.tip) for j in items)
    ]


def render(items: list[Item], hidden: int) -> str:
    if not items:
        return "マージ待ちはありません"
    width = max(len(i.name) for i in items)
    lines = [f"{i.name:<{width}}  {i.ahead:>3} コミット  {i.subject[:SUBJECT_MAX]}" for i in items]
    if hidden:
        lines.append(f"(他の枝に含まれる {hidden} 件を隠した。--all で全部)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="develop へのマージ待ちの一覧")
    p.add_argument("--all", action="store_true", help="他の枝に含まれる枝も出す")
    p.add_argument("--repo", default=".", help="リポジトリ（既定: カレント）")
    p.add_argument("--target", default="develop", help="統合先（既定: develop）")
    args = p.parse_args(argv)
    repo = Path(args.repo)
    try:
        items = collect(repo, args.target)
        shown = items if args.all else hide_contained(repo, items)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"prs.py: {e}", file=sys.stderr)
        return 2
    print(render(shown, len(items) - len(shown)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
