"""docs の索引整合を検査する lint_docs.py の挙動を確認する。

索引が腐ると docs 全体が腐るので、整合の検出をここで押さえる。

**このテストの半分は「落ちないこと」の確認**である。設計の過程で一度は入れた
ものの、運用と両立しないと分かって撤回した制約がいくつかある。それらを後から
善意で再導入してしまわないよう、回帰試験として残す。

- 連番の欠番を許す (終了した案件が出れば欠番は正常に生じる)
- ルート index.md にカテゴリ索引と同じ構成を求めない (契約が違う)
- 相対リンクを全数検査しない (実行時間に見合わない)

Run with: ``uv run --with pytest --no-project pytest test/test_lint_docs.py -q``
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "lint_docs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lint_docs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_docs"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lint():
    return load_module()


def build_docs(tmp_path: Path) -> Path:
    """最小の健全な docs ツリーを作る。"""
    docs = tmp_path / "docs"
    for name in ("spec", "adr", "research", "change"):
        (docs / name).mkdir(parents=True)

    (docs / "index.md").write_text("# 現在地とドキュメント\n", encoding="utf-8")

    (docs / "spec" / "index.md").write_text(
        "# 仕様\n\n## 一覧\n\n| 文書 | 内容 |\n| --- | --- |\n| [x](x.md) | x |\n",
        encoding="utf-8",
    )
    (docs / "spec" / "x.md").write_text("# x\n", encoding="utf-8")

    (docs / "adr" / "index.md").write_text(
        "# ADR\n\n## 一覧\n\n| [0001](0001-a.md) | a |\n",
        encoding="utf-8",
    )
    (docs / "adr" / "0001-a.md").write_text(
        "# a\n\n- **ステータス**: Accepted\n",
        encoding="utf-8",
    )

    (docs / "research" / "index.md").write_text(
        "# 調査\n\n## 一覧\n\n| [t](t.md) | t |\n",
        encoding="utf-8",
    )
    (docs / "research" / "t.md").write_text("# t\n", encoding="utf-8")

    (docs / "change" / "index.md").write_text(
        "# 案件\n\n## 活動中\n\n| [0001](0001-a.md) | a | Exploring |\n\n## 終了\n\n（なし）\n",
        encoding="utf-8",
    )
    (docs / "change" / "0001-a.md").write_text(
        "# CHG-0001\n\n- **状態**: Exploring\n",
        encoding="utf-8",
    )
    return docs


def test_clean_tree_passes(lint, tmp_path: Path):
    assert lint.lint_docs(build_docs(tmp_path)) == []


def test_real_repository_docs_pass(lint):
    """このリポジトリの実データが契約を満たしていること。"""
    assert lint.lint_docs(ROOT / "docs") == []


# --- 検出すべきもの -----------------------------------------------------


def test_missing_from_index_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    (docs / "spec" / "orphan.md").write_text("# orphan\n", encoding="utf-8")

    problems = lint.lint_docs(docs)
    assert any("orphan.md" in p and "載っていない" in p for p in problems)


def test_dangling_index_entry_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    index = docs / "spec" / "index.md"
    text = index.read_text(encoding="utf-8")
    index.write_text(text + "| [gone](gone.md) | g |\n", encoding="utf-8")

    problems = lint.lint_docs(docs)
    assert any("gone.md" in p and "実在しない" in p for p in problems)


def test_duplicate_number_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    (docs / "adr" / "0001-b.md").write_text("# b\n", encoding="utf-8")
    index = docs / "adr" / "index.md"
    text = index.read_text(encoding="utf-8")
    index.write_text(text + "| [0001](0001-b.md) | b |\n", encoding="utf-8")

    problems = lint.lint_docs(docs)
    assert any("重複" in p for p in problems)


def test_unknown_change_state_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    (docs / "change" / "0001-a.md").write_text(
        "# CHG-0001\n\n- **状態**: とりあえず\n",
        encoding="utf-8",
    )
    problems = lint.lint_docs(docs)
    assert any("既定値でない" in p for p in problems)


def test_closed_change_left_in_active_is_detected(lint, tmp_path: Path):
    """終了した案件が活動中に残っていたら落とす。

    これが「終了しても削除しない」運用の安全網になる。削除しない代わりに、
    活動中の一覧から外すことだけは機械で保証する。
    """
    docs = build_docs(tmp_path)
    (docs / "change" / "0001-a.md").write_text(
        "# CHG-0001\n\n- **状態**: Done\n",
        encoding="utf-8",
    )
    problems = lint.lint_docs(docs)
    assert any("活動中" in p for p in problems)


def test_missing_change_state_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    (docs / "change" / "0001-a.md").write_text("# CHG-0001\n\n本文\n", encoding="utf-8")
    problems = lint.lint_docs(docs)
    assert any("状態" in p for p in problems)


def test_dangling_superseded_reference_is_detected(lint, tmp_path: Path):
    docs = build_docs(tmp_path)
    (docs / "adr" / "0001-a.md").write_text(
        "# a\n\n- **ステータス**: Superseded by ADR-0099\n",
        encoding="utf-8",
    )
    problems = lint.lint_docs(docs)
    assert any("0099" in p for p in problems)


# --- 撤回した制約の回帰試験（落ちないこと） -----------------------------


def test_gap_in_numbering_is_allowed(lint, tmp_path: Path):
    """★欠番を許す。

    終了した案件は削除せず残すが、番号が飛ぶこと自体は正常に起きる。
    番号の連続性は正しさではないので、一意性だけを見る。
    """
    docs = build_docs(tmp_path)
    (docs / "change" / "0007-later.md").write_text(
        "# CHG-0007\n\n- **状態**: Planned\n",
        encoding="utf-8",
    )
    index = docs / "change" / "index.md"
    text = index.read_text(encoding="utf-8").replace(
        "| [0001](0001-a.md) | a | Exploring |",
        "| [0001](0001-a.md) | a | Exploring |\n| [0007](0007-later.md) | l | Planned |",
    )
    index.write_text(text, encoding="utf-8")

    assert lint.lint_docs(docs) == [], "0002〜0006 が無くても合格すること"


def test_root_index_is_not_required_to_match_category_contract(lint, tmp_path: Path):
    """★ルート索引に「## 運用」や一覧を求めない。

    ルートはダッシュボードとナビゲーションで、カテゴリ索引とは契約が違う。
    """
    docs = build_docs(tmp_path)
    (docs / "index.md").write_text(
        "# 現在地\n\n## 活動中\n\n表だけ\n",
        encoding="utf-8",
    )
    assert lint.lint_docs(docs) == []


def test_relative_links_are_not_exhaustively_checked(lint, tmp_path: Path):
    """★本文中の相対リンクを全数検査しない。

    実行時間に見合わない。索引経由の参照で主要な壊れは捕まる。
    """
    docs = build_docs(tmp_path)
    (docs / "spec" / "x.md").write_text(
        "# x\n\n[壊れたリンク](../nowhere/none.md) と [これも](./missing.md)\n",
        encoding="utf-8",
    )
    assert lint.lint_docs(docs) == []


def test_closed_change_kept_on_disk_is_allowed(lint, tmp_path: Path):
    """★終了した案件をディスクに残してよい。

    削除を要求しない。索引の「終了」区分に移してあれば合格する。
    """
    docs = build_docs(tmp_path)
    (docs / "change" / "0002-done.md").write_text(
        "# CHG-0002\n\n- **状態**: Done\n",
        encoding="utf-8",
    )
    index = docs / "change" / "index.md"
    text = index.read_text(encoding="utf-8").replace(
        "## 終了\n\n（なし）",
        "## 終了\n\n| [0002](0002-done.md) | d | 採用 |",
    )
    index.write_text(text, encoding="utf-8")

    assert lint.lint_docs(docs) == []


def test_missing_category_directory_is_not_an_error(lint, tmp_path: Path):
    """カテゴリが無いリポジトリでも落とさない。

    このスキルは他のリポジトリでも動く。4 種類が揃っていることを前提にしない。
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# docs\n", encoding="utf-8")
    assert lint.lint_docs(docs) == []
