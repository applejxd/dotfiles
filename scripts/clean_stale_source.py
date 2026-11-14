#!/usr/bin/env python3
"""`.chezmoiremove` の対象に対応する source 側の残骸ディレクトリを消す。

`.chezmoiremove` に載った対象と同名の source ディレクトリが、Git 管理外の
残骸 (`__pycache__` など) だけで残ると、chezmoi は inconsistent state で止まる。
chezmoi.toml の `hooks.read-source-state.pre` から呼ぶ。
仕組み・撤去条件は docs/spec/structure.md#source-側の残骸の掃除 を参照。
TEMP-REMOVE: chezmoi が対応するか、.chezmoiremove を廃止したら削除する。

標準ライブラリだけで動く。追跡ファイルがあるディレクトリは消さず、警告だけ出す。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# source 名の属性接頭辞。順不同・重複して付くので、付かなくなるまで外す
_PREFIXES = (
    "exact_",
    "private_",
    "readonly_",
    "executable_",
    "symlink_",
    "empty_",
    "create_",
    "modify_",
    "remove_",
    "literal_",
    "encrypted_",
    "once_",
    "onchange_",
    "before_",
    "after_",
    "run_",
)
_SUFFIXES = (".tmpl", ".literal")
_GLOB_CHARS = set("*?[")


def target_name(source_name: str) -> str:
    """source の名前から、属性接頭辞・接尾辞を外した target 名を返す。"""
    name = source_name
    stripped = True
    while stripped:
        stripped = False
        for prefix in _PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix) :]
                stripped = True
                if prefix == "literal_":
                    # literal_ 以降は文字どおりの名前 (dot_ なども解釈しない)
                    return name
    if name.startswith("dot_"):
        name = "." + name[len("dot_") :]
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def read_entries(chezmoiremove: Path) -> list[tuple[str, ...]]:
    """`.chezmoiremove` のエントリを要素の列にして返す。解釈できない行は読み飛ばす。"""
    entries: list[tuple[str, ...]] = []
    for raw in chezmoiremove.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "{{" in line or "}}" in line or _GLOB_CHARS & set(line):
            continue
        parts = tuple(p for p in line.replace("\\", "/").split("/") if p)
        if not parts or ".." in parts or "." in parts:
            continue
        entries.append(parts)
    return entries


def find_source_dirs(home: Path, parts: tuple[str, ...]) -> list[Path]:
    """target の要素列に対応する source ディレクトリを、接頭辞を無視して探す。"""
    current = [home]
    for part in parts:
        nxt: list[Path] = []
        for base in current:
            for child in sorted(base.iterdir()):
                if child.is_symlink() or not child.is_dir():
                    continue
                if target_name(child.name) == part:
                    nxt.append(child)
        current = nxt
        if not current:
            return []
    return current


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    # 継承した GIT_INDEX_FILE などでリポジトリ・index が差し替わると、追跡の判定が狂う
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None


def is_own_git_root(root: Path) -> bool:
    """root 自身が git のワークツリーの最上位かを返す (外側のリポジトリを誤用しない)。"""
    proc = _git(root, "rev-parse", "--show-toplevel")
    if proc is None or proc.returncode != 0:
        return False
    return Path(proc.stdout.strip()).resolve() == root.resolve()


def has_tracked_files(root: Path, directory: Path) -> bool | None:
    """残すべきファイル (追跡中、または未追跡かつ ignored でないもの) の有無を返す。

    git で確かめられないときは None。ignored な残骸 (__pycache__ など) だけなら False。
    """
    rel = directory.relative_to(root).as_posix()
    proc = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", rel)
    if proc is None or proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def clean(root: Path, dry_run: bool) -> int:
    """残骸を消す。消した (dry-run なら消す予定の) 数を返す。"""
    home = root / "home"
    chezmoiremove = home / ".chezmoiremove"
    if not chezmoiremove.is_file() or not home.is_dir() or home.is_symlink():
        return 0
    if not is_own_git_root(root):
        print(
            f"警告: {root} は git 管理外か確かめられないため、何も消しません",
            file=sys.stderr,
        )
        return 0
    removed = 0
    seen: set[Path] = set()
    for parts in read_entries(chezmoiremove):
        for directory in find_source_dirs(home, parts):
            if directory in seen:
                continue
            seen.add(directory)
            tracked = has_tracked_files(root, directory)
            if tracked is None:
                print(f"警告: git で確かめられないため残します: {directory}", file=sys.stderr)
            elif tracked:
                print(
                    f"警告: .chezmoiremove の対象 {'/'.join(parts)} の source に追跡中・未追跡の"
                    f"ファイルがあるため残します (source を消すか .chezmoiremove から外してください): {directory}",
                    file=sys.stderr,
                )
            else:
                print(f"{'削除予定' if dry_run else '削除'}: {directory}")
                if not dry_run:
                    shutil.rmtree(directory)
                removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="source のルート (home/ を含むリポジトリ。既定はこのスクリプトの位置から推定)",
    )
    parser.add_argument("--dry-run", action="store_true", help="消さずに対象を表示する")
    args = parser.parse_args(argv)
    clean(args.source.resolve(), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
