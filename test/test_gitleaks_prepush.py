"""scripts/gitleaks_prepush.py の試験（範囲の組み立てと、履歴に残った秘密の検出）。"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gitleaks_prepush.py"
_spec = importlib.util.spec_from_file_location("gitleaks_prepush", SCRIPT)
assert _spec is not None and _spec.loader is not None
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)

ZERO = "0" * 40


def _gitleaks_available() -> bool:
    cmd = gp.gitleaks_command()
    if cmd is None:
        return False
    r = subprocess.run([*cmd, "version"], capture_output=True, check=False)
    return r.returncode == 0


needs_gitleaks = pytest.mark.skipif(not _gitleaks_available(), reason="gitleaks が使えない")


# ---- 範囲の組み立て（単体） ----


def test_range_normal_update():
    assert gp.build_log_opts("a" * 40, "b" * 40) == f"{'a' * 40}..{'b' * 40}"


@pytest.mark.parametrize("from_ref", [None, "", ZERO])
def test_range_new_branch_uses_not_remotes(from_ref):
    assert gp.build_log_opts(from_ref, "b" * 40) == f"{'b' * 40} --not --remotes"


def test_range_from_missing_locally_falls_back():
    assert gp.build_log_opts("a" * 40, "b" * 40, from_exists=False) == f"{'b' * 40} --not --remotes"


def test_range_without_to_ref_uses_head():
    assert gp.build_log_opts(ZERO, None) == "HEAD --not --remotes"


def test_range_branch_delete_is_skipped():
    assert gp.build_log_opts("a" * 40, ZERO) is None


# ---- 使い捨てリポジトリでの検出 ----


def _fake_token() -> str:
    # 検出用の架空のトークン。ファイルには書かず、実行時に連結して作る
    return "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"[:36]


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    r = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return r.stdout.strip()


def _commit(repo: Path, name: str, text: str, msg: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, from_ref: str, to_ref: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PRE_COMMIT_FROM_REF": from_ref, "PRE_COMMIT_TO_REF": to_ref}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@needs_gitleaks
def test_secret_added_then_removed_is_rejected(repo: Path):
    base = _commit(repo, "a.txt", "clean\n", "base")
    _commit(repo, "cfg.txt", f"token = {_fake_token()}\n", "add secret")
    head = _commit(repo, "cfg.txt", "token = removed\n", "remove secret")
    # 最終 tree はきれいでも、途中コミットの秘密を拒否する
    assert "ghp_" not in (repo / "cfg.txt").read_text(encoding="utf-8")
    r = _run(repo, base, head)
    assert r.returncode != 0, r.stdout + r.stderr


@needs_gitleaks
def test_secret_in_merge_range_is_rejected(repo: Path):
    base = _commit(repo, "a.txt", "clean\n", "base")
    _git(repo, "switch", "-q", "-c", "side")
    _commit(repo, "cfg.txt", f"token = {_fake_token()}\n", "add secret")
    _commit(repo, "cfg.txt", "gone\n", "remove secret")
    _git(repo, "switch", "-q", "main")
    _commit(repo, "b.txt", "other\n", "main work")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    head = _git(repo, "rev-parse", "HEAD")
    assert _run(repo, base, head).returncode != 0


@needs_gitleaks
def test_new_branch_range_rejects_unpushed_secret(repo: Path):
    _commit(repo, "a.txt", "clean\n", "base")
    head = _commit(repo, "cfg.txt", f"token = {_fake_token()}\n", "add secret")
    assert _run(repo, ZERO, head).returncode != 0


@needs_gitleaks
def test_clean_history_passes(repo: Path):
    base = _commit(repo, "a.txt", "clean\n", "base")
    head = _commit(repo, "b.txt", "also clean\n", "more")
    r = _run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_gitleaks_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "a" * 40)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "b" * 40)
    monkeypatch.chdir(repo)
    assert gp.main() == 2
