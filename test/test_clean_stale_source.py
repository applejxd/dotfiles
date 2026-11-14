"""scripts/clean_stale_source.py (.chezmoiremove 対象の source 残骸の掃除) の試験。"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clean_stale_source.py"

_spec = importlib.util.spec_from_file_location("clean_stale_source", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
clean_stale_source = importlib.util.module_from_spec(_spec)
sys.modules["clean_stale_source"] = clean_stale_source
_spec.loader.exec_module(clean_stale_source)


def _git(repo: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """git リポジトリ。`.gitignore` で __pycache__ を除き、`.chezmoiremove` を置く。"""
    root = tmp_path / "src"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root / ".gitignore", "__pycache__/\n")
    _write(
        root / "home" / ".chezmoiremove",
        "# コメント\n"
        ".config/pi\n"
        ".ssh/x\n"
        "!.config/keep\n"
        ".config/glob*\n",
    )
    _write(root / "home" / "dot_config" / "keep" / "a.txt")
    _git(root, "add", "-A")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_untracked_leftover_is_removed(repo: Path) -> None:
    _write(repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert not (repo / "home" / "dot_config" / "pi").exists()
    assert (repo / "home" / "dot_config" / "keep" / "a.txt").exists()


def test_tracked_files_are_kept_with_warning(repo: Path) -> None:
    _write(repo / "home" / "dot_config" / "pi" / "a.txt")
    _write(repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc")
    _git(repo, "add", "-A")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi" / "a.txt").exists()
    assert (repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc").exists()
    assert "警告" in proc.stderr


def test_dry_run_removes_nothing(repo: Path) -> None:
    _write(repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc")
    proc = _run(repo, "--dry-run")
    assert proc.returncode == 0
    assert "削除予定" in proc.stdout
    assert (repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc").exists()


def test_directories_not_in_chezmoiremove_are_untouched(repo: Path) -> None:
    _write(repo / "home" / "dot_config" / "other" / "__pycache__" / "m.pyc")
    _write(repo / "home" / "dot_config" / "globx" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "other").exists()
    # 解釈できない行 (テンプレート・glob) の対象は触らない
    assert (repo / "home" / "dot_config" / "globx").exists()


def test_attribute_prefixes_are_ignored(repo: Path) -> None:
    _write(repo / "home" / "private_dot_ssh" / "exact_x" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert not (repo / "home" / "private_dot_ssh" / "exact_x").exists()


def test_outside_git_removes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    _write(root / "home" / ".chezmoiremove", ".config/pi\n")
    _write(root / "home" / "dot_config" / "pi" / "m.pyc")
    proc = _run(root)
    assert proc.returncode == 0
    assert (root / "home" / "dot_config" / "pi" / "m.pyc").exists()
    assert "警告" in proc.stderr


def test_symlinked_directory_is_not_followed(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _write(outside / "keep.txt")
    (repo / "home" / "dot_config").mkdir(parents=True, exist_ok=True)
    try:
        (repo / "home" / "dot_config" / "pi").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink を作れない環境")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (outside / "keep.txt").exists()


def test_untracked_non_ignored_file_is_kept(repo: Path) -> None:
    """未追跡でも ignored でない手書きのファイルは、キャッシュと混在していても消さない。"""
    _write(repo / "home" / "dot_config" / "pi" / "notes.txt")
    _write(repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi" / "notes.txt").exists()
    assert "警告" in proc.stderr


def test_inherited_git_index_file_does_not_bypass_tracking(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(repo / "home" / "dot_config" / "pi" / "a.txt")
    _git(repo, "add", "-A")
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "no-such-index"))
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi" / "a.txt").exists()


def test_literal_prefix_is_not_interpreted(repo: Path) -> None:
    _write(repo / "home" / "literal_dot_config" / "pi" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "literal_dot_config" / "pi").exists()


def test_submodule_contents_are_kept(repo: Path, tmp_path: Path) -> None:
    """外側の ls-files が空でも、サブモジュールの内側の追跡ファイルは消さない。"""
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q")
    _write(inner / "guard" / "notes.txt")
    _git(inner, "add", "-A")
    _git(inner, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i")
    _write(repo / "home" / ".chezmoiremove", ".config/pi/guard\n")
    _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "home/dot_config/pi")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi" / "guard" / "notes.txt").exists()
    assert "警告" in proc.stderr


def test_nested_repo_below_candidate_is_kept(repo: Path) -> None:
    """候補の子孫にある ignored な別リポジトリ (内側の commit 済みファイル付き) は消さない。"""
    inner = repo / "home" / "dot_config" / "pi" / "__pycache__"
    inner.mkdir(parents=True)
    _git(inner, "init", "-q")
    _write(inner / "notes.txt")
    _git(inner, "add", "-A")
    _git(inner, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (inner / "notes.txt").exists()
    assert "警告" in proc.stderr


def test_directory_suffixes_are_not_stripped(repo: Path) -> None:
    """ディレクトリの .tmpl / .literal は target 名から除かれない (chezmoi managed で確認済み)。"""
    _write(repo / "home" / "dot_config" / "pi.tmpl" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi.tmpl").exists()


@pytest.mark.parametrize("name", ["run_pi", "executable_pi", "symlink_pi", "create_pi", "dot_literal_pi"])
def test_file_only_prefixes_are_not_stripped_from_directories(repo: Path, name: str) -> None:
    """ファイル用の属性は、ディレクトリでは名前の一部 (chezmoi managed で確認済み)。別の target を消さない。"""
    _write(repo / "home" / name / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / name).exists()


def test_multiline_template_in_chezmoiremove_disables_cleanup(repo: Path) -> None:
    """条件つきの複数行は行単位で解釈できないので、テンプレートがあれば何も消さない。"""
    _write(repo / "home" / ".chezmoiremove", "{{ if false }}\n.config/pi\n{{ end }}\n")
    _write(repo / "home" / "dot_config" / "pi" / "__pycache__" / "m.pyc")
    proc = _run(repo)
    assert proc.returncode == 0
    assert (repo / "home" / "dot_config" / "pi").exists()
    assert "テンプレート" in proc.stderr
