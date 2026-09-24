"""SKILL.md の frontmatter が全ファイルで妥当かを確認する。

frontmatter が壊れたスキルは CLI に黙って読み飛ばされ、起動時に
"Failed to load 1 skill." としか出ない。pre-commit の
skill-frontmatter-local と同じ検証をリポジトリ全体に掛ける。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import validate_skills as vs  # noqa: E402

SKILL_PATHS = sorted(ROOT.glob(vs.SKILL_GLOB))


def test_skill_files_are_discovered():
    assert SKILL_PATHS, f"{vs.SKILL_GLOB} に一致する SKILL.md が無い"


@pytest.mark.parametrize("path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_valid(path: Path):
    errors = vs.validate(path)
    assert not errors, f"{path.relative_to(ROOT)}: " + " / ".join(errors)


def write_skill(tmp_path: Path, name: str, frontmatter: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n# {name}\n", encoding="utf-8")
    return path


def test_colon_in_unquoted_description_is_rejected(tmp_path):
    """今回の再発防止対象。`undefined symbol: _ZNK3c10` のコロンで落ちる。"""
    path = write_skill(
        tmp_path,
        "sample",
        "name: sample\ndescription: 「undefined symbol: _ZNK3c10」と言われたら使う",
    )
    errors = vs.validate(path)
    assert errors
    assert "YAML パースに失敗" in errors[0]


def test_colon_in_quoted_description_is_accepted(tmp_path):
    path = write_skill(
        tmp_path,
        "sample",
        'name: sample\ndescription: "「undefined symbol: _ZNK3c10」と言われたら使う"',
    )
    assert vs.validate(path) == []


def test_hash_in_unquoted_description_is_rejected(tmp_path):
    """パースは通るが ` #` 以降が無言で捨てられるため、引用符を要求する。"""
    path = write_skill(
        tmp_path, "sample", "name: sample\ndescription: use # for comments"
    )
    errors = vs.validate(path)
    assert any("引用符で囲むこと" in e for e in errors)


def test_name_must_match_directory(tmp_path):
    path = write_skill(tmp_path, "sample", "name: other\ndescription: x")
    errors = vs.validate(path)
    assert any("ディレクトリ名" in e for e in errors)


def test_missing_frontmatter_is_rejected(tmp_path):
    skill_dir = tmp_path / "sample"
    skill_dir.mkdir()
    path = skill_dir / "SKILL.md"
    path.write_text("# sample\n", encoding="utf-8")
    assert vs.validate(path) == ["先頭の `---` で囲んだ YAML frontmatter が無い"]


def test_missing_description_is_rejected(tmp_path):
    path = write_skill(tmp_path, "sample", "name: sample")
    errors = vs.validate(path)
    assert any("description が無い" in e for e in errors)


def test_too_long_description_is_rejected(tmp_path):
    long_text = "あ" * (vs.MAX_DESCRIPTION_LEN + 1)
    path = write_skill(tmp_path, "sample", f"name: sample\ndescription: {long_text}")
    errors = vs.validate(path)
    assert any("文字を超える" in e for e in errors)


def write_skill_with_body(tmp_path: Path, name: str, frontmatter: str, body: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    path = skill_dir / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_fork_with_conversation_dependent_body_is_rejected(tmp_path):
    """★fork は会話の分岐ではなく新規コンテキストのサブエージェント。

    2026-09-19 に adr skill を廃止した理由がこれ (ac7749a)。同じ欠陥が
    explain / learn に残っていた。OpenCode は context を読み捨てるので
    無害だが、Claude Code 側で効くと会話が見えないまま要約を書く。

    see docs/research/opencode/skill-frontmatter.md
    """
    path = write_skill_with_body(
        tmp_path,
        "sample",
        "name: sample\ndescription: x\ncontext: fork",
        "これまでの会話を振り返り、要約せよ。",
    )
    errors = vs.validate(path)
    assert any("context: fork" in e for e in errors)


def test_fork_without_conversation_dependency_is_accepted(tmp_path):
    """入力がリポジトリの状態で完結するなら fork してよい (commit / fix など)。"""
    path = write_skill_with_body(
        tmp_path,
        "sample",
        "name: sample\ndescription: x\ncontext: fork",
        "`git diff` を読んでコミットメッセージを書く。",
    )
    assert vs.validate(path) == []


def test_conversation_dependent_body_without_fork_is_accepted(tmp_path):
    path = write_skill_with_body(
        tmp_path,
        "sample",
        "name: sample\ndescription: x",
        "これまでの会話を振り返り、要約せよ。",
    )
    assert vs.validate(path) == []
