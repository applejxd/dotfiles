"""``guarded_task`` の ``isolation: "worktree"`` (子の worktree 隔離) の統合試験。

偽のモデル (faux) の親が ``worker`` を隔離で起動し、子が worktree の中で動くこと・回収の結果・Landlock の拒否を、
使い捨ての git リポジトリで確かめる。Landlock・git・pi・python3 のどれかが無い環境では skip する。
偽のモデルを使う統合経路で、Landlock の適用・回収・親への書込拒否・拒否の理由・書込可の一覧とリポジトリの重なりの扱いを確かめる。
``children.ts`` の停止確認 (``stopped=false``・孫の残存・二重シグナル) は直接検査しない。
see docs/change/0029-worktree-isolation.md#w1-の実装計画
"""

# ruff: noqa: F811  (env はインポートしたフィクスチャ。引数名で使うので再定義に見える)
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_harness import FIXTURES, PI, env  # noqa: F401  (env はフィクスチャ。使い回す)

HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"
LANDLOCK = HARNESS / "landlock_exec.py"
CHILDREN = HARNESS / "children.ts"
JOB_ID = r"job-[0-9a-f]{12}"


def _skip_reason() -> str | None:
    if PI is None:
        return "pi is not installed"
    if shutil.which("git") is None or not Path("/usr/bin/git").exists():
        return "/usr/bin/git が無い"
    if shutil.which("python3") is None:
        return "python3 が無い"
    try:
        r = subprocess.run(["python3", str(LANDLOCK), "--check"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "landlock_exec.py --check を実行できない"
    return None if r.returncode == 0 else "Landlock を使えない"


_REASON = _skip_reason()
integration = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def repo(env):
    """使い捨ての git リポジトリ。/tmp と TMPDIR の外に置く (子の書込可に含まれると、拒否の試験にならない)。"""
    base = ROOT / ".tmp"
    base.mkdir(exist_ok=True)
    proj = Path(tempfile.mkdtemp(prefix="isolation-", dir=base)).resolve()
    try:
        git(proj, "init", "-q", "-b", "main")
        (proj / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
        (proj / "tracked.txt").write_text("a\nb\nc\n", encoding="utf-8")
        (proj / "sub").mkdir()
        (proj / "sub" / "keep.txt").write_text("k\n", encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "init")
        (proj / "tracked.txt").write_text("a\nB-parent\nc\n", encoding="utf-8")  # 未コミットの変更
        (proj / "untracked_new.txt").write_text("u\n", encoding="utf-8")  # 未追跡
        yield proj
    finally:
        shutil.rmtree(proj, ignore_errors=True)


def run_task(env, cwd: Path, task_args: dict, child_calls: list, **extra):
    """親 (偽のモデル) が guarded_task を 1 回呼ぶ。子の結果を全文 (FAUX_RESULT_CHARS) で stdout に出す。"""
    rounds = [[{"name": "guarded_task", "args": task_args}]]
    args = [PI, "--no-session", "--model", "faux/spike", "-nbt", "-ne", "-e", "builtin:mcp"]
    args += ["-e", str(env["harness"]), "-e", str(FIXTURES / "faux.ts"), "-p", "go"]
    return subprocess.run(
        args,
        cwd=cwd,
        env={
            **env["env"],
            "PI_HARNESS_BYPASS": "1",  # 子 (worker) は bypass を継ぐ。確認の無い UI でも子の操作が通る
            "FAUX_TOOL_ROUNDS": json.dumps(rounds),
            "FAUX_CHILD_TOOL_CALLS": json.dumps(child_calls),
            "FAUX_RESULT_CHARS": "20000",
            "PI_HARNESS_TEST_CHILD_EXT": str(FIXTURES / "faux.ts"),
            **extra,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
    )


def isolated(**more):
    return {"agent": "worker", "task": "do it", "isolation": "worktree", **more}


def bash(command: str) -> list:
    return [{"name": "guarded_bash", "args": {"command": command}}]


def parent_files(proj: Path) -> dict:
    """親の作業ツリーの内容 (.git と置き場を除く)。"""
    out = {}
    for p in proj.rglob("*"):
        rel = p.relative_to(proj)
        if p.is_file() and rel.parts[0] not in (".git", ".tmp"):
            out[str(rel)] = p.read_bytes()
    return out


def object_files(proj: Path) -> set:
    return {str(p.relative_to(proj)) for p in (proj / ".git" / "objects").rglob("*") if p.is_file()}


def leftover_worktrees(proj: Path) -> list:
    return (
        sorted((proj / ".tmp" / "worktrees").glob("pi-agent-*"))
        if (proj / ".tmp" / "worktrees").exists()
        else []
    )


# ─── 隔離の起動・回収 ───────────────────────────────────────────────


@integration
def test_isolated_child_runs_in_a_worktree_and_an_unchanged_one_is_removed(env, repo):
    proc = run_task(env, repo, isolated(), bash("pwd"))
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert re.search(re.escape(f"{repo}/.tmp/worktrees/pi-agent-") + JOB_ID, out), out
    assert "- isolation: worktree" in out, out
    assert "- worktree: no changes (removed)" in out, out
    assert leftover_worktrees(repo) == []
    assert len(git(repo, "worktree", "list").strip().splitlines()) == 1  # 登録も消えている


@integration
def test_isolated_child_changes_are_collected_as_a_patch_without_touching_the_parent(env, repo):
    before = parent_files(repo)
    child = [{"name": "guarded_write", "args": {"path": "newfile.txt", "content": "from child\n"}}]
    proc = run_task(env, repo, isolated(), child)
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert "- isolation: worktree" in out and "- worktree: ref refs/pi-agent/" in out, out
    m = re.search(rf"ref refs/pi-agent/({JOB_ID}); patch (\S+); apply: git apply (\S+)", out)
    assert m, out
    job_id, patch_rel, apply_rel = m.groups()
    assert (
        patch_rel == apply_rel
        and patch_rel.startswith(".tmp/subagents/")
        and patch_rel.endswith(".patch")
    )
    patch = repo / patch_rel
    assert patch.is_file()
    text = patch.read_text(encoding="utf-8")
    assert "newfile.txt" in text and "from child" in text and "tracked.txt" not in text
    check = subprocess.run(
        ["git", "apply", "--check", patch_rel],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert check.returncode == 0, check.stderr
    # 親の作業ツリーは変わらず、結果は専用の ref にだけ残る
    assert parent_files(repo) == before
    assert not (repo / "newfile.txt").exists()
    git(repo, "rev-parse", "--verify", f"refs/pi-agent/{job_id}")


@integration
def test_isolated_child_cannot_write_into_the_parent_working_tree(env, repo):
    probe = env["tmp"] / "probe.py"
    probe.write_text(
        "import sys\n"
        "try:\n"
        "    open(sys.argv[1], 'w').close()\n"
        "    print('WROTE')\n"
        "except OSError as e:\n"
        "    print('DENIED', e.errno)\n",
        encoding="utf-8",
    )
    proc = run_task(env, repo, isolated(), bash(f"python3 {probe} {repo}/zz.txt"))
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert "DENIED 13" in out and "WROTE" not in out, out
    assert not (repo / "zz.txt").exists()


@integration
def test_isolated_child_keeps_the_relative_position_of_the_parent_cwd(env, repo):
    proc = run_task(env, repo / "sub", isolated(), bash("pwd"))
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert re.search(re.escape(f"{repo}/.tmp/worktrees/pi-agent-") + JOB_ID + r"/sub\b", out), out


# ─── 拒否 ───────────────────────────────────────────────────────────


@integration
def test_isolation_outside_a_git_repository_is_refused_and_no_child_starts(env):
    plain = Path(
        tempfile.mkdtemp(prefix="iso-nongit-", dir="/tmp")
    )  # TMPDIR はリポジトリの中のことがある
    try:
        proc = run_task(env, plain, isolated(), bash("pwd"))
    finally:
        shutil.rmtree(plain, ignore_errors=True)
    assert "isolation refused: not_a_git_repository" in proc.stdout, proc.stdout
    assert "child worker" not in proc.stdout, proc.stdout


@integration
def test_isolation_refuses_a_protected_untracked_file_before_writing_any_object(env, repo):
    (repo / ".env").write_text("SECRET=topsecretvalue\n", encoding="utf-8")
    objects = object_files(repo)
    proc = run_task(env, repo, isolated(), bash("pwd"))
    out = proc.stdout
    assert "isolation refused: protected_path" in out, out
    assert "child worker" not in out and "topsecretvalue" not in out, out
    assert object_files(repo) == objects
    assert leftover_worktrees(repo) == []


# ─── 隔離でない結果の表示 ───────────────────────────────────────────


@integration
def test_a_plain_worker_result_says_isolation_none_and_explore_does_not(env, repo):
    out = run_task(env, repo, {"agent": "worker", "task": "do it"}, bash("pwd")).stdout
    assert "- isolation: none" in out and "- isolation: worktree" not in out, out
    out = run_task(env, repo, {"agent": "explore", "task": "look"}, []).stdout
    assert "- isolation:" not in out, out


# ─── 書込可の一覧とリポジトリの重なり ───────────────────────────────


@integration
@pytest.mark.parametrize("where", ["tmp_in_repo", "repo_itself", "ancestor"])
def test_tmpdir_overlapping_the_repository_is_dropped_and_overridden_with_tmp(env, repo, where):
    (repo / ".tmp").mkdir(exist_ok=True)
    tmpdir = {"tmp_in_repo": repo / ".tmp", "repo_itself": repo, "ancestor": repo.parent}[where]
    target = repo / ".tmp" / "subagents"
    command = (
        f"(mkdir -p {target} && echo x > {target}/x) 2>/dev/null; "
        'echo "RC=$?"; echo "CHILD_TMPDIR=[$TMPDIR]"'
    )
    proc = run_task(env, repo, isolated(), bash(command), TMPDIR=str(tmpdir))
    out = proc.stdout
    assert proc.returncode == 0, proc.stderr
    assert re.search(r"RC=[1-9]", out) and "RC=0" not in out, out
    assert "CHILD_TMPDIR=[/tmp]" in out, out
    assert not (target / "x").exists()


@integration
@pytest.mark.parametrize("where", ["repo_root", "inside_repo"])
def test_agent_dir_overlapping_the_repository_is_refused_before_creating_a_worktree(
    env, repo, where
):
    agent = repo if where == "repo_root" else repo / "agent-in-repo"
    agent.mkdir(exist_ok=True)
    objects = object_files(repo)
    proc = run_task(env, repo, isolated(), bash("pwd"), PI_CODING_AGENT_DIR=str(agent))
    out = proc.stdout
    assert "isolation refused: agent_dir_overlaps_repository" in out, out
    assert "child worker" not in out, out
    assert leftover_worktrees(repo) == []
    assert object_files(repo) == objects


@integration
def test_repository_under_tmp_is_refused(env):
    proj = Path(tempfile.mkdtemp(prefix="iso-intmp-", dir="/tmp")).resolve()
    try:
        git(proj, "init", "-q", "-b", "main")
        (proj / "a.txt").write_text("a\n", encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "init")
        objects = object_files(proj)
        proc = run_task(env, proj, isolated(), bash("pwd"))
        out = proc.stdout
        assert "isolation refused: tmp_overlaps_repository" in out, out
        assert "child worker" not in out, out
        assert not (proj / ".tmp" / "worktrees").exists()
        assert object_files(proj) == objects
    finally:
        shutil.rmtree(proj, ignore_errors=True)
