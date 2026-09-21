#!/usr/bin/env python3
"""docs/ の索引と実ファイルの整合を検査する。

索引が腐ると docs 全体が腐る。整合だけは決定的に判定できるので、ここで機械に
やらせる。``scripts/lint_templates.py`` と同じ位置づけで pre-commit に入れる。

**検査するのは整合だけ。** 候補比較の妥当性や証拠の十分性は判定しない。
それらは人と AI が読んで判断する領分で、lint の合格をもって保証したことには
しない。

検査:

    1. 索引の一覧に載っているファイルが実在する
    2. ディレクトリ内の .md が全て索引のどこかに載っている
    3. adr/ と change/ の番号が (カテゴリ内で) 重複していない
    4. 案件の状態が既定値のどれか
    5. Done / Abandoned の案件が「活動中」区分に残っていない
    6. Superseded by ADR-NNNN の参照先が実在する

意図的に検査しないこと:

    - 連番の欠番。終了した案件が出れば欠番は正常に生じる。番号の連続性は
      正しさではないので、一意性だけを見る
    - ルート index.md にカテゴリ索引と同じ構成を求めること。ルートは
      ダッシュボードとナビゲーションで、契約が違う
    - 相対リンクの全数検査。実行時間に見合わない

exit code:

    0  問題なし
    1  不整合あり
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1

# カテゴリ索引を持つディレクトリ。ルート index.md は契約が違うので含めない。
CATEGORIES = ("spec", "adr", "research", "change")

# 連番を持つカテゴリ。番号空間はカテゴリごとに独立している。
NUMBERED = ("adr", "change")

CHANGE_STATES = (
    "Exploring",
    "Planned",
    "In progress",
    "Done",
    "Paused",
    "Abandoned",
)

# 終了した案件。活動中の一覧に残っていてはいけない。
CLOSED_STATES = ("Done", "Abandoned")

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
NUMBER_RE = re.compile(r"^(\d{4})-")
STATUS_RE = re.compile(r"^-\s*\*\*ステータス\*\*\s*:\s*(.+?)\s*$", re.MULTILINE)
STATE_RE = re.compile(r"^-\s*\*\*状態\*\*\s*:\s*(.+?)\s*$", re.MULTILINE)
SUPERSEDED_RE = re.compile(r"Superseded by ADR-(\d{4})")


def _linked_targets(index: Path) -> set[str]:
    """索引から張られている配下の .md を集める (サブディレクトリを含む)。"""
    text = index.read_text(encoding="utf-8")
    names: set[str] = set()
    for target in LINK_RE.findall(text):
        target = target.split("#", 1)[0].strip()
        if not target.endswith(".md"):
            continue
        # 上位や別カテゴリへのリンクは対象外
        if target.startswith(("../", "/", "http")):
            continue
        names.add(target)
    return names


def _active_section(text: str) -> str:
    """「活動中」節だけを切り出す。無ければ空文字。"""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## 活動中")
    except StopIteration:
        return ""
    collected: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected)


def check_category(docs: Path, name: str) -> list[str]:
    """1 カテゴリ分を検査して、見つかった問題を返す。"""
    problems: list[str] = []
    directory = docs / name
    if not directory.is_dir():
        return problems

    index = directory / "index.md"
    if not index.exists():
        return [f"{name}/index.md が無い"]

    documents = sorted(
        p
        for p in directory.rglob("*.md")
        if p.name != "index.md" or p.parent != directory
    )
    linked = _linked_targets(index)
    index_text = index.read_text(encoding="utf-8")

    # 1. 索引が指す先が実在するか
    for target in sorted(linked):
        if not (directory / target).exists():
            problems.append(f"{name}/index.md が実在しないファイルを指している: {target}")

    # 2. 掲載漏れが無いか
    for document in documents:
        relative = document.relative_to(directory).as_posix()
        if relative not in linked:
            problems.append(f"{name}/{relative} が index.md に載っていない")

    # 3. 番号の一意性 (カテゴリ内)
    if name in NUMBERED:
        seen: dict[str, str] = {}
        for document in documents:
            match = NUMBER_RE.match(document.name)
            if not match:
                continue
            number = match.group(1)
            if number in seen:
                problems.append(
                    f"{name}/ の番号 {number} が重複している: "
                    f"{seen[number]} と {document.name}"
                )
            seen[number] = document.name

    if name == "change":
        problems.extend(_check_change(directory, documents, index_text))

    if name == "adr":
        problems.extend(_check_adr(directory, documents))

    return problems


def _check_change(directory: Path, documents: list[Path], index_text: str) -> list[str]:
    """案件の状態と、活動中一覧の整合を見る。"""
    problems: list[str] = []
    active = _active_section(index_text)

    for document in documents:
        text = document.read_text(encoding="utf-8")
        match = STATE_RE.search(text)
        if not match:
            problems.append(f"change/{document.name} に「- **状態**: ...」が無い")
            continue
        state = match.group(1)
        if state not in CHANGE_STATES:
            problems.append(
                f"change/{document.name} の状態が既定値でない: {state!r} "
                f"(既定値: {', '.join(CHANGE_STATES)})"
            )
            continue
        # 5. 終了した案件が活動中に残っていないか
        if state in CLOSED_STATES and document.name in active:
            problems.append(
                f"change/{document.name} は {state} なのに「活動中」に残っている"
            )
    return problems


def _check_adr(directory: Path, documents: list[Path]) -> list[str]:
    """Superseded の参照先が実在するかを見る。"""
    problems: list[str] = []
    numbers = {
        match.group(1)
        for document in documents
        if (match := NUMBER_RE.match(document.name))
    }
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in SUPERSEDED_RE.findall(text):
            if target not in numbers:
                problems.append(
                    f"adr/{document.name} の Superseded by ADR-{target} が実在しない"
                )
    return problems


def lint_docs(docs: Path) -> list[str]:
    problems: list[str] = []
    if not (docs / "index.md").exists():
        problems.append("docs/index.md が無い")
    for name in CATEGORIES:
        problems.extend(check_category(docs, name))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docs の索引整合を検査する")
    parser.add_argument(
        "--docs",
        default="docs",
        help="docs ディレクトリ (既定: docs)",
    )
    # pre-commit がファイル名を渡してくるが、検査は docs 全体で行う。
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    docs = Path(args.docs)
    if not docs.is_dir():
        print(f"error: {docs} が無い", file=sys.stderr)
        return EXIT_FAIL

    problems = lint_docs(docs)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} 件の不整合", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
