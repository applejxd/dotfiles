"""sdd-docs スキルの check_refs.py (docs への参照の切れの検査) の挙動を確かめる。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home" / "dot_claude" / "skills" / "sdd-docs" / "scripts" / "check_refs.py"


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # tmp_path がこのリポジトリの中にあっても、外側の repo を拾わせない
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(repo.parent)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


GOOD = {
    "docs/a.md": "# A\n\n## 手順の説明\n\n[b](b.md#見出し-b)\n",
    "docs/b.md": "# B\n\n## 見出し B\n",
    "src/x.py": "# see docs/a.md#手順の説明\n# see docs/b.md 「見出し B」\n",
}


def test_valid_references_pass(tmp_path):
    result = run(make_repo(tmp_path, GOOD))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("rel", "text", "expected"),
    [
        ("docs/a.md", "[x](missing.md)\n", "ファイルが無い"),
        ("docs/a.md", "[x](b.md#無い見出し)\n", "見出しが無い"),
        ("src/x.py", "# see docs/b.md#無い見出し\n", "見出しが無い"),
        ("src/x.py", "# see docs/b.md 「無い見出し」\n", "名前の見出しが無い"),
    ],
    ids=["リンク先のファイル", "リンク先の見出し", "コメントのアンカー", "コメントの見出し名"],
)
def test_broken_references_are_reported(tmp_path, rel, text, expected):
    files = dict(GOOD)
    files[rel] = files.get(rel, "") + text
    result = run(make_repo(tmp_path, files))
    assert result.returncode == 1
    assert expected in result.stdout


def test_headings_in_code_blocks_are_not_anchors(tmp_path):
    files = dict(GOOD)
    files["docs/b.md"] = "# B\n\n```text\n## 見出し B\n```\n"
    result = run(make_repo(tmp_path, files))
    assert "見出しが無い" in result.stdout


def test_baseline_shows_only_new_problems(tmp_path):
    """作業前に控えた問題は出さず、作業で新たに切れた参照だけを出す。"""
    files = dict(GOOD)
    files["docs/a.md"] += "[old](gone.md)\n"
    repo = make_repo(tmp_path, files)
    baseline = tmp_path / "before.txt"
    assert run(repo, "--save", str(baseline)).returncode == 1

    assert run(repo, "--baseline", str(baseline)).returncode == 0
    (repo / "docs" / "b.md").write_text("# B\n\n## 名前を変えた\n", encoding="utf-8")
    result = run(repo, "--baseline", str(baseline))
    assert result.returncode == 1
    assert "gone.md" not in result.stdout
    assert "見出し-b" in result.stdout


def test_outside_a_git_repository_is_a_usage_error(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 2


def test_save_creates_missing_parent_directory(tmp_path):
    """控えの置き場 (.tmp/ など) が無いリポジトリでも --save が通る。"""
    repo = make_repo(tmp_path, GOOD)
    saved = repo / ".tmp" / "nested" / "refs-before.txt"
    result = run(repo, "--save", str(saved))
    assert result.returncode == 0, result.stderr
    assert saved.is_file()
    assert run(repo, "--baseline", str(saved)).returncode == 0


def test_baseline_file_inside_the_repository_is_not_scanned(tmp_path):
    """控えが git の管理外でなくても、控えに書かれたパスを新しい切れと数えない。"""
    files = dict(GOOD)
    files["src/x.py"] += "# see docs/b.md#無い見出し\n"
    repo = make_repo(tmp_path, files)
    saved = repo / "refs-before.txt"
    assert run(repo, "--save", str(saved)).returncode == 1
    result = run(repo, "--baseline", str(saved))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "text",
    [
        "# see sdd-docs/references/adr-template.md\n",
        "# see ~/.claude/skills/sdd-docs/SKILL.md\n",
        "# see my.docs/x.md\n",
        "# see sdd-docs/b.md 「無い見出し」\n",
    ],
    ids=[
        "ハイフン付きのディレクトリ名",
        "ホーム配下のスキル",
        "ドット付きの名前",
        "見出し名の参照",
    ],
)
def test_docs_inside_another_path_is_not_a_reference(tmp_path, text):
    """パスの途中に現れる `docs/` を、リポジトリの docs/ への参照と取り違えない。"""
    files = dict(GOOD)
    files["src/y.py"] = text
    result = run(make_repo(tmp_path, files))
    assert result.returncode == 0, result.stdout


def test_git_does_not_run_the_repository_fsmonitor(tmp_path):
    """.git/config の core.fsmonitor を起動しない。

    OpenCode はこのスクリプトを確認なしに実行させる。リポジトリの設定から
    任意コマンドを起動できると、確認を経ない実行の入口になる。
    see docs/spec/agent-config-generation.md#スキルのスクリプト
    """
    repo = make_repo(tmp_path, GOOD)
    mark = tmp_path / "fsmonitor-ran"
    subprocess.run(
        ["git", "config", "core.fsmonitor", f"touch '{mark}'; false"], cwd=repo, check=True
    )
    (repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    assert run(repo).returncode == 0
    assert not mark.exists()


def test_save_and_baseline_default_to_the_repository_tmp(tmp_path):
    """パスを省くとルートの .tmp/refs-before.txt を使う。

    OpenCode はこの形だけを確認なしに通す (書き込み先を引数で決められない)。
    """
    files = dict(GOOD)
    files["src/x.py"] += "# see docs/b.md#無い見出し\n"
    repo = make_repo(tmp_path, files)
    assert run(repo, "--save").returncode == 1
    assert (repo / ".tmp" / "refs-before.txt").is_file()
    result = run(repo, "--baseline")
    assert result.returncode == 0, result.stdout
