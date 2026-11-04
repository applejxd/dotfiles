#!/usr/bin/env python3
"""ステージ済みの変更で、既存ファイルが空になっていないかを検査する（pre-commit の local hook）。

HEAD で 20 行以上あったファイルが、ステージ後に空（0 バイト・空白と改行だけ）なら失敗（終了コード 1）。
80% 以上減ったファイルは警告だけ出す（終了コード 0）。変更（M）のファイルだけが対象。
see docs/spec/development.md#ステージの空ファイル検査
"""

from __future__ import annotations

import subprocess
import sys

MIN_LINES = 20  # この行数以上のファイルが空になったら失敗
SHRINK_RATIO = 0.8  # この割合以上減ったら警告
MAX_REPORT = 20  # 1 種類あたりの出力上限


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], capture_output=True, check=False)


def _modified_paths() -> list[str]:
    r = _git("diff", "--cached", "--name-status", "-z", "--no-renames")
    if r.returncode != 0:
        return []
    parts = r.stdout.decode("utf-8", "surrogateescape").split("\0")
    paths: list[str] = []
    i = 0
    while i + 1 < len(parts):
        status, path = parts[i], parts[i + 1]
        i += 2
        if status == "M":
            paths.append(path)
    return paths


def _count_lines(data: bytes) -> int:
    return len(data.splitlines())


def main() -> int:
    if _git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return 0  # 初回コミット
    emptied: list[tuple[str, int]] = []
    shrunk: list[tuple[str, int, int]] = []
    for path in _modified_paths():
        head = _git("show", f"HEAD:{path}")
        new = _git("show", f":{path}")
        if head.returncode != 0 or new.returncode != 0 or b"\0" in head.stdout:
            continue
        before = _count_lines(head.stdout)
        if before < MIN_LINES:
            continue
        if not new.stdout.strip():
            emptied.append((path, before))
            continue
        after = _count_lines(new.stdout)
        if after <= before * (1 - SHRINK_RATIO):
            shrunk.append((path, before, after))
    for path, before, after in shrunk[:MAX_REPORT]:
        print(
            f"警告: 大きく減りました: {path} {before} → {after} 行。意図したものか確認してください"
        )
    for path, n in emptied[:MAX_REPORT]:
        print(
            f"ファイルが空になっています: {path}（HEAD では {n} 行）。意図しない場合は内容を戻してください"
            f"（編集ツールで書き直す。`git show HEAD:{path}` で元の内容を確認できる）。"
            "ファイルを消したいなら削除してください（空にしない）"
        )
    if len(emptied) > MAX_REPORT:
        print(f"ほか {len(emptied) - MAX_REPORT} 件")
    return 1 if emptied else 0


if __name__ == "__main__":
    sys.exit(main())
