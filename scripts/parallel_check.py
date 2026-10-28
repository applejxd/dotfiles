#!/usr/bin/env python3
"""並列実装の混線の検査: 子が終わるたびに、親が取り込み前に実行する。

次を調べて、問題があれば終了コード 1 で終わる (読み取りだけ。何も変更しない)。
  1. 本体の作業ツリーに、変更が無いこと (子は feature の worktree の中だけに書く約束)
  2. 各 feature の worktree の変更 (未コミット + develop より先のコミット) が、`--owned` で宣言した範囲に収まること
  3. 2 つ以上の worktree が、同じファイルを変更していないこと (finish で衝突する)

使い方 (リポジトリのルートで):
    python3 scripts/parallel_check.py --owned a=docs/a.md,test/test_a.py --owned b='scripts/b/**'

`--owned NAME=GLOB[,GLOB...]` は、feature/NAME の worktree が変更してよいパス (fnmatch。`**` は任意の深さ)。
宣言の無い worktree は、変更の一覧を出すだけ (範囲の検査はしない)。
see docs/spec/guard/pi-subagents.md#並列実装の運用
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

WORKTREES_DIR = ".tmp/worktrees"
BASE_BRANCH = "develop"


def git(cwd: Path, *args: str) -> str:
    # 読み取りだけ: hook・fsmonitor を動かさず、任意ロック (index の更新) と端末入力を止める
    r = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} が失敗した ({cwd}): {r.stderr.strip()}")
    return r.stdout


def status_paths(cwd: Path) -> list[str]:
    """未コミットの変更 (追跡の変更・未追跡のファイル。ignore されたものは除く)。リネームは新旧の両方。"""
    out = git(cwd, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    paths: list[str] = []
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        code, path = e[:2], e[3:]
        paths.append(path)
        if "R" in code or "C" in code:
            if i < len(entries) and entries[i]:
                paths.append(entries[i])
            i += 1
    return paths


def committed_paths(cwd: Path, branch: str) -> list[str]:
    """develop より先のコミットで変更されたパス (develop との分岐点からの差分)。"""
    out = git(cwd, "diff", "--name-only", "--no-renames", "-z", f"{BASE_BRANCH}...{branch}")
    return [p for p in out.split("\0") if p]


def feature_worktrees(root: Path) -> dict[str, Path]:
    """`.tmp/worktrees/` の下にある feature の worktree: {名前: パス}。"""
    out = git(root, "worktree", "list", "--porcelain", "-z")
    found: dict[str, Path] = {}
    path: Path | None = None
    base = (root / WORKTREES_DIR).resolve()
    for line in out.split("\0"):
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line.startswith("branch refs/heads/feature/") and path is not None:
            name = line[len("branch refs/heads/feature/") :]
            try:
                if path.resolve().is_relative_to(base):
                    found[name] = path
            except OSError:
                pass
    return found


def matches(path: str, globs: list[str]) -> bool:
    for g in globs:
        # `dir/**` は dir の下のすべて。それ以外は fnmatch (`*` は `/` も含む)
        if g.endswith("/**"):
            if path == g[:-3] or path.startswith(g[:-2]):
                return True
        elif fnmatch.fnmatch(path, g):
            return True
    return False


def parse_owned(values: list[str]) -> dict[str, list[str]]:
    owned: dict[str, list[str]] = {}
    for v in values:
        name, sep, globs = v.partition("=")
        if not sep or not name or not globs:
            raise SystemExit(f"--owned は NAME=GLOB[,GLOB...] の形: {v!r}")
        items = [g for g in globs.split(",") if g]
        for g in items:
            # `**` は末尾の `/**` だけ。途中の `**` は fnmatch では意味が違うので受け付けない
            if "**" in g and not (g.endswith("/**") and "**" not in g[:-3]):
                raise SystemExit(f"--owned の glob の `**` は `dir/**` の形だけ: {g!r}")
            if g.startswith("/") or ".." in g.split("/"):
                raise SystemExit(f"--owned の glob は、リポジトリからの相対パス: {g!r}")
        owned[name] = items
    return owned


def check(root: Path, owned: dict[str, list[str]]) -> dict:
    problems: list[str] = []
    # 1. 本体の作業ツリー
    main_changes = status_paths(root)
    if main_changes:
        problems.append(
            "本体の作業ツリーに変更がある (子は worktree の中だけに書く約束): "
            + ", ".join(sorted(main_changes))
        )
    # 2. 各 worktree
    trees = feature_worktrees(root)
    changed: dict[str, list[str]] = {}
    for name, path in sorted(trees.items()):
        files = sorted(set(status_paths(path)) | set(committed_paths(root, f"feature/{name}")))
        changed[name] = files
        if name in owned:
            outside = [f for f in files if not matches(f, owned[name])]
            if outside:
                problems.append(
                    f"feature/{name} が、宣言した範囲の外を変更した: " + ", ".join(outside)
                )
    for name in owned:
        if name not in trees:
            problems.append(
                f"--owned の feature/{name} の worktree が見つからない ({WORKTREES_DIR} の下)"
            )
    # 3. 重複
    seen: dict[str, list[str]] = {}
    for name, files in changed.items():
        for f in files:
            seen.setdefault(f, []).append(name)
    for f, names in sorted(seen.items()):
        if len(names) > 1:
            problems.append(
                f"{f} を複数の feature が変更している ({', '.join(names)})。finish で衝突する"
            )
    return {
        "ok": not problems,
        "problems": problems,
        "main_changes": main_changes,
        "worktrees": changed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--owned", action="append", default=[], metavar="NAME=GLOB[,GLOB...]")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    args = ap.parse_args(argv)
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    result = check(root, parse_owned(args.owned))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"本体の変更: {len(result['main_changes'])} 件")
        for name, files in result["worktrees"].items():
            print(
                f"feature/{name}: {len(files)} ファイル"
                + (": " + ", ".join(files) if files else "")
            )
        if result["ok"]:
            print("OK: 混線は見つからなかった")
        else:
            print("問題:")
            for p in result["problems"]:
                print(f"  - {p}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
