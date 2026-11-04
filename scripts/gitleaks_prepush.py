#!/usr/bin/env python3
"""pre-push 段の秘密検出: これから push するコミットの全履歴を gitleaks で検査する。

pre-commit 段の gitleaks は `--staged` だけで、ジョブの commit（commit-tree）や統合の
merge commit・途中コミットは通らない。push の直前に、範囲内の全コミットの差分を見る。
範囲は pre-commit が渡す環境変数 PRE_COMMIT_FROM_REF / PRE_COMMIT_TO_REF から組み立てる。
see docs/spec/development.md#hook-の-stage-の分け方
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ZERO_SHA = "0" * 40


def is_empty_ref(ref: str | None) -> bool:
    """空・全ゼロ（新規ブランチ・削除）の ref か。"""
    return not ref or set(ref) == {"0"}


def build_log_opts(
    from_ref: str | None, to_ref: str | None, from_exists: bool = True
) -> str | None:
    """`git log` に渡す範囲を返す。検査するものが無い（ブランチ削除の push）ときは None。

    - 通常の更新: `<from>..<to>`
    - 新規ブランチ（from が空・全ゼロ）、または from がローカルに無い: リモートに無いコミットだけ
    """
    if to_ref is not None and to_ref != "" and set(to_ref) == {"0"}:
        return None
    to = to_ref or "HEAD"
    if is_empty_ref(from_ref) or not from_exists:
        return f"{to} --not --remotes"
    return f"{from_ref}..{to}"


def _ref_exists(ref: str) -> bool:
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def gitleaks_command() -> list[str] | None:
    """gitleaks の起動コマンド。mise 経由を優先し、無ければ PATH 上のものを使う。"""
    if shutil.which("mise"):
        return ["mise", "exec", "--", "gitleaks"]
    if shutil.which("gitleaks"):
        return ["gitleaks"]
    return None


def main() -> int:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    exists = is_empty_ref(from_ref) or _ref_exists(from_ref or "")
    opts = build_log_opts(from_ref, to_ref, exists)
    if opts is None:
        return 0
    cmd = gitleaks_command()
    if cmd is None:
        print("gitleaks が見つからない。push 前の秘密検出ができないので拒否する", file=sys.stderr)
        return 2
    return subprocess.run(
        [*cmd, "git", "--redact", "--verbose", f"--log-opts={opts}", "."],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
