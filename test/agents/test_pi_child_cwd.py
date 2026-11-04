"""``guarded_task`` の ``cwd`` (子の実行場所の指定) の統合試験。

偽のモデル (faux) の親が worker を ``cwd`` つきで起動し、登録された worktree でだけ子が動くこと・拒否の理由・
本体の汚れの警告を、使い捨ての git リポジトリで確かめる。git・pi が無い環境では skip する。
see docs/spec/guard/pi-subagents.md
"""

# ruff: noqa: F811  (env / repo はインポートしたフィクスチャ。引数名で使うので再定義に見える)
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_pi_harness import PI, env  # noqa: F401
from test_pi_isolation import bash, git, repo, run_task  # noqa: F401

pytestmark = pytest.mark.skipif(
    PI is None or shutil.which("git") is None, reason="pi か git が無い"
)

WARN = "⚠ 本体の作業ツリーに、子の起動前に無かった変更が入っている"


@pytest.fixture
def linked(repo):
    """repo の linked worktree (repo/.tmp/wt-a。.tmp は無視される)。"""
    wt = repo / ".tmp" / "wt-a"
    git(repo, "worktree", "add", "-q", "-b", "feature/a", str(wt))
    return wt.resolve()


def worker(cwd: str, **more):
    return {"agent": "worker", "task": "do it", "cwd": cwd, **more}


def test_child_runs_in_a_registered_linked_worktree(env, repo, linked):
    proc = run_task(env, repo, worker(str(linked)), bash("pwd"))
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert str(linked) in out, out
    assert "cwd refused" not in out, out
    assert WARN not in out, out


def test_child_runs_in_the_main_worktree_without_warning(env, repo):
    out = run_task(env, repo, worker(str(repo)), bash(f"touch {repo}/by-child.txt")).stdout
    assert "cwd refused" not in out, out
    assert WARN not in out, out


def test_batch_items_accept_cwd_and_refuse_an_unregistered_one(env, repo, linked):
    rounds = {
        "tasks": [
            {"agent": "worker", "task": "ok", "cwd": str(linked)},
            {"agent": "worker", "task": "bad", "cwd": str(repo / "sub")},
        ]
    }
    out = run_task(env, repo, rounds, bash("pwd")).stdout
    assert "cwd refused: 親のリポジトリの git worktree に登録されていない" in out, out
    assert str(linked) in out, out


@pytest.mark.parametrize(
    ("make", "why"),
    [
        (lambda repo, linked: str(repo / "sub"), "登録されていない"),
        (lambda repo, linked: "relative/path", "絶対パスでない"),
        (lambda repo, linked: str(repo / "no-such-dir"), "存在しない"),
        (lambda repo, linked: str(linked) + "/../wt-a", "`..`"),
        (lambda repo, linked: str(linked / ".git"), "`.git`"),
    ],
)
def test_unregistered_or_malformed_cwd_is_refused_and_no_child_starts(env, repo, linked, make, why):
    out = run_task(env, repo, worker(make(repo, linked)), bash("pwd")).stdout
    assert "cwd refused" in out and why in out, out
    assert "child worker" not in out, out


def test_symlink_to_a_registered_worktree_is_refused(env, repo, linked):
    link = repo / ".tmp" / "wt-link"
    link.symlink_to(linked)
    out = run_task(env, repo, worker(str(link)), bash("pwd")).stdout
    assert "cwd refused" in out and "シンボリックリンク" in out, out
    assert "child worker" not in out, out


def test_another_repository_is_refused(env, repo, linked, tmp_path_factory):
    other = Path(tmp_path_factory.mktemp("other-repo")).resolve()
    git(other, "init", "-q", "-b", "main")
    out = run_task(env, repo, worker(str(other)), bash("pwd")).stdout
    assert "cwd refused" in out and "登録されていない" in out, out
    assert "child worker" not in out, out


def test_cwd_with_isolation_is_refused(env, repo, linked):
    out = run_task(env, repo, worker(str(linked), isolation="worktree"), bash("pwd")).stdout
    assert "cwd" in out and "isolation" in out and "invalid guarded_task input" in out, out
    assert "child worker" not in out, out


def test_a_dirtied_main_tree_adds_a_warning(env, repo, linked):
    out = run_task(env, repo, worker(str(linked)), bash(f"touch {repo}/by-child.txt")).stdout
    if (repo / "by-child.txt").exists():
        assert WARN in out and "by-child.txt" in out, out
    else:
        pytest.skip("子の guard が本体への書き込みを拒否した (警告の前提が作れない)")


def test_no_warning_without_cwd_even_if_main_changes(env, repo):
    out = run_task(
        env, repo, {"agent": "worker", "task": "do it"}, bash(f"touch {repo}/by-child.txt")
    ).stdout
    assert WARN not in out, out


def test_cwd_child_gets_write_root_and_cwdless_child_does_not(env, repo, linked):
    out = run_task(env, repo, worker(str(linked)), bash("echo WR=[$PI_HARNESS_WRITE_ROOT]")).stdout
    assert f"WR=[{linked}]" in out, out
    out = run_task(
        env, repo, {"agent": "worker", "task": "do it"}, bash("echo WR=[$PI_HARNESS_WRITE_ROOT]")
    ).stdout
    assert "WR=[]" in out, out


def test_cwd_child_cannot_write_outside_its_worktree_even_with_bypass(env, repo, linked):
    def write(path: Path) -> list:
        return [{"name": "guarded_write", "args": {"path": str(path), "content": "x\n"}}]

    inside = linked / "by-child-in.txt"
    run_task(env, repo, worker(str(linked)), write(inside))
    assert inside.exists()
    outside = repo / "by-child-out.txt"
    out = run_task(env, repo, worker(str(linked)), write(outside)).stdout
    assert not outside.exists(), out
    assert "担当の worktree" in out, out
