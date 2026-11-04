"""台帳の置き場を、`.git` 以外の名前の git-common-dir でも保護する (`judge/ledger_root.ts` の `ledgerRoots`)。

保存側 (`work/root.ts`) は `git rev-parse --git-common-dir` の `<common>/pi-work` を使うので、`--separate-git-dir` や `GIT_DIR`
の構成では名前の正規表現 (`.git/pi-work`) に当たらない。判定器は fs だけで置き場を解いて照合する。
see docs/spec/work/store.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT, load_common
from test_pi_confirm import _bash
from test_pi_judge_ts import _node

sys.path.insert(0, str(ROOT / "scripts" / "agents"))
import generate as gen

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

ROLES = ["implementer", "worker", "explore"]


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra or {})
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )


def _judge(requests, env=None):
    common = gen.pi_judge_data(load_common())["common"]
    proc = subprocess.run(
        [_node(), str(ROOT / "test" / "agents" / "pi" / "judge_boundary.mjs")],
        input=json.dumps({"requests": requests, "common": common}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=_clean_env(env),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def _roots(cases, many=0):
    proc = subprocess.run(
        [_node(), str(ROOT / "test" / "agents" / "pi" / "ledger_root_driver.mjs")],
        input=json.dumps({"cases": cases, "many": many}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


@pytest.fixture
def sep_repo(tmp_path):
    """`git init --separate-git-dir` の構成。`.git` はファイルで、common-dir は `<tmp>/elsewhere/proj.git`。"""
    base = tmp_path.resolve()
    proj = base / "proj"
    sep = base / "elsewhere" / "proj.git"
    proj.mkdir()
    sep.parent.mkdir()
    _git(proj, "init", "-q", f"--separate-git-dir={sep}")
    (sep / "pi-work" / "log").mkdir(parents=True)
    assert (proj / ".git").is_file()
    return proj, sep


def _decisions(commands, cwd, role="implementer", env=None, **flags):
    return [
        r["decision"]
        for r in _judge([_bash(c, cwd=str(cwd), role=role, **flags) for c in commands], env)
    ]


def _file(tool, path, cwd, role="implementer"):
    return {
        "tool": tool,
        "input": {"path": str(path), "content": "x"},
        "cwd": str(cwd),
        "role": role,
    }


@pytest.mark.parametrize("bypass", [False, True])
@pytest.mark.parametrize("role", ROLES)
def test_separate_git_dir_ledger_is_denied_for_bash_writes(sep_repo, role, bypass):
    proj, sep = sep_repo
    commands = [
        f"echo x > {sep}/pi-work/log/x",
        f"rm -r {sep}/pi-work",
        f"cp x {sep}/pi-work/x",
    ]
    flags = {"bypass": True} if bypass else {}
    assert _decisions(commands, proj, role, **flags) == ["deny"] * 3


def test_separate_git_dir_ledger_reads_are_not_denied(sep_repo):
    proj, sep = sep_repo
    assert _decisions([f"grep x {sep}/pi-work/x"], proj) != ["deny"]


def test_separate_git_dir_relative_path_and_symlink_are_denied(sep_repo):
    proj, sep = sep_repo
    (proj / "link").symlink_to(sep / "pi-work")
    commands = ["echo x > ../elsewhere/proj.git/pi-work/x", "echo x > link/x", "rm -r link/log"]
    assert _decisions(commands, proj) == ["deny"] * 3


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("tool", ["write", "edit"])
def test_separate_git_dir_ledger_is_denied_for_file_tools(sep_repo, tool, role):
    proj, sep = sep_repo
    target = sep / "pi-work" / "log" / "x.jsonl"
    assert [r["decision"] for r in _judge([_file(tool, target, proj, role)])] == ["deny"]


def test_file_tools_still_allow_ordinary_files_in_the_repo(sep_repo):
    proj, _ = sep_repo
    reqs = [
        _file("write", proj / "a.txt", proj),
        _file("write", proj / ".tmp" / "worktrees" / "x" / "a", proj),
    ]
    assert [r["decision"] for r in _judge(reqs)] == ["allow", "allow"]


def test_worktree_of_a_separate_git_dir_repo_resolves_the_common_dir(sep_repo, tmp_path):
    proj, sep = sep_repo
    _git(proj, "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path.resolve() / "wt"
    _git(proj, "worktree", "add", "-q", str(wt), "-b", "feat")
    roots = _roots([{"cwd": str(wt)}])["results"][0]
    assert str(sep / "pi-work") in roots
    assert _decisions([f"echo x > {sep}/pi-work/log/x"], wt) == ["deny"]
    # worktree 自身の gitdir (`<sep>/worktrees/wt`) の下は台帳ではない
    assert all("worktrees" not in r for r in roots)


def test_worktree_of_a_normal_repo_resolves_the_main_git_dir(tmp_path):
    main = tmp_path.resolve() / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path.resolve() / "wt"
    _git(main, "worktree", "add", "-q", str(wt), "-b", "feat")
    roots = _roots([{"cwd": str(wt)}])["results"][0]
    assert str(main / ".git" / "pi-work") in roots
    assert _decisions([f"echo x > {main}/.git/pi-work/log/x"], wt) == ["deny"]


def test_git_dir_and_git_common_dir_env_are_honored(sep_repo, tmp_path):
    _, sep = sep_repo
    other = tmp_path.resolve() / "other"
    other.mkdir()
    for key in ("GIT_DIR", "GIT_COMMON_DIR"):
        assert (
            str(sep / "pi-work")
            in _roots([{"cwd": str(other), "env": {key: str(sep)}}])["results"][0]
        )
        assert _decisions([f"echo x > {sep}/pi-work/x"], other, env={key: str(sep)}) == ["deny"]
    # 環境変数が無ければ、無関係の cwd からは解けない (名前の照合だけ)
    assert str(sep / "pi-work") not in _roots([{"cwd": str(other)}])["results"][0]


def test_git_dir_env_of_a_worktree_gitdir_resolves_commondir(sep_repo, tmp_path):
    proj, sep = sep_repo
    _git(proj, "commit", "-q", "--allow-empty", "-m", "x")
    wt = tmp_path.resolve() / "wt"
    _git(proj, "worktree", "add", "-q", str(wt), "-b", "feat")
    gitdir = sep / "worktrees" / "wt"
    roots = _roots([{"cwd": str(tmp_path), "env": {"GIT_DIR": str(gitdir)}}])["results"][0]
    assert str(sep / "pi-work") in roots


def test_relative_gitdir_file_is_resolved_from_the_dot_git_directory(tmp_path):
    base = tmp_path.resolve()
    proj = base / "proj"
    real = base / "store" / "p.git"
    proj.mkdir()
    real.mkdir(parents=True)
    _git(real, "init", "-q", "--bare")
    (proj / ".git").write_text("gitdir: ../store/p.git\n", encoding="utf-8")
    sub = proj / "deep" / "er"
    sub.mkdir(parents=True)
    # 上の階層の `.git` を見つける
    assert str(real / "pi-work") in _roots([{"cwd": str(sub)}])["results"][0]
    assert _decisions([f"echo x > {real}/pi-work/x"], sub) == ["deny"]


@pytest.mark.parametrize(
    "dot_git",
    [
        "garbage\n",
        "gitdir: /nonexistent/nowhere.git\n",
        "gitdir:\n",
        "",
        "gitdir: ./self\n",
    ],
)
def test_broken_dot_git_file_does_not_raise_and_falls_back_to_name_matching(tmp_path, dot_git):
    proj = tmp_path.resolve() / "proj"
    proj.mkdir()
    (proj / ".git").write_text(dot_git, encoding="utf-8")
    roots = _roots([{"cwd": str(proj)}])["results"][0]
    assert str(proj / ".tmp" / "work") in roots
    # 名前の照合 (従来) は残る
    assert _decisions([f"echo x > {proj}/.git/pi-work/x", "echo x > .tmp/work/x"], proj) == [
        "deny",
        "deny",
    ]


def test_commondir_pointing_at_itself_does_not_loop(tmp_path):
    base = tmp_path.resolve()
    proj = base / "proj"
    gitdir = base / "loop.git"
    proj.mkdir()
    gitdir.mkdir()
    (proj / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "commondir").write_text(".\n", encoding="utf-8")
    assert str(gitdir / "pi-work") in _roots([{"cwd": str(proj)}])["results"][0]


def test_unreadable_commondir_does_not_raise(tmp_path):
    base = tmp_path.resolve()
    proj = base / "proj"
    gitdir = base / "weird.git"
    proj.mkdir()
    gitdir.mkdir()
    (proj / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    (gitdir / "commondir").mkdir()  # ファイルではなくディレクトリ (読めない)
    roots = _roots([{"cwd": str(proj)}])["results"][0]
    assert str(proj / ".tmp" / "work") in roots


def test_cwd_that_does_not_exist_does_not_raise():
    out = _roots([{"cwd": "/nonexistent/a/b"}])
    assert out["results"][0] == ["/nonexistent/a/b/.tmp/work"]


def test_roots_are_cached_per_cwd_and_bounded(sep_repo):
    proj, _ = sep_repo
    out = _roots([{"cwd": str(proj)}], many=200)
    assert out["same"] == [True]  # 同じ cwd は同じ配列 (fs を引き直さない)
    assert out["cacheSize"] <= 64


def test_normal_dot_git_directory_gives_the_same_result_as_before(tmp_path):
    proj = tmp_path.resolve() / "proj"
    proj.mkdir()
    _git(proj, "init", "-q")
    roots = _roots([{"cwd": str(proj)}])["results"][0]
    assert roots == [str(proj / ".git" / "pi-work"), str(proj / ".tmp" / "work")]
    assert _decisions(["echo x > .git/pi-work/x", f"echo x > {proj}/.git/pi-work/x"], proj) == [
        "deny",
        "deny",
    ]


def test_worktrees_directory_and_ordinary_dirs_are_not_ledger(tmp_path):
    proj = tmp_path.resolve() / "proj"
    proj.mkdir()
    _git(proj, "init", "-q")
    commands = [
        "echo x > .tmp/worktrees/x",
        "echo x > .tmp/workflow/x",
    ]
    assert "deny" not in _decisions(commands, proj)


def test_sibling_with_the_same_prefix_is_not_a_ledger(tmp_path):
    base = tmp_path.resolve()
    proj = base / "proj"
    store = base / "pstore"
    proj.mkdir()
    store.mkdir()
    _git(store, "init", "-q", "--bare")
    (proj / ".git").write_text(f"gitdir: {store}\n", encoding="utf-8")
    assert _decisions([f"echo x > {store}/pi-work/x"], proj) == ["deny"]
    assert "deny" not in _decisions([f"echo x > {store}/pi-workbench/x"], proj)
