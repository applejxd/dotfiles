#!/usr/bin/env python3
"""skill-lab の ``skills/<名前>`` を ``home/dot_claude/skills/<名前>`` へ複製して同期する。

正本は skill-lab で、このリポジトリのコピーは編集しない。取り込むのは skill-lab の
**コミット済みの版 (HEAD)** だけ (作業中の変更は取り込まない)。

    python3 scripts/sync_skill_lab.py conference-video --check   # 差分を見るだけ
    python3 scripts/sync_skill_lab.py conference-video           # 置き換える

置き換えたら ``docs/spec/<名前>.md`` の「取り込んだ版」(コミット・日付・件数) も更新する。
手順の全体は docs/spec/conference-video.md の「更新の手順」。
"""

from __future__ import annotations

import argparse
import filecmp
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path.home() / "src" / "skill-lab"
# 実行時に生えるもの。上流の追跡ファイルには無く、同期でも触らない比較から除く
IGNORED = {".venv", ".pytest_cache", ".ruff_cache", ".tmp", "__pycache__"}
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SyncError(Exception):
    pass


def _git(src: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(src), "-c", "core.fsmonitor=false", *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SyncError(
            f"git {' '.join(args)} が失敗: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def _extract(src: Path, skill: str, into: Path) -> int:
    """``HEAD:skills/<skill>`` を ``into`` へ展開し、ファイル数を返す。"""
    data = _git(src, "archive", "HEAD", f"skills/{skill}")
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[2:]  # skills/<skill>/ を外す
            if not parts:
                continue
            if member.issym() or member.islnk():
                raise SyncError(f"リンクを含む (取り込まない): {member.name}")
            target = into.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            assert extracted is not None
            target.write_bytes(extracted.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            count += 1
    return count


def _diff(new: Path, old: Path, rel: str = "") -> list[str]:
    """``new`` (上流) と ``old`` (取り込み済み) の差分を、``+ 追加`` / ``- 削除`` / ``M 変更`` で返す。"""
    out: list[str] = []
    if not old.is_dir():
        return [f"+ {rel or '.'} (新規)"]
    cmp = filecmp.dircmp(new, old, ignore=sorted(IGNORED))
    out += [f"+ {rel}{n}" for n in sorted(cmp.left_only)]
    out += [f"- {rel}{n}" for n in sorted(cmp.right_only)]
    out += [f"M {rel}{n}" for n in sorted(cmp.diff_files)]
    for sub in sorted(cmp.common_dirs):
        out += _diff(new / sub, old / sub, f"{rel}{sub}/")
    return out


def _update_doc(doc: Path, commit: str, date: str, count: int) -> bool:
    if not doc.is_file():
        return False
    text = doc.read_text(encoding="utf-8")
    new = re.sub(
        r"skill-lab のコミット `[0-9a-f]+`（[0-9-]+）",
        f"skill-lab のコミット `{commit}`（{date}）",
        text,
        count=1,
    )
    new = re.sub(r"（\d+ 件。`git archive`", f"（{count} 件。`git archive`", new, count=1)
    if new == text:
        return False
    doc.write_text(new, encoding="utf-8")
    return True


def sync(skill: str, src: Path, repo: Path = REPO, check: bool = False) -> int:
    if not NAME.match(skill):
        raise SyncError(f"スキル名が不正: {skill!r}")
    if not (src / ".git").exists():
        raise SyncError(f"skill-lab が見つからない: {src}")
    if not _git(src, "ls-tree", "-d", "HEAD", f"skills/{skill}").strip():
        raise SyncError(f"skill-lab の HEAD に skills/{skill} が無い")
    dirty = (
        _git(src, "status", "--porcelain", "--", f"skills/{skill}")
        .decode("utf-8", "replace")
        .strip()
    )
    if dirty:
        raise SyncError(
            "skill-lab に未コミットの変更がある。コミットしてから実行する (取り込むのはコミット済みの版だけ):\n"
            + dirty
        )
    commit = _git(src, "rev-parse", "--short=7", "HEAD").decode().strip()
    date = _git(src, "log", "-1", "--format=%cs", "HEAD", "--", f"skills/{skill}").decode().strip()
    dest = repo / "home" / "dot_claude" / "skills" / skill
    with tempfile.TemporaryDirectory() as tmp:
        new = Path(tmp) / skill
        new.mkdir()
        count = _extract(src, skill, new)
        diff = _diff(new, dest)
        print(f"skill-lab {commit} ({date}): {count} ファイル。差分 {len(diff)} 件")
        for line in diff:
            print("  " + line)
        if check:
            return 1 if diff else 0
        if not diff:
            print("すでに同じ。何もしない")
            return 0
        # 実行時に生えたもの (.venv など) は消さずに残す
        keep = {p.name: p for p in dest.iterdir() if p.name in IGNORED} if dest.is_dir() else {}
        if dest.is_dir():
            for child in dest.iterdir():
                if child.name in IGNORED:
                    continue
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        shutil.copytree(new, dest, dirs_exist_ok=True)
        del keep
    doc = repo / "docs" / "spec" / f"{skill}.md"
    if _update_doc(doc, commit, date, count):
        print(f"{doc.relative_to(repo)} の「取り込んだ版」を更新した")
    else:
        print(f"注意: docs/spec/{skill}.md の「取り込んだ版」を更新できなかった (手で直す)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("skill", help="skill-lab の skills/ 直下の名前")
    ap.add_argument(
        "--src", type=Path, default=DEFAULT_SRC, help=f"skill-lab のパス (既定 {DEFAULT_SRC})"
    )
    ap.add_argument(
        "--check", action="store_true", help="差分を表示するだけ (差分があれば終了コード 1)"
    )
    args = ap.parse_args(argv)
    try:
        return sync(args.skill, args.src.expanduser(), check=args.check)
    except SyncError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
