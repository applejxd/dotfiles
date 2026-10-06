"""コミットの計画を固定・表示・実行するスクリプト (``commit_plan.py``) の test.

一時の git リポジトリで、計画の固定・表示・状態の確かめ・単位ごとのコミットを確かめる。
see docs/change/0014-deterministic-commit-runner.md

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "home" / "dot_claude" / "skills" / "commit" / "scripts" / "commit_plan.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "core.hooksPath", "/dev/null")
    (r / "a.py").write_text("a = 1\n")
    (r / "README.md").write_text("# x\n")
    (r / "old.txt").write_text("old\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "init")
    (r / "a.py").write_text("a = 2\n")
    (r / "README.md").write_text("# y\n")
    (r / "new dir").mkdir()
    (r / "new dir" / "n.txt").write_text("n\n")
    (r / "old.txt").unlink()
    return r


def snapshot(repo: Path) -> str:
    out = run(repo, "snapshot")
    assert out.returncode == 0, out.stderr
    return out.stdout.splitlines()[0].split(": ")[1]


PLAN = {
    "units": [
        {
            "paths": ["a.py", "old.txt"],
            "message": "feat: a を 2 にする\n\n- Change: [1/1] a と old",
        },
        {"paths": ["README.md"], "message": "docs: README を直す"},
    ]
}


def test_full_flow_commits_each_unit_and_leaves_the_rest(repo):
    plan_id = snapshot(repo)
    saved = run(repo, "save", plan_id, json.dumps(PLAN, ensure_ascii=False))
    assert saved.returncode == 0, saved.stderr
    shown = run(repo, "show", plan_id)
    assert shown.stdout.rstrip("\n") == saved.stdout.rstrip("\n")
    assert "[1/2] 対象 2 件" in shown.stdout
    assert "  - Change: [1/1] a と old" in shown.stdout
    assert "コミットしない変更 1 件" in shown.stdout and "new dir/n.txt" in shown.stdout

    applied = run(repo, "apply", plan_id)
    assert applied.returncode == 0, applied.stderr
    log = git(repo, "log", "--format=%s", "-3").splitlines()
    assert log == ["docs: README を直す", "feat: a を 2 にする", "init"]
    assert git(repo, "show", "--name-status", "--format=", "HEAD~1").split() == [
        "M",
        "a.py",
        "D",
        "old.txt",
    ]
    body = git(repo, "log", "-1", "--format=%B", "HEAD~1").strip()
    assert body == PLAN["units"][0]["message"]
    assert git(repo, "status", "--porcelain", "-z", "-uall").strip("\0") == "?? new dir/n.txt"


def test_apply_twice_is_refused(repo):
    plan_id = snapshot(repo)
    run(repo, "save", plan_id, json.dumps(PLAN))
    assert run(repo, "apply", plan_id).returncode == 0
    again = run(repo, "apply", plan_id)
    assert again.returncode == 1 and "実行済み" in again.stderr


def test_save_once(repo):
    plan_id = snapshot(repo)
    assert run(repo, "save", plan_id, json.dumps(PLAN)).returncode == 0
    again = run(repo, "save", plan_id, json.dumps(PLAN))
    assert again.returncode == 1 and "保存済み" in again.stderr


def test_file_changed_after_snapshot_is_refused(repo):
    plan_id = snapshot(repo)
    run(repo, "save", plan_id, json.dumps(PLAN))
    (repo / "a.py").write_text("a = 3\n")
    out = run(repo, "apply", plan_id)
    assert out.returncode == 1 and "a.py が変わりました" in out.stderr
    assert git(repo, "log", "--format=%s", "-1").strip() == "init"


def test_staged_changes_are_refused(repo):
    git(repo, "add", "README.md")
    out = run(repo, "snapshot")
    assert out.returncode == 1 and "ステージ済み" in out.stderr


def test_staged_after_plan_is_refused(repo):
    plan_id = snapshot(repo)
    run(repo, "save", plan_id, json.dumps(PLAN))
    git(repo, "add", "new dir/n.txt")
    out = run(repo, "apply", plan_id)
    assert out.returncode == 1 and "ステージ済み" in out.stderr


def test_head_moved_is_refused(repo):
    plan_id = snapshot(repo)
    run(repo, "save", plan_id, json.dumps(PLAN))
    git(repo, "commit", "-q", "--allow-empty", "-m", "other")
    out = run(repo, "apply", plan_id)
    assert out.returncode == 1 and "HEAD" in out.stderr


def test_plan_text_tampering_is_refused(repo):
    plan_id = snapshot(repo)
    run(repo, "save", plan_id, json.dumps(PLAN))
    plan_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip()) / "commit-plan" / plan_id
    plan = json.loads((plan_dir / "plan.json").read_text())
    plan["units"][1]["message"] = "docs: 書き換えた"
    (plan_dir / "plan.json").write_text(json.dumps(plan))
    out = run(repo, "apply", plan_id)
    assert out.returncode == 1 and "食い違います" in out.stderr


@pytest.mark.parametrize(
    ("plan", "error"),
    [
        ({"units": []}, "units"),
        ({"units": [{"paths": ["nope.py"], "message": "x"}]}, "snapshot の変更にありません"),
        (
            {"units": [{"paths": ["a.py"], "message": "x"}, {"paths": ["a.py"], "message": "y"}]},
            "複数の単位",
        ),
        ({"units": [{"paths": ["a.py"], "message": "\n\n"}]}, "件名"),
        ({"units": [{"paths": ["a.py"], "message": "x", "extra": 1}]}, "paths と message だけ"),
        ({"units": [{"paths": [], "message": "x"}]}, "paths"),
    ],
)
def test_invalid_plans_are_refused(repo, plan, error):
    plan_id = snapshot(repo)
    out = run(repo, "save", plan_id, json.dumps(plan))
    assert out.returncode == 1 and error in out.stderr


def test_broken_json_is_refused(repo):
    plan_id = snapshot(repo)
    out = run(repo, "save", plan_id, "{not json")
    assert out.returncode == 1 and "JSON" in out.stderr


def test_in_progress_merge_is_refused(repo):
    gd = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    (gd / "MERGE_HEAD").write_text("0" * 40)
    out = run(repo, "snapshot")
    assert out.returncode == 1 and "進行中" in out.stderr


def test_unknown_plan_id_is_refused(repo):
    out = run(repo, "show", "20990101-000000-abcdef")
    assert out.returncode == 1 and "見つかりません" in out.stderr
    bad = run(repo, "show", "../x")
    assert bad.returncode == 1 and "形が違います" in bad.stderr


def test_hook_failure_stops_and_reports(repo):
    hooks = repo / ".hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho no >&2\nexit 1\n")
    (hooks / "pre-commit").chmod(0o755)
    git(repo, "config", "core.hooksPath", str(hooks))
    plan_id = snapshot(repo)
    plan = {"units": [{"paths": ["a.py"], "message": "feat: a"}]}
    run(repo, "save", plan_id, json.dumps(plan))
    out = run(repo, "apply", plan_id)
    assert out.returncode == 1 and "[1/1] で止まりました" in out.stderr
    assert git(repo, "log", "--format=%s", "-1").strip() == "init"


def test_usage_errors():
    assert run(Path.cwd(), "apply").returncode == 2
    assert run(Path.cwd(), "unknown", "x").returncode == 2


def test_old_plans_are_pruned_on_snapshot(repo):
    base = Path(git(repo, "rev-parse", "--absolute-git-dir").strip()) / "commit-plan"
    old = base / "20200101-000000-aaaaaa"
    recent = base / "20261005-000000-bbbbbb"
    other = base / "keep-me"
    for d in (old, recent, other):
        d.mkdir(parents=True)
        (d / "snapshot.json").write_text("{}")
    stale = time.time() - 8 * 24 * 60 * 60
    for d in (old, other):
        os.utime(d, (stale, stale))
    out = run(repo, "snapshot")
    assert out.returncode == 0, out.stderr
    assert "1 件消しました" in out.stdout
    assert not old.exists()
    assert recent.exists(), "7 日以内は残す"
    assert other.exists(), "計画 ID の形でない名前には触れない"
