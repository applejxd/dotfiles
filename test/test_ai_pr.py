"""scripts/ai_pr.py（専用 GitHub App の ai/* PR 入口）の単体試験。ネットワークは呼ばない。"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ai_pr.py"

_spec = importlib.util.spec_from_file_location("ai_pr", SCRIPT)
assert _spec is not None and _spec.loader is not None
ai_pr = importlib.util.module_from_spec(_spec)
sys.modules["ai_pr"] = ai_pr
_spec.loader.exec_module(ai_pr)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


@pytest.mark.parametrize("name", ["ai/vim-ssh", "ai/fix_1.2", "ai/a"])
def test_validate_ai_branch_accepts_valid_names(name: str):
    assert ai_pr.validate_ai_branch(name) == name


@pytest.mark.parametrize(
    "bad",
    [
        "develop",
        "main",
        "feature/x",
        "ai/",
        "ai/Upper",
        "ai/a:main",
        "ai/a b",
        "ai/a..b",
        "ai/-bad",
        "ai/trail.",
        "ai/" + "x" * 65,
    ],
)
def test_validate_ai_branch_rejects_dangerous_names(bad: str):
    with pytest.raises(ai_pr.AiPrError):
        ai_pr.validate_ai_branch(bad)


def test_build_app_jwt_formats_rs256_segments(tmp_path, monkeypatch):
    pem = tmp_path / "dummy.pem"
    pem.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(ai_pr, "_sign_rs256", lambda data, path: b"sig-bytes")
    token = ai_pr.build_app_jwt(5955830, pem, now=1_700_000_000)
    parts = token.split(".")
    assert len(parts) == 3
    header = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload == {"iat": 1_699_999_940, "exp": 1_700_000_540, "iss": "5955830"}


def test_submit_dry_run_rejects_workflow_changes_and_detects_protected_paths(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "chore: init")

    _git(repo, "checkout", "-q", "-b", "ai/test-normal")
    (repo / "home").mkdir()
    (repo / "home" / "dot_vimrc").write_text("set number\n", encoding="utf-8")
    _git(repo, "add", "home/dot_vimrc")
    _git(repo, "commit", "-q", "-m", "fix(vim): test")

    monkeypatch.setattr(ai_pr, "_run_gitleaks_check", lambda root, base: None)
    rc = ai_pr.main(["submit", "--cwd", str(repo), "--title", "fix(vim): test", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["protected"] is False
    assert out["branch"] == "ai/test-normal"

    # 保護パス（権限ポリシー）は protected=True になる
    (repo / "home" / ".chezmoitemplates").mkdir()
    (repo / "home" / ".chezmoitemplates" / "pi-permission-policy.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "home/.chezmoitemplates/pi-permission-policy.json")
    _git(repo, "commit", "-q", "-m", "chore: policy")
    rc = ai_pr.main(["submit", "--cwd", str(repo), "--title", "chore: policy", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["protected"] is True

    # .github/workflows/ を含む場合は入口で即拒否する
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    _git(repo, "add", ".github/workflows/ci.yml")
    _git(repo, "commit", "-q", "-m", "ci: touch workflow")
    rc = ai_pr.main(["submit", "--cwd", str(repo), "--title", "ci: touch workflow", "--dry-run"])
    assert rc == 1
    assert ".github/workflows/" in capsys.readouterr().err


def test_submit_rejects_non_ai_branch_and_dirty_tree(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "chore: init")

    assert ai_pr.main(["submit", "--cwd", str(repo), "--title", "fix: on develop", "--dry-run"]) == 1
    assert "ai/" in capsys.readouterr().err

    _git(repo, "checkout", "-q", "-b", "ai/dirty")
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
    assert ai_pr.main(["submit", "--cwd", str(repo), "--title", "fix: dirty", "--dry-run"]) == 1
    assert "未コミット" in capsys.readouterr().err


def test_cleanup_removes_merged_worktree_and_keeps_active_remote_branch(tmp_path, monkeypatch, capsys):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-q", str(origin))

    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    _git(repo, "checkout", "-q", "-b", "develop")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "chore: init")
    _git(repo, "push", "-q", "-u", "origin", "develop")

    # 完了済み（一度 push されて upstream があり、マージ後にリモートから消えて [gone] になった枝）
    wt_done = repo / ".tmp" / "worktrees" / "done"
    wt_done.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", "-q", "-b", "ai/done", str(wt_done), "develop")
    (wt_done / "done.txt").write_text("ok\n", encoding="utf-8")
    _git(wt_done, "add", "done.txt")
    _git(wt_done, "commit", "-q", "-m", "feat: done")
    _git(wt_done, "push", "-q", "-u", "origin", "ai/done")
    _git(repo, "merge", "--ff-only", "ai/done")
    _git(repo, "push", "-q", "origin", "develop")
    _git(repo, "push", "-q", "origin", ":ai/done")

    # 新規作成直後（未 push の枝）。cleanup 無引数で巻き込んで消してはいけない（P1-1 回帰）
    wt_fresh = repo / ".tmp" / "worktrees" / "fresh"
    _git(repo, "worktree", "add", "-q", "-b", "ai/fresh", str(wt_fresh), "develop")

    # 未 push のローカル作業中（コミット済み・未 push）。これも worktree ごと保護する
    wt_unpushed = repo / ".tmp" / "worktrees" / "unpushed"
    _git(repo, "worktree", "add", "-q", "-b", "ai/unpushed", str(wt_unpushed), "develop")
    (wt_unpushed / "wip2.txt").write_text("wip\n", encoding="utf-8")
    _git(wt_unpushed, "add", "wip2.txt")
    _git(wt_unpushed, "commit", "-q", "-m", "feat: unpushed")

    # 進行中（リモートに ai/active が残っている枝）
    wt_active = repo / ".tmp" / "worktrees" / "active"
    _git(repo, "worktree", "add", "-q", "-b", "ai/active", str(wt_active), "develop")
    (wt_active / "wip.txt").write_text("wip\n", encoding="utf-8")
    _git(wt_active, "add", "wip.txt")
    _git(wt_active, "commit", "-q", "-m", "feat: wip")
    _git(wt_active, "push", "-q", "-u", "origin", "ai/active")

    monkeypatch.chdir(repo)
    # --allow-squashed 単体は拒否する
    assert ai_pr.main(["cleanup", "--allow-squashed"]) == 1
    assert "--branch" in capsys.readouterr().err

    rc = ai_pr.main(["cleanup"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted_branches"] == ["ai/done"]
    assert not wt_done.exists()
    assert wt_fresh.exists()
    assert wt_unpushed.exists()
    assert wt_active.exists()
    assert any("ai/active" in s for s in out["skipped"])
    assert any("ai/fresh" in s for s in out["skipped"])
    assert any("ai/unpushed" in s for s in out["skipped"])

    # 未 push の枝に --branch + --allow-squashed を付けても [gone] でないため削除しない
    rc = ai_pr.main(["cleanup", "--branch", "ai/unpushed", "--allow-squashed"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted_branches"] == []
    assert wt_unpushed.exists()

    # Squash 統合済み（push 済み→リモート削除で [gone] かつ develop の祖先でない枝）は --branch + --allow-squashed で片付く
    wt_sq = repo / ".tmp" / "worktrees" / "squashed"
    _git(repo, "worktree", "add", "-q", "-b", "ai/squashed", str(wt_sq), "develop")
    (wt_sq / "sq.txt").write_text("sq\n", encoding="utf-8")
    _git(wt_sq, "add", "sq.txt")
    _git(wt_sq, "commit", "-q", "-m", "feat: sq")
    _git(wt_sq, "push", "-q", "-u", "origin", "ai/squashed")
    _git(repo, "push", "-q", "origin", ":ai/squashed")
    rc = ai_pr.main(["cleanup", "--branch", "ai/squashed", "--allow-squashed"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted_branches"] == ["ai/squashed"]
    assert not wt_sq.exists()
