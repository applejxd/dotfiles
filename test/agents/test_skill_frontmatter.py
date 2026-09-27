"""SKILL.md の frontmatter が全ファイルで妥当かを確認する。

frontmatter が壊れたスキルは CLI に黙って読み飛ばされ、起動時に
"Failed to load 1 skill." としか出ない。pre-commit の
skill-frontmatter-local と同じ検証をリポジトリ全体に掛ける。

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "scripts" / "agents"))

import validate_skills as vs  # noqa: E402

SKILL_PATHS = vs.discover()

# 収集ロジックと独立に書いた既知のパス。glob を使い回すと自己確認になる。
KNOWN_SKILLS = [
    "home/dot_claude/skills/commit/SKILL.md",
    "home/dot_codex/skills/commit/SKILL.md",
    "home/dot_config/opencode/skills/checkpoint/SKILL.md",
]


def test_skill_files_are_discovered():
    assert SKILL_PATHS, f"{vs.SKILL_ROOTS} に SKILL.md が無い"


@pytest.mark.parametrize("relpath", KNOWN_SKILLS)
def test_known_skills_are_collected(relpath: str):
    """OpenCode 専用の checkpoint は `home/*/skills/` の形に収まらず漏れていた。"""
    assert ROOT / relpath in SKILL_PATHS


def tracked_skill_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", ":(glob)home/**/SKILL.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def test_every_tracked_skill_is_collected():
    """新しい配布先を足したときに SKILL_ROOTS の更新漏れを検出する。

    skill に同梱した資材の中の SKILL.md（skill ディレクトリの配下）は除く。
    """
    skill_dirs = {path.parent for path in SKILL_PATHS}
    missed = [
        path
        for path in tracked_skill_files()
        if path not in SKILL_PATHS
        and not any(d in path.parents for d in skill_dirs)
    ]
    assert not missed, f"SKILL_ROOTS に無い場所の SKILL.md: {missed}"


def test_pre_commit_hook_covers_the_same_files():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text("utf-8"))
    [hook] = [
        hook
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "skill-frontmatter-local"
    ]
    pattern = re.compile(hook["files"])
    for relpath in KNOWN_SKILLS:
        assert pattern.search(relpath), relpath
    for path in SKILL_PATHS:
        assert pattern.search(path.relative_to(ROOT).as_posix()), path


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


# ---------------------------------------------------------------------------
# description と本文の整合 (個別の skill)
# ---------------------------------------------------------------------------

CLAUDE_SKILLS = ROOT / "home/dot_claude/skills"


def load_skill(name: str) -> tuple[dict, str]:
    frontmatter, body = vs.split_frontmatter(
        (CLAUDE_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    )
    return yaml.safe_load(frontmatter), body


def test_learn_proposes_by_default():
    """description は「提案する」なのに本文が直接書き込ませていた。"""
    data, body = load_skill("learn")
    assert "提案" in data["description"]
    assert "書き込まない" in body
    assert "明示的" in body
    # fork を撤去した後も残っていた、サブエージェント前提の宛先
    assert "親エージェント" not in body


def test_review_loop_description_states_the_real_stop_condition():
    data, body = load_skill("review-loop")
    rounds = re.search(r"上限: (\d+) ラウンド", body).group(1)
    assert "BLOCKER" in data["description"] and "MAJOR" in data["description"]
    assert f"{rounds} ラウンド" in data["description"]
    # トリガーの言い回しは残す
    assert "「指摘が無くなるまで直して」" in data["description"]


def test_uv_migration_description_names_uv_lock_and_mise():
    """本文は uv.lock と mise.toml を前提にしている (「pyproject.toml のみ」ではない)。"""
    data, _ = load_skill("uv-migration")
    assert "のみ" not in data["description"]
    assert "uv.lock" in data["description"]
    assert "mise" in data["description"]


def test_hook_creator_branches_before_direct_registration():
    """common.toml が正本の環境で、生成先を直接編集させない。"""
    _, body = load_skill("hook-creator")
    branch = body.index("## 登録先の判定")
    assert branch < body.index("## 判断フロー")
    assert branch < body.index("## テンプレート選択と配置")


def test_hook_creator_names_existing_sources():
    """source state のパスが古いと、managed の手順で存在しないファイルを探す。"""
    _, body = load_skill("hook-creator")
    relpaths = re.findall(r"`(home/[^`<>{}*]+)`", body)
    assert relpaths
    for relpath in relpaths:
        assert (ROOT / relpath).exists(), relpath
