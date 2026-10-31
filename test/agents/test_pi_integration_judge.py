"""統合コマンドの検出器 (judge/gitintegration.ts) の表試験。

期待結果 (コマンド → kind) の表を持ち、node のドライバーに通して比べる。
主眼は、負例 (none) が確認の対象にならないこと。
see docs/change/0053-worktree-integration-gate.md
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "test" / "agents" / "pi" / "integration_driver.mjs"


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    return node if (major, minor) >= (22, 18) else None


pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

FLOW_TYPES = ["feature", "release", "hotfix", "support", "bugfix"]

ALWAYS = [
    *[f"git flow {t} finish x" for t in FLOW_TYPES],
    *[f"git flow {t} delete x" for t in FLOW_TYPES],
    *[f"git flow {t} abort" for t in FLOW_TYPES],
    "git flow integrate",
    "git-flow feature finish x",
    "git-flow integrate",
    "git flow feature finish --squash x",
    "git flow feature finish -r -k x",
    "git -c user.name=x flow feature finish x",
    "FOO=1 git flow feature finish x",
    "env git flow feature finish x",
    "env FOO=1 git flow feature finish x",
    "command git flow feature finish x",
    "git log; git flow feature finish x",
    "git status && git flow release finish v1",
    "git update-ref refs/heads/develop abc123",
    "git update-ref develop abc123",
    "git update-ref -m msg refs/heads/main abc123",
    "git update-ref -d refs/heads/develop",
    "git update-ref --delete develop",
    "git symbolic-ref HEAD refs/heads/develop",
    "git symbolic-ref refs/heads/main refs/heads/feature/x",
    "git branch -m Develop x",
    "git branch -M main",
    "git branch --move develop x",
    "git branch -c develop copy",
    "git branch -C x develop",
    "git branch --copy x main",
    "git branch -f develop abc",
    "git branch --force main HEAD~1",
    "git branch -m refs/heads/develop old",
    "git branch develop",
    "git branch develop abc123",
    "git branch refs/heads/main",
    "git fetch origin feature/x:develop",
    "git fetch origin +feature/x:develop",
    "git fetch origin +refs/heads/x:refs/heads/main",
    "git fetch . x:Develop",
    "git worktree add -B develop ../w",
    "git worktree add -b develop ../w",
    "git worktree add ../w -B main origin/main",
    "git worktree add -Bdevelop ../w",
]

UNKNOWN = [
    "git update-ref --stdin",
    "git update-ref --stdin -z",
    "git reflog delete HEAD@{1}",
    "git reflog expire --expire=now --all",
    "git fast-import",
    "cd x && git merge y",
    "pushd ../repo; git cherry-pick abc",
    "git -C ../repo merge y",
    "git --git-dir=/x/.git merge y",
    "git --work-tree /x merge y",
    "GIT_DIR=/x/.git git merge y",
    "GIT_WORK_TREE=/x git pull",
    "cd x && git flow feature finish a",
    "git -C ../repo branch -m develop x",
    "git -c alias.m=merge m y",
    "git update-ref $REF abc",
    "git update-ref refs/heads/$B abc",
    "git branch -m $OLD new",
    "git branch $NAME",
    "git branch -m feature/* x",
    "git fetch origin x:$DST",
    "git fetch origin +refs/heads/*:refs/heads/*",
    "git fetch origin x:`echo develop`",
    "git worktree add -B $B ../w",
    "git symbolic-ref HEAD $(cat ref)",
    'git merge "x',
    "git flow feature finish 'x",
]

HEAD = [
    "git merge x",
    "git merge --no-ff feature/x",
    "git cherry-pick abc123",
    "git revert HEAD",
    "git pull",
    "git pull origin develop",
    "git am patch.mbox",
    "git reset",
    "git reset HEAD~1",
    "git reset --soft HEAD~1",
    "git reset --mixed HEAD~1",
    "git reset --merge",
    "git reset --keep abc",
    "git status && git merge a",
    "FOO=1 git merge x",
    "env git merge x",
    "command git merge x",
    "git -c user.name=x merge y",
    "git --no-pager merge y",
    "git update-ref HEAD abc123",
    "/usr/bin/git merge x",
]

NONE = [
    "git checkout develop",
    "git checkout refs/heads/main",
    "git switch develop",
    "git switch main",
    "git checkout -B develop",
    "git switch -C develop",
    "git switch --force-create develop",
    "git log",
    "git diff develop",
    "git show HEAD",
    "git status",
    "git rev-parse develop",
    "git ls-files",
    "git blame x",
    "git branch",
    "git branch --list",
    "git branch --list 'feat*'",
    "git branch -v",
    "git branch --show-current",
    "git branch -a",
    "git fetch",
    "git fetch origin",
    "git fetch origin develop",
    "git fetch origin feature/x:feature/y",
    "git fetch origin +refs/heads/*:refs/remotes/origin/*",
    "git fetch origin x:refs/remotes/origin/develop",
    "git fetch origin x:origin/develop",
    "git branch feature/a",
    "git branch feature/a develop",
    "git branch -m feature/a feature/b",
    "git branch origin/develop",
    "git branch refs/remotes/origin/develop",
    "git branch --set-upstream-to=origin/develop",
    "git flow feature start x",
    "git flow feature list",
    "git flow feature config",
    "git flow feature publish x",
    "git flow init",
    "git-flow feature start x",
    "git stash",
    "git tag v1",
    "git add .",
    "git commit -m x",
    'git commit -m "git merge"',
    "git rebase develop",
    "git reset --hard HEAD~1",
    "git push origin develop",
    "git push . x:develop",
    "git symbolic-ref HEAD",
    "git symbolic-ref --short HEAD",
    "git symbolic-ref -q HEAD",
    "git symbolic-ref -d refs/heads/develop",
    "git symbolic-ref HEAD refs/heads/feature/x",
    "git update-ref refs/heads/feature/x abc123",
    "git update-ref refs/remotes/origin/develop abc123",
    "git worktree add ../w feature/x",
    "git worktree add -b feature/y ../w develop",
    "git worktree add -B feature/y ../w",
    "git worktree list",
    "git reflog",
    "git reflog show",
    "cd x && git status",
    "git -C ../repo status",
    "GIT_DIR=/x git log",
    'echo "git merge x"',
    "echo 'git flow feature finish x'",
    'grep "git flow feature finish" file',
    'git log --grep="git merge"',
    "cat <<'EOF'\ngit merge x\ngit flow feature finish y\nEOF",
    "cat <<EOF > f\ngit update-ref develop abc\nEOF",
    'echo "unterminated',
    "ls -la",
    "",
    "   ",
    "\n\t",
    "echo " + "a" * 100000,
]


def _rows() -> list[tuple[str, str]]:
    rows = [(c, "always") for c in ALWAYS]
    rows += [(c, "unknown") for c in UNKNOWN]
    rows += [(c, "head") for c in HEAD]
    rows += [(c, "none") for c in NONE]
    return rows


def _run(cases: list[dict]) -> list[dict]:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps({"cases": cases}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_table_matches_the_detector():
    rows = _rows()
    results = _run([{"command": c} for c, _ in rows])
    assert len(results) == len(rows)
    wrong = [
        f"{c[:80]!r}: 期待 {want}, 実際 {got['kind']} ({got['reason']})"
        for (c, want), got in zip(rows, results, strict=True)
        if got["kind"] != want
    ]
    assert not wrong, "\n".join(wrong)


def test_every_kind_has_positive_and_negative_rows():
    assert ALWAYS and UNKNOWN and HEAD and NONE
    assert len(_rows()) > 150


def test_reason_is_present_unless_none():
    rows = _rows()
    results = _run([{"command": c} for c, _ in rows])
    for (c, want), got in zip(rows, results, strict=True):
        if want != "none":
            assert got["reason"], c


def test_custom_protected_refs():
    cases = [
        {"command": "git branch -m release/1.0 x", "protected": ["release/*"]},
        {"command": "git branch -m release x", "protected": ["release/*"]},
        {"command": "git branch -m develop x", "protected": ["main"]},
        {"command": "git branch -m develop x", "protected": []},
    ]
    assert [r["kind"] for r in _run(cases)] == ["always", "none", "none", "none"]


def test_huge_input_is_fast():
    start = time.monotonic()
    out = _run([{"command": "echo " + "a" * 100000}])
    assert out[0]["kind"] == "none"
    # node の起動を含めても 1 秒を超えない
    assert time.monotonic() - start < 1.0
