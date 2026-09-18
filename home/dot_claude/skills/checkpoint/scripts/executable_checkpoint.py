#!/usr/bin/env python3
"""checkpoint skill の保存先解決・書き込み・構造検査を扱う。

compaction を跨いで作業文脈を失わないようにするため、セッションの実行状態を
リポジトリ内の使い捨てディレクトリへ保存する。保存先の決め方と検査をここへ
寄せて、スキル本文・hook の双方が同じ結果を得られるようにする。

サブコマンド:

    paths   保存先を解決して JSON で返す
    lint    checkpoint を検査する (--structure で構造のみ)
    write   stdin の内容を checkpoint へアトミックに書く

exit code:

    0  問題なし
    1  検査に不合格
    2  引数や状態の誤り

設計上の約束 (docs/spec 側にも同じ内容がある):

- **保存先は常にセッション別**。固定名を奪い合わないので、ロックも所有権の
  交渉も要らない。復帰は必ず自分のファイルだけを読む。
- **セッション横断の GC をしない**。件数や日数で消すと、稼働中の別セッション
  の記録まで消えてしまう。各セッションは自分の 3 ファイルだけを管理する。
- **鮮度はその要求の固定境界と比べる**。「現在の会話地点」と比べると、保存や
  検査そのもので境界が進み、正しく保存しても永久に一致しない。

依存は標準ライブラリのみ。``uv run --no-project python`` で動く。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

# 使い捨ての置き場。redirect-tmp.py が /tmp の代わりに誘導する先と同じ。
TMP_DIRNAME = ".tmp"

# 意味内容の見出し。順序も含めてこのとおりに並んでいること。
REQUIRED_HEADINGS = (
    "## Goal",
    "## Constraints",
    "## State",
    "## Evidence",
    "## Next",
    "## Refs",
)

# 機械が書く節。意味内容の文字数予算には含めない。
MACHINE_MARKER = "<!-- machine:"

# 暫定値。復帰試験 (段 3) の結果で見直す。
DEFAULT_BUDGET = 2000

# 「長い」フェンスの定義。診断に要る短い引用は落とさない。
MAX_FENCE_LINES = 12

HEADER_RE = re.compile(r"<!--\s*checkpoint:\s*v1(?P<body>.*?)-->", re.DOTALL)


def _run_git(args: list[str], cwd: Path) -> str | None:
    """git を実行して stdout を返す。失敗したら None。"""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def repo_root(start: Path) -> Path:
    """リポジトリルートを返す。git でなければ start をそのまま使う。

    hook の cwd はサブディレクトリのことがあるので ``./`` を前提にしない。
    """
    top = _run_git(["rev-parse", "--show-toplevel"], start)
    if top:
        return Path(top)
    return start


def _short_sid(session_id: str) -> str:
    """セッション ID を保存先の名前に使える形へ縮める。"""
    cleaned = re.sub(r"[^0-9A-Za-z]", "", session_id)
    if not cleaned:
        raise ValueError("session id is empty after normalization")
    return cleaned[:8]


def resolve_paths(session_id: str, start: Path | None = None) -> dict[str, str]:
    """保存先を決める。探索も所有権の交渉もしない。

    同じセッションなら常に同じ結果になる。別セッションとはパスが重ならない
    ので、互いのファイルを読むことも壊すこともない。
    """
    start = start or Path.cwd()
    root = repo_root(start)
    base = root / TMP_DIRNAME
    sid = _short_sid(session_id)
    stem = f"checkpoint-{sid}"
    return {
        "root": str(root),
        "base": str(base),
        "session_short": sid,
        "checkpoint": str(base / f"{stem}.md"),
        "prev": str(base / f"{stem}.prev.md"),
        "state": str(base / f"{stem}.state.json"),
    }


def _check_ignore(root: Path, target: str) -> bool | None:
    """target が git に無視されるか。判定できなければ None。"""
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-q", target],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if done.returncode == 0:
        return True
    if done.returncode == 1:
        return False
    return None


def ensure_ignored(paths: dict[str, str]) -> dict[str, object]:
    """生成するファイルが git に無視されるか確かめ、必要なら除外へ足す。

    ``.gitignore`` は共有ファイルなので触らない。追記できなくても失敗にせず、
    呼び出し側が報告できるように結果を返す。
    """
    root = Path(paths["root"])
    targets = [paths["checkpoint"], paths["prev"], paths["state"]]

    inside = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if inside != "true":
        return {"git": False, "ignored": True, "updated": False, "reason": "not a git repo"}

    missing = [t for t in targets if _check_ignore(root, t) is False]
    if not missing:
        return {"git": True, "ignored": True, "updated": False, "reason": ""}

    # .git はファイルのこともある (linked worktree / chezmoi の source state)。
    # 固定パスの .git/info/exclude は成立しないので git に解決させる。
    rel = _run_git(["rev-parse", "--git-path", "info/exclude"], root)
    if not rel:
        return {
            "git": True,
            "ignored": False,
            "updated": False,
            "reason": "cannot resolve info/exclude",
        }
    exclude = Path(rel)
    if not exclude.is_absolute():
        exclude = root / exclude

    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if f"{TMP_DIRNAME}/" not in existing.split():
            suffix = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(f"{existing}{suffix}{TMP_DIRNAME}/\n", encoding="utf-8")
    except OSError as exc:
        return {"git": True, "ignored": False, "updated": False, "reason": str(exc)}

    return {"git": True, "ignored": True, "updated": True, "reason": ""}


def atomic_write(path: Path, text: str) -> None:
    """一時ファイルへ書いてから差し替える。途中書き込みの破損を防ぐ。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".checkpoint-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def parse_header(text: str) -> dict[str, str]:
    """先頭のヘッダコメントを読む。無ければ空の辞書。"""
    match = HEADER_RE.search(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            fields[key] = value.strip()
    return fields


def split_machine(text: str) -> tuple[str, str]:
    """意味内容と機械節に分ける。予算を取り合わせないため。"""
    index = text.find(MACHINE_MARKER)
    if index == -1:
        return text, ""
    return text[:index], text[index:]


def _fence_violations(body: str) -> list[str]:
    """``## Refs`` 以外にある長いフェンスを探す。"""
    problems: list[str] = []
    section = ""
    fence: str | None = None
    fence_start = 0
    fence_section = ""
    for number, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if fence is None and stripped.startswith("```"):
            fence = "```"
            fence_start = number
            fence_section = section
            continue
        if fence is not None:
            if stripped.startswith(fence):
                length = number - fence_start - 1
                if length > MAX_FENCE_LINES and fence_section != "## Refs":
                    problems.append(
                        f"{fence_start} 行目のコードブロックが {length} 行 "
                        f"(上限 {MAX_FENCE_LINES} 行、`## Refs` 以外)"
                    )
                fence = None
            continue
        if stripped.startswith("## "):
            section = stripped
    return problems


def _section_items(body: str, heading: str) -> list[str]:
    """見出し直下の箇条書きを集める。"""
    lines = body.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return []
    items: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", stripped):
            items.append(stripped)
    return items


def lint(
    text: str,
    *,
    budget: int = DEFAULT_BUDGET,
    boundary: str | None = None,
) -> tuple[list[str], list[str]]:
    """checkpoint を検査して (エラー, 警告) を返す。

    ``boundary`` を渡すと鮮度も見る。渡さなければ構造だけを見る。
    現在の会話地点とは決して比べない。
    """
    errors: list[str] = []
    warnings: list[str] = []

    body, _machine = split_machine(text)

    position = -1
    for heading in REQUIRED_HEADINGS:
        found = body.find(heading)
        if found == -1:
            errors.append(f"見出しが無い: {heading}")
            continue
        if found < position:
            errors.append(f"見出しの順序が違う: {heading}")
        position = found

    length = len(body.strip())
    if length > budget:
        errors.append(f"意味内容が {length} 文字 (予算 {budget} 文字)")

    errors.extend(_fence_violations(body))

    if boundary is not None:
        covered = parse_header(text).get("covered_through", "")
        if covered != boundary:
            errors.append(
                f"covered_through が要求の境界と違う (記録 {covered!r} / 要求 {boundary!r})"
            )

    next_items = _section_items(body, "## Next")
    if len(next_items) > 1:
        warnings.append(f"`## Next` が {len(next_items)} 項目 (1 つに絞ると復帰が速い)")

    return errors, warnings


def _cmd_paths(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.session, Path(args.cwd) if args.cwd else None)
    payload: dict[str, object] = dict(paths)
    if args.ensure_ignored:
        payload["ignore"] = ensure_ignored(paths)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK


def _cmd_lint(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"error: checkpoint が無い: {target}", file=sys.stderr)
        return EXIT_FAIL
    text = target.read_text(encoding="utf-8")
    boundary = None if args.structure else args.boundary
    errors, warnings = lint(text, budget=args.budget, boundary=boundary)
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return EXIT_FAIL if errors else EXIT_OK


def _cmd_write(args: argparse.Namespace) -> int:
    target = Path(args.path)
    text = sys.stdin.read()
    if args.keep_prev and target.exists():
        atomic_write(Path(args.keep_prev), target.read_text(encoding="utf-8"))
    atomic_write(target, text)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="checkpoint の保存先解決と検査")
    sub = parser.add_subparsers(dest="command", required=True)

    paths = sub.add_parser("paths", help="保存先を解決する")
    paths.add_argument("--session", required=True, help="セッション ID")
    paths.add_argument("--cwd", help="起点ディレクトリ (既定は現在地)")
    paths.add_argument(
        "--ensure-ignored",
        action="store_true",
        help="git に無視されるか確かめ、必要なら除外へ足す",
    )
    paths.set_defaults(func=_cmd_paths)

    check = sub.add_parser("lint", help="checkpoint を検査する")
    check.add_argument("path", help="checkpoint のパス")
    check.add_argument("--structure", action="store_true", help="構造だけを見る")
    check.add_argument("--boundary", help="その要求の固定境界")
    check.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="意味内容の文字数予算",
    )
    check.set_defaults(func=_cmd_lint)

    write = sub.add_parser("write", help="stdin の内容をアトミックに書く")
    write.add_argument("path", help="checkpoint のパス")
    write.add_argument("--keep-prev", help="直前の世代を残すパス")
    write.set_defaults(func=_cmd_write)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
