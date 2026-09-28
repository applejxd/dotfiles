#!/usr/bin/env python3
"""docs への参照が、実在するファイルと見出しを指しているかを確かめる。

文書を分割・移動すると、索引の検査 (lint_docs.py) では見えない参照が切れる。
Markdown のリンクだけでなく、コードのコメントなどに書いた ``docs/...md#見出し`` や
``docs/...md 「見出し」`` も見る。

作業の前に ``--save`` で今の結果を控え、作業の後に ``--baseline`` で比べると、
**新たに切れた参照だけ**が出る (もともと切れているものに埋もれない)::

    python3 check_refs.py --save before.txt
    # ... 文書を編集する ...
    python3 check_refs.py --baseline before.txt

見出しのアンカーは GitHub の規則に近い変換で作る (完全には一致しない)。

exit code:

    0  問題なし (--baseline を渡したときは、新しい問題なし)
    1  問題あり
    2  使い方の誤り
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from functools import cache
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".lock", ".db"}
LINK = re.compile(r"\]\(([^)\s]+)\)")
# 前の文字の否定は、`sdd-docs/references/...` の途中から `docs/...` を拾わせないため
PATH_REF = re.compile(r"(?<![\w/.-])(docs/[\w./-]+?\.md)(#[^\s)`'\"」、。,]+)?")
NAME_REF = re.compile(r"(?<![\w/.-])(docs/[\w./-]+?\.md)\s*「([^」]+)」")


def slug(text: str) -> str:
    text = text.strip().lower().replace("`", "")
    kept = [ch for ch in text if ch in " -_" or unicodedata.category(ch)[0] in "LNM"]
    return "".join(kept).replace(" ", "-")


@cache
def headings(path: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    """(アンカーの集合, 見出しの文言) を返す。コードブロックの中は数えない。"""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    texts: list[str] = []
    fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        match = re.match(r"^#{1,6} (.+)$", line)
        if fence or not match:
            continue
        texts.append(match.group(1))
        base = slug(match.group(1))
        count = seen.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return frozenset(anchors), tuple(texts)


def tracked_files(root: Path) -> list[str]:
    done = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout.splitlines()


def check_target(root: Path, source: Path, dest: Path, anchor: str | None, label: str):
    where = source.relative_to(root).as_posix()
    if not dest.exists():
        return f"{where}: ファイルが無い -> {label}"
    if anchor and dest.suffix == ".md" and anchor not in headings(dest)[0]:
        return f"{where}: 見出しが無い -> {label}"
    return None


def find_problems(root: Path, skip: frozenset[Path] = frozenset()) -> list[str]:
    problems: set[str] = set()
    for rel in tracked_files(root):
        source = root / rel
        if not source.is_file() or source.suffix.lower() in SKIP_SUFFIXES:
            continue
        if source.resolve() in skip:
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if source.suffix == ".md":
            for target in LINK.findall(text):
                if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("<"):
                    continue
                file_part, _, anchor = target.partition("#")
                dest = (source.parent / file_part).resolve() if file_part else source
                problem = check_target(root, source, dest, anchor or None, target)
                if problem:
                    problems.add(problem)
        for match in PATH_REF.finditer(text):
            path, anchor = match.group(1), match.group(2)
            if "<" in path or "*" in path or "..." in path:
                continue
            problem = check_target(
                root, source, root / path, anchor[1:] if anchor else None, match.group(0)
            )
            if problem:
                problems.add(problem)
        for match in NAME_REF.finditer(text):
            dest = root / match.group(1)
            name = match.group(2)
            if not dest.exists() or name.startswith("<") or "..." in match.group(1):
                continue
            if not any(name.lower() in h.lower() for h in headings(dest)[1]):
                where = source.relative_to(root).as_posix()
                problems.add(f"{where}: 名前の見出しが無い -> {match.group(1)} 「{name}」")
    return sorted(problems)


def git_root(start: Path) -> Path | None:
    done = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docs への参照の切れを検査する")
    parser.add_argument("--root", help="リポジトリのルート (既定: 現在地の git のルート)")
    parser.add_argument("--save", help="今の結果をこのファイルへ保存する")
    parser.add_argument("--baseline", help="このファイルに無い問題だけを出す")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else git_root(Path.cwd())
    if root is None or not root.is_dir():
        print("error: git リポジトリの中で実行するか --root を渡す", file=sys.stderr)
        return EXIT_USAGE

    # 控え自体が git の管理外でなくても、控えに書いたパスを参照として数えない
    skip = frozenset(Path(p).resolve() for p in (args.save, args.baseline) if p)
    problems = find_problems(root.resolve(), skip)
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text("".join(f"{p}\n" for p in problems), encoding="utf-8")
    if args.baseline:
        known = set(Path(args.baseline).read_text(encoding="utf-8").splitlines())
        problems = [p for p in problems if p not in known]
    for problem in problems:
        print(problem)
    print(f"{len(problems)} 件", file=sys.stderr)
    return EXIT_FAIL if problems else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
