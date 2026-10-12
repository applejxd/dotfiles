"""docs_state.py (sdd-docs スキルの「指示なし」の入口) の挙動を確認する。

押さえること:

- 状態の判定 (absent / partial / complete)。索引が全て在るときだけ complete
- `scaffold` は足りない索引だけを作り、既存を上書きしない。作った骨組みは `lint_docs.py` を通る
- `status` は前回 docs を更新したコミット以降の差分 (コミット・未コミット・未追跡) を出し、
  docs の中の変更は含めず、変わったファイルに言及している文書を示す

Run with: ``uv run --with pytest --no-project pytest test/test_docs_state.py -q``
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "home" / "dot_claude" / "skills" / "sdd-docs"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ds = load("docs_state")
lint = load("lint_docs")


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def test_structure_distinguishes_absent_partial_and_complete(tmp_path):
    docs = tmp_path / "docs"
    assert ds.structure(docs)[0] == "absent"

    ds.scaffold(docs, "P", "目的")
    assert ds.structure(docs) == ("complete", [])

    (docs / "adr" / "index.md").unlink()
    state, missing = ds.structure(docs)
    assert state == "partial" and missing == ["adr/index.md"]


def test_scaffold_fills_in_title_and_purpose_and_passes_the_docs_lint(tmp_path):
    docs = tmp_path / "docs"
    created = ds.scaffold(docs, "MyProject", "検索を速くする")

    assert sorted(created) == sorted(ds.SCAFFOLD_FILES)
    root = (docs / "index.md").read_text(encoding="utf-8")
    assert "MyProject" in root and "検索を速くする" in root and "{{" not in root
    # 空の骨組みが、そのまま索引の検査を通る (これが通らないと、最初の lint で落ちる)
    assert lint.lint_docs(docs) == []


def test_scaffold_never_overwrites_existing_files_and_only_fills_the_gaps(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# 既存の入口\n", encoding="utf-8")

    created = ds.scaffold(docs, "P", "目的")

    assert "index.md" not in created
    assert (docs / "index.md").read_text(encoding="utf-8") == "# 既存の入口\n"
    assert ds.scaffold(docs, "P", "目的") == []  # 2 回目は何も作らない (冪等)


def test_status_for_absent_lists_existing_markdown_without_touching_it(repo, capsys):
    docs = repo / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("# メモ\n", encoding="utf-8")

    assert ds.main(["status"]) == 0
    out = capsys.readouterr().out

    assert "state: absent" in out and "notes.md" in out and "消さない" in out
    assert not (docs / "index.md").exists()  # status は何も作らない


def test_status_for_a_missing_docs_directory_is_absent(repo, capsys):
    assert ds.main(["status"]) == 0
    assert "state: absent" in capsys.readouterr().out


def test_status_for_partial_names_the_missing_indexes(repo, capsys):
    ds.scaffold(repo / "docs", "P", "目的")
    (repo / "docs" / "research" / "index.md").unlink()

    assert ds.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "state: partial" in out and "research/index.md" in out


def test_status_reports_changes_since_the_last_docs_commit(repo, capsys):
    (repo / "src").mkdir()
    (repo / "src" / "service_config.py").write_text("v = 1\n", encoding="utf-8")
    ds.scaffold(repo / "docs", "P", "目的")
    (repo / "docs" / "spec" / "setup.md").write_text("`src/service_config.py` で設定する\n", encoding="utf-8")
    commit_all(repo, "feat: 初期")

    (repo / "src" / "service_config.py").write_text("v = 2\n", encoding="utf-8")
    commit_all(repo, "fix: 設定の値を変える")
    (repo / "src" / "other_module.py").write_text("x = 1\n", encoding="utf-8")  # 未追跡
    (repo / "docs" / "spec" / "setup.md").write_text("`src/service_config.py` で設定する (追記)\n", encoding="utf-8")

    assert ds.main(["status"]) == 0
    out = capsys.readouterr().out

    assert "state: complete" in out
    assert "feat: 初期" in out.split("それ以降")[0]  # 基準は docs を最後に変えたコミット
    assert "それ以降のコミット: 1 件" in out and "fix: 設定の値を変える" in out
    assert "src/service_config.py" in out and "src/other_module.py" in out  # 未追跡も含める
    # docs の中の変更は「docs の外で変わったファイル」に含めない
    changed = out.split("docs の外で変わったファイル")[1]
    assert "setup.md" not in changed.split("変わったファイルに言及")[0]
    # 変わったファイルに言及している文書を示す
    assert "spec/setup.md: src/service_config.py" in out


def test_status_without_any_docs_commit_looks_at_recent_history_only(repo, capsys):
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    commit_all(repo, "chore: 最初")
    ds.scaffold(repo / "docs", "P", "目的")  # 未コミット

    assert ds.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "（無い。直近の履歴だけを見る）" in out and "chore: 最初" in out


def test_status_outside_a_git_repository_says_so(tmp_path, monkeypatch, capsys):
    ds.scaffold(tmp_path / "docs", "P", "目的")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert ds.main(["status"]) == 0
    assert "git のリポジトリでない" in capsys.readouterr().out


def test_status_lists_active_cases_with_their_state(repo, capsys):
    ds.scaffold(repo / "docs", "P", "目的")
    (repo / "docs" / "change" / "0001-first.md").write_text(
        "# CHG-0001: 最初の案件\n\n- **状態**: In progress\n", encoding="utf-8"
    )
    commit_all(repo, "docs: 初期")

    assert ds.main(["status"]) == 0
    assert "0001-first.md [In progress] CHG-0001: 最初の案件" in capsys.readouterr().out


def test_scaffold_command_prints_what_it_created(repo, capsys):
    assert ds.main(["scaffold", "--title", "X", "--purpose", "Y"]) == 0
    assert "作成:" in capsys.readouterr().out
    assert ds.main(["scaffold"]) == 0
    assert "索引は全て在る" in capsys.readouterr().out
