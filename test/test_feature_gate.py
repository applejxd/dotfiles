"""scripts/feature_gate.py: feature の worktree の取り込み前の確認 (読み取り専用)。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "feature_gate.py"
ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
HARNESS = "home/dot_config/pi/harness"
COPY_LISTS = (
    "test/agents/test_pi_harness.py",
    "test/agents/test_pi_commit_confirm.py",
    "scripts/pi-harness-spike/compact-real.py",
)


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "develop")
    _write(root / ".gitignore", ".tmp/\n")
    _write(root / "base.txt", "b\n")
    _write(root / "big.txt", "".join(f"line {i}\n" for i in range(30)))
    _write(root / HARNESS / "index.ts", 'import { a } from "./a.ts";\n')
    _write(root / HARNESS / "a.ts", "export const a = 1;\n")
    for rel in COPY_LISTS:
        _write(root / rel, 'FILES = ["redact.ts", "a.ts"]\n')
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


@pytest.fixture
def wt(repo):
    path = repo / ".tmp" / "worktrees" / "feat"
    _git(repo, "worktree", "add", "-q", "-b", "feature/feat", str(path), "develop")
    return path


def _run(root: Path, *args: str, as_json: bool = True):
    cmd = [sys.executable, str(SCRIPT), "check", "feat", *args]
    if as_json:
        cmd.append("--json")
    r = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    return r, (json.loads(r.stdout) if as_json and r.returncode in (0, 1) else None)


def _check(data: dict, cid: str) -> dict:
    return next(c for c in data["checks"] if c["id"] == cid)


def test_clean_is_ok(repo, wt):
    r, data = _run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert data["ok"] is True


def test_json_schema(repo, wt):
    _r, data = _run(repo, "--owned", "docs/**")
    assert set(data) == {"v", "feature", "base", "tree", "ok", "checks"}
    assert data["v"] == 1
    assert data["feature"] == "feat"
    assert data["base"] == _git(repo, "rev-parse", "develop").strip()
    assert len(data["tree"]) == 40
    assert [c["id"] for c in data["checks"]] == [
        "scope",
        "numstat_drop",
        "register_tests",
        "register_harness_copy",
    ]
    for c in data["checks"]:
        assert set(c) == {"id", "ok", "detail"}
        assert isinstance(c["ok"], bool) and isinstance(c["detail"], str)


def test_human_output(repo, wt):
    r, _ = _run(repo, as_json=False)
    assert r.returncode == 0
    assert "scope" in r.stdout and "numstat_drop" in r.stdout


def test_scope_skipped_without_owned(repo, wt):
    _, data = _run(repo)
    assert _check(data, "scope") == {"id": "scope", "ok": True, "detail": "skipped (no --owned)"}


def test_scope_outside_fails(repo, wt):
    _write(wt / "base.txt", "changed\n")
    r, data = _run(repo, "--owned", "docs/**")
    assert r.returncode == 1
    assert _check(data, "scope")["ok"] is False
    assert "base.txt" in _check(data, "scope")["detail"]


def test_scope_inside_ok(repo, wt):
    _write(wt / "docs" / "x.md", "x\n")
    r, data = _run(repo, "--owned", "docs/**")
    assert r.returncode == 0, r.stdout
    assert _check(data, "scope")["ok"] is True


def test_numstat_drop_empty_file(repo, wt):
    _write(wt / "big.txt", "")
    r, data = _run(repo)
    assert r.returncode == 1
    c = _check(data, "numstat_drop")
    assert c["ok"] is False and "big.txt" in c["detail"] and "30 -> 0" in c["detail"]


def test_numstat_drop_small_edit_ok(repo, wt):
    _write(wt / "big.txt", "".join(f"line {i}\n" for i in range(25)))
    _, data = _run(repo)
    assert _check(data, "numstat_drop")["ok"] is True


def test_register_tests_unselected_fails(repo, wt):
    _write(wt / "test" / "test_zz_never_registered_xyz.py", "def test_a():\n    pass\n")
    r, data = _run(repo)
    assert r.returncode == 1
    c = _check(data, "register_tests")
    assert c["ok"] is False and "test_zz_never_registered_xyz.py" in c["detail"]


def test_register_tests_selected_ok(repo, wt):
    _write(wt / "test" / "test_pi_audit.py", "def test_a():\n    pass\n")
    # 規則に当たる stem (_PI_TESTS)。HEAD に無いので新規扱い
    _, data = _run(repo)
    assert _check(data, "register_tests")["ok"] is True


def test_harness_new_imported_ts_missing_from_copy_lists(repo, wt):
    _write(
        wt / HARNESS / "index.ts",
        'import { a } from "./a.ts";\nimport { n } from "./newpart.ts";\n',
    )
    _write(wt / HARNESS / "newpart.ts", "export const n = 1;\n")
    r, data = _run(repo)
    assert r.returncode == 1
    c = _check(data, "register_harness_copy")
    assert c["ok"] is False and "newpart.ts" in c["detail"]
    assert all(rel in c["detail"] for rel in COPY_LISTS)


def test_harness_transitive_import_detected(repo, wt):
    _write(wt / HARNESS / "a.ts", 'import { n } from "./deep.ts";\n')
    _write(wt / HARNESS / "deep.ts", "export const n = 1;\n")
    _, data = _run(repo)
    assert "deep.ts" in _check(data, "register_harness_copy")["detail"]


def test_harness_standalone_ts_ok(repo, wt):
    _write(wt / HARNESS / "standalone.ts", "export const s = 1;\n")
    _, data = _run(repo)
    assert _check(data, "register_harness_copy")["ok"] is True


def test_harness_listed_in_all_copy_lists_ok(repo, wt):
    _write(
        wt / HARNESS / "index.ts",
        'import { a } from "./a.ts";\nimport { n } from "./newpart.ts";\n',
    )
    _write(wt / HARNESS / "newpart.ts", "export const n = 1;\n")
    for rel in COPY_LISTS:
        _write(wt / rel, 'FILES = ["redact.ts", "a.ts", "newpart.ts"]\n')
    _, data = _run(repo)
    assert _check(data, "register_harness_copy")["ok"] is True


def test_harness_copy_lists_not_found_skipped(repo, wt):
    (wt / COPY_LISTS[0]).unlink()
    _, data = _run(repo)
    assert _check(data, "register_harness_copy")["detail"] == "skipped (copy lists not found)"


def _snapshot(path: Path) -> tuple:
    index = Path(_git(path, "rev-parse", "--path-format=absolute", "--git-path", "index").strip())
    return (
        index.read_bytes(),
        _git(path, "rev-parse", "HEAD"),
        _git(path, "diff", "--cached"),
        _git(path, "status", "--porcelain", "--untracked-files=all"),
        _git(path, "diff"),
    )


def test_read_only(repo, wt):
    _write(wt / "staged.txt", "s\n")
    _git(wt, "add", "staged.txt")
    _write(wt / "base.txt", "changed\n")
    _write(wt / "untracked.txt", "u\n")
    _write(wt / "big.txt", "")
    before = (_snapshot(wt), _snapshot(repo))
    r, _ = _run(repo, "--owned", "docs/**")
    assert r.returncode == 1
    assert (_snapshot(wt), _snapshot(repo)) == before


def test_unknown_feature_exit_2(repo):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "check", "nope"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **ENV},
        check=False,
    )
    assert r.returncode == 2
    assert "nope" in r.stderr
