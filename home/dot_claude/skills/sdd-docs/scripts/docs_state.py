#!/usr/bin/env python3
"""docs/ の状態と、反映すべき差分の手がかりを出す。sdd-docs スキルの「指示なし」の入口。

何を書くかは判断が要るので、ここでは**判断の材料を決定的に集めるだけ**にする
(文書の中身は書かない。ただし `scaffold` は空の索引の骨組みを作る)。

サブコマンド:

    status    docs/ の状態 (absent / partial / complete) と、そのあとの差分 (前回 docs を
              更新したコミット以降のコミット・未コミットの変更・それに言及している文書) を出す
    scaffold  足りない索引 (docs/index.md と各カテゴリの index.md) の骨組みだけを作る。
              既存のファイルは上書きしない

使い方:

    python3 ~/.claude/skills/sdd-docs/scripts/docs_state.py status
    python3 ~/.claude/skills/sdd-docs/scripts/docs_state.py scaffold --title NAME --purpose "..."

exit code: 0 = 成功。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

STATE_RE = re.compile(r"^-\s*\*\*状態\*\*\s*:\s*(.+?)\s*$", re.MULTILINE)
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "references" / "scaffold"
SCAFFOLD_FILES = {
    "index.md": "root-index.md.tpl",
    "spec/index.md": "spec-index.md.tpl",
    "adr/index.md": "adr-index.md.tpl",
    "research/index.md": "research-index.md.tpl",
    "change/index.md": "change-index.md.tpl",
}
MAX_LIST = 40  # 1 つの一覧に出す最大行数 (出力を読める量に保つ)


def structure(docs: Path) -> tuple[str, list[str]]:
    """(absent | partial | complete, 足りない索引の docs からの相対パス) を返す。"""
    missing = [name for name in SCAFFOLD_FILES if not (docs / name).is_file()]
    if len(missing) == len(SCAFFOLD_FILES):
        return "absent", missing
    return ("complete" if not missing else "partial"), missing


def scaffold(docs: Path, title: str, purpose: str) -> list[str]:
    """足りない索引だけを作る。作ったファイルの相対パスを返す (既存は触らない)。"""
    created: list[str] = []
    for name, template in SCAFFOLD_FILES.items():
        target = docs / name
        if target.exists():
            continue
        text = (SCAFFOLD_DIR / template).read_text(encoding="utf-8")
        text = text.replace("{{TITLE}}", title).replace("{{PURPOSE}}", purpose)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        created.append(name)
    return created


def _git(args: list[str], cwd: Path) -> str | None:
    """git を呼ぶ。失敗 (git が無い・リポジトリでない・不正な rev) は None。"""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _lines(text: str | None) -> list[str]:
    return [line for line in (text or "").splitlines() if line]


def diff_context(docs: Path, since: str | None) -> dict | None:
    """前回 docs を更新した以降の差分。git のリポジトリでなければ None。"""
    top_text = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    if not top_text or not top_text.strip():
        return None
    top = Path(top_text.strip())
    try:
        docs_rel = docs.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None

    baseline = since
    baseline_label = since or ""
    if baseline is None:
        out = _git(["log", "-1", "--format=%H%x09%cs%x09%s", "--", docs_rel], top)
        if out and out.strip():
            parts = (out.strip().split("\t", 2) + ["", ""])[:3]
            baseline = parts[0]
            baseline_label = f"{parts[0][:8]} {parts[1]} {parts[2]}"

    if baseline:
        count = _git(["rev-list", "--count", f"{baseline}..HEAD"], top)
        total = int(count.strip()) if count and count.strip().isdigit() else 0
        commits = _lines(_git(["log", "--format=%h %cs %s", f"--max-count={MAX_LIST}", f"{baseline}..HEAD"], top))
        changed = _lines(_git(["diff", "--name-only", baseline], top))  # 作業ツリーまで含む
    else:
        # docs を一度も更新していない。直近の変更だけを見る (全履歴は読まない)
        commits = _lines(_git(["log", "--format=%h %cs %s", f"--max-count={MAX_LIST}"], top))
        total = len(commits)
        changed = _lines(_git(["diff", "--name-only", "HEAD"], top))
    untracked = _lines(_git(["ls-files", "--others", "--exclude-standard"], top))
    uncommitted = set(_lines(_git(["diff", "--name-only", "HEAD"], top))) | set(untracked)

    prefix = docs_rel.rstrip("/") + "/"
    return {
        "baseline": baseline_label,
        "commits": commits,
        "total_commits": total,
        "outside": sorted({f for f in changed + untracked if not f.startswith(prefix)}),
        "uncommitted": sorted(f for f in uncommitted if not f.startswith(prefix)),
    }


def mentions(docs: Path, files: list[str]) -> dict[str, list[str]]:
    """変更されたファイルに言及している文書を探す (パス、または 8 文字以上のファイル名が本文にある)。"""
    needles = {}
    for f in files:
        name = f.rsplit("/", 1)[-1]
        needles[f] = [f] + ([name] if len(name) >= 8 else [])
    found: dict[str, list[str]] = {}
    for doc in sorted(docs.rglob("*.md")):
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = [f for f, keys in needles.items() if any(k in text for k in keys)]
        if hits:
            found[doc.relative_to(docs).as_posix()] = hits
    return found


def active_changes(docs: Path) -> list[str]:
    """closed/ に無い案件の (ファイル名 / 状態 / 題名)。"""
    rows: list[str] = []
    directory = docs / "change"
    if not directory.is_dir():
        return rows
    for doc in sorted(directory.glob("*.md")):
        if doc.name == "index.md":
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        state = STATE_RE.search(text)
        title = TITLE_RE.search(text)
        rows.append(f"{doc.name} [{state.group(1) if state else '状態なし'}] {title.group(1) if title else ''}")
    return rows


def _capped(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_LIST:
        return lines
    return lines[:MAX_LIST] + [f"... ほか {len(lines) - MAX_LIST} 件"]


def cmd_status(args: argparse.Namespace) -> int:
    docs = Path(args.docs)
    state, missing = structure(docs)
    print(f"state: {state}")
    if state == "absent":
        others = sorted(p.relative_to(docs).as_posix() for p in docs.rglob("*.md")) if docs.is_dir() else []
        print(f"{docs}/ に構成（index.md と spec / adr / research / change の索引）が無い。")
        if others:
            print("既にある .md（消さない・動かさない。取り込む対象）:")
            for line in _capped(others):
                print(f"  {line}")
        print("次: scaffold で骨組みを作り、リポジトリと今の文脈から中身を書く (SKILL.md「新規に作る」)")
        return 0
    if state == "partial":
        print("足りない索引: " + ", ".join(missing))
        print("次: scaffold で足りない索引を作ってから、差分を反映する")

    ctx = diff_context(docs, args.since)
    if ctx is None:
        print("git のリポジトリでない (差分は出せない)。今の文脈と docs の中身から判断する")
    else:
        print(f"前回 docs を更新したコミット: {ctx['baseline'] or '（無い。直近の履歴だけを見る）'}")
        print(f"それ以降のコミット: {ctx['total_commits']} 件")
        for line in ctx["commits"]:
            print(f"  {line}")
        if ctx["uncommitted"]:
            print("未コミットの変更（docs を除く）:")
            for line in _capped(ctx["uncommitted"]):
                print(f"  {line}")
        print(f"docs の外で変わったファイル: {len(ctx['outside'])} 件")
        for line in _capped(ctx["outside"]):
            print(f"  {line}")
        found = mentions(docs, ctx["outside"])
        if found:
            print("変わったファイルに言及している文書（古くなっていないか確かめる）:")
            for doc, hits in list(found.items())[:MAX_LIST]:
                extra = f" ほか {len(hits) - 4} 件" if len(hits) > 4 else ""
                print(f"  {doc}: {', '.join(hits[:4])}{extra}")
        elif ctx["outside"]:
            print("変わったファイルに言及している文書は無い")
    cases = active_changes(docs)
    if cases:
        print("案件（change/ 直下）:")
        for row in cases:
            print(f"  {row}")
    return 0


def cmd_scaffold(args: argparse.Namespace) -> int:
    docs = Path(args.docs)
    title = args.title or Path.cwd().name
    purpose = args.purpose or "（未記入。リポジトリの README から書く）"
    created = scaffold(docs, title, purpose)
    if created:
        print("作成: " + ", ".join(f"{docs}/{name}" for name in created))
    else:
        print("作成するものは無い（索引は全て在る）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="docs/ の状態と、反映すべき差分を出す")
    parser.add_argument("--docs", default="docs", help="docs ディレクトリ (既定: docs)")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="状態と差分を出す")
    status.add_argument("--since", help="差分の基準にするコミット (既定: docs を最後に変えたコミット)")
    status.set_defaults(func=cmd_status)
    scaf = sub.add_parser("scaffold", help="足りない索引の骨組みを作る")
    scaf.add_argument("--title", help="プロジェクト名 (既定: カレントディレクトリ名)")
    scaf.add_argument("--purpose", help="目的の 1 文")
    scaf.set_defaults(func=cmd_scaffold)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
