"""自由区の判定 (harness/freezone.ts, gitrun.ts) の表試験。使い捨ての実 git リポジトリで確かめる。

迷ったら free:false に倒す判定なので、free になる表は狭く、それ以外は広く確かめる。
see docs/change/0053-worktree-integration-gate.md
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "freezone_driver.mjs"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="シェルスクリプトの偽 git を使う")
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *IDENT, "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def _init(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def _run(payload: dict) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _classify(cwd: Path | str, **extra) -> dict:
    return _run({"cwd": str(cwd), **extra})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init(tmp_path / "main")


def _linked(repo: Path, branch: str, name: str) -> Path:
    wt = repo.parent / name
    _git(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    return wt


@pytest.mark.parametrize("branch", ["feature/x", "feature/a/b"])
def test_linked_feature_is_free(repo: Path, branch: str):
    wt = _linked(repo, branch, "wt")
    r = _classify(wt)
    assert r["free"] is True, r
    assert r["linked"] is True
    assert r["branch"] == f"refs/heads/{branch}"


def test_subdirectory_cwd_is_free(repo: Path):
    wt = _linked(repo, "feature/x", "wt")
    (wt / "a" / "b").mkdir(parents=True)
    assert _classify(wt / "a" / "b")["free"] is True


def test_symlinked_cwd_is_free(repo: Path, tmp_path: Path):
    wt = _linked(repo, "feature/x", "wt")
    link = tmp_path / "link"
    try:
        link.symlink_to(wt, target_is_directory=True)
    except OSError:
        pytest.skip("symlink を作れない")
    assert _classify(link)["free"] is True


def test_uppercase_feature_is_free_like_isFeatureSourceRef(repo: Path):
    try:
        wt = _linked(repo, "Feature/X", "wt")
    except subprocess.CalledProcessError:
        pytest.skip("大文字のブランチを作れない環境")
    assert _classify(wt)["free"] is True


def test_main_worktree_is_not_free(repo: Path):
    r = _classify(repo)
    assert r["free"] is False
    assert r["linked"] is False


def test_feature_branch_on_main_worktree_is_not_free(repo: Path):
    _git(repo, "switch", "-q", "-c", "feature/x")
    assert _classify(repo)["free"] is False


@pytest.mark.parametrize("branch", ["develop", "release/1.0", "hotfix/1", "main-2/x"])
def test_linked_non_feature_is_not_free(repo: Path, branch: str):
    wt = _linked(repo, branch, "wt")
    assert _classify(wt)["free"] is False


def test_protected_list_is_a_parameter(repo: Path):
    wt = _linked(repo, "feature/x", "wt")
    assert _classify(wt, protected=["feature/*"])["free"] is False
    assert _classify(wt, protected=["develop"])["free"] is True


def test_linked_detached_is_not_free(repo: Path):
    wt = _linked(repo, "feature/x", "wt")
    _git(wt, "switch", "-q", "--detach")
    r = _classify(wt)
    assert r["free"] is False
    assert "detached" in r["reason"]


def test_empty_feature_name_is_not_free(repo: Path):
    # `feature/` はブランチ名にできないので、HEAD を直接書き換えて作る
    wt = _linked(repo, "feature/x", "wt")
    gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir").strip())
    (gitdir / "HEAD").write_text("ref: refs/heads/feature/\n")
    assert _classify(wt)["free"] is False


def test_submodule_is_not_free(tmp_path: Path):
    lib = _init(tmp_path / "lib", "feature/lib")
    parent = _init(tmp_path / "parent")
    _git(parent, "submodule", "add", "-q", str(lib), "sub")
    sub = parent / "sub"
    assert _git(sub, "rev-parse", "--show-superproject-working-tree").strip()
    r = _classify(sub)
    assert r["free"] is False
    assert "submodule" in r["reason"]


def test_nested_normal_repo_inside_worktree_is_not_free(repo: Path):
    wt = _linked(repo, "feature/x", "wt")
    child = _init(wt / "child", "feature/y")
    assert _classify(child)["free"] is False


def test_not_a_repository_is_not_free(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _classify(plain)["free"] is False


def test_missing_cwd_is_not_free(tmp_path: Path):
    assert _classify(tmp_path / "nope")["free"] is False


def test_broken_dotgit_file_is_not_free(tmp_path: Path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / ".git").write_text("")
    assert _classify(d)["free"] is False


def test_git_missing_from_path_is_not_free(repo: Path):
    wt = _linked(repo, "feature/x", "wt")
    r = _classify(wt, env={"PATH": ""})
    assert r["free"] is False


def test_git_dir_in_environment_does_not_retarget(repo: Path, tmp_path: Path):
    wt = _linked(repo, "feature/x", "wt")
    other = _init(tmp_path / "other")
    env = {**os.environ, "GIT_DIR": str(other / ".git")}
    r = _classify(wt, env=env)
    assert r["free"] is True, r
    assert _classify(repo, env=env)["free"] is False


def test_gitsync_never_raises():
    r = _run({"fn": "git", "args": ["--version"], "cwd": str(ROOT)})
    assert r["ok"] is True and r["stdout"].startswith("git version")
    r = _run({"fn": "git", "args": ["--version"], "cwd": str(ROOT / "no-such-dir")})
    assert r["ok"] is False and r["reason"]
    r = _run({"fn": "git", "args": ["no-such-subcommand"], "cwd": str(ROOT)})
    assert r["ok"] is False and r["code"] != 0
    r = _run({"fn": "git", "args": ["--version"], "cwd": str(ROOT), "env": {"PATH": ""}})
    assert r["ok"] is False and r["reason"]


def _fake_git(tmp_path: Path, body: str) -> dict:
    real = subprocess.run(
        ["which", "git"], capture_output=True, text=True, check=True
    ).stdout.strip()
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(f'#!/bin/sh\n{body}\nexec "{real}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "COUNT": str(tmp_path / "count"),
    }


@POSIX_ONLY
def test_git_is_started_at_most_twice(repo: Path, tmp_path: Path):
    env = _fake_git(tmp_path, 'echo x >> "$COUNT"')
    count = Path(env["COUNT"])
    wt = _linked(repo, "feature/x", "wt")

    assert _classify(wt, env=env)["free"] is True
    assert len(count.read_text().splitlines()) == 2

    count.unlink()
    assert _classify(repo, env=env)["free"] is False
    assert len(count.read_text().splitlines()) <= 2


@POSIX_ONLY
def test_timeout_is_not_free(repo: Path, tmp_path: Path):
    env = _fake_git(tmp_path, "sleep 2")
    wt = _linked(repo, "feature/x", "wt")
    r = _classify(wt, env=env, timeoutMs=200)
    assert r["free"] is False
    assert "時間内" in r["reason"]
    g = _run({"fn": "git", "args": ["--version"], "cwd": str(wt), "env": env, "timeoutMs": 200})
    assert g["ok"] is False and "時間内" in g["reason"]
