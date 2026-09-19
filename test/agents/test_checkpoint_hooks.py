"""checkpoint hook の共通処理 (checkpoint_core.py) の挙動を確認する。

段 5 の hook は「圧縮の直前に機械的事実を残す」「圧縮の直後に自分の記録を戻す」
の 2 つだけを担う。ここで押さえるのは次の 3 点。

- 機械節の差し替えが**意味内容を壊さない**こと。特に ``updated_at`` と
  ``covered_through`` を動かさないこと (動かすと古い内容が「新鮮」に見える)
- 復帰が**自分のファイルだけ**を読むこと
- スキル未配備や壊れた入力でも**落ちない**こと (hook の失敗でセッションを
  止めない)

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / "home" / "dot_claude" / "hooks" / "lib" / "checkpoint_core.py"
SKILL_PATH = (
    ROOT
    / "home"
    / "dot_claude"
    / "skills"
    / "checkpoint"
    / "scripts"
    / "executable_checkpoint.py"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def core():
    return _load("checkpoint_core", CORE_PATH)


@pytest.fixture(scope="module")
def skill():
    return _load("checkpoint_cli", SKILL_PATH)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    return tmp_path


WRITTEN = (
    "<!-- checkpoint: v1\n"
    "     session: demo1234\n"
    "     updated_at: 2026-09-19T10:00:00+09:00\n"
    "     covered_through: msg-42\n"
    "-->\n"
    "# Checkpoint — sample\n\n"
    "## Goal\n達成条件。\n\n"
    "## Constraints\n- 制約 A\n\n"
    "## State\n- 完了: X\n\n"
    "## Evidence\n- `pytest -q`: 3 passed\n\n"
    "## Next\n- 次の 1 手\n\n"
    "## Refs\n- docs/spec/x.md — 手順の確認用\n"
)


# --- 機械節の差し替え ---------------------------------------------------


def test_machine_section_is_appended_when_absent(core):
    out = core.replace_machine_section(WRITTEN, "<!-- machine: x -->\n## Snapshot\nhead: abc\n")
    assert "## Goal" in out
    assert "## Snapshot" in out


def test_machine_section_is_replaced_not_duplicated(core):
    first = core.replace_machine_section(WRITTEN, "<!-- machine: x -->\n古い\n")
    second = core.replace_machine_section(first, "<!-- machine: x -->\n新しい\n")

    assert second.count("<!-- machine:") == 1
    assert "古い" not in second
    assert "新しい" in second


def test_machine_section_never_touches_semantic_content(core):
    """★意味内容と鮮度の印を動かさない。

    ここを動かすと、PreCompact が機械節を書いた瞬間に古い意味内容が
    「新鮮」に見えてしまう。
    """
    out = core.replace_machine_section(WRITTEN, "<!-- machine: x -->\n## Snapshot\n")

    assert "updated_at: 2026-09-19T10:00:00+09:00" in out
    assert "covered_through: msg-42" in out
    for heading in ("## Goal", "## Constraints", "## State", "## Evidence", "## Next", "## Refs"):
        assert heading in out
    assert "達成条件。" in out


def test_snapshot_survives_the_structure_lint(core, skill):
    """機械節を足しても構造検査に落ちない。"""
    out = core.replace_machine_section(WRITTEN, core.collect_snapshot(ROOT, "auto"))
    errors, _ = skill.lint(out)
    assert errors == []


def test_snapshot_is_excluded_from_the_budget(core, skill):
    """機械節は意味内容の予算に含めない。"""
    out = core.replace_machine_section(WRITTEN, core.collect_snapshot(ROOT, "auto"))
    errors, _ = skill.lint(out, budget=len(WRITTEN.strip()) + 50)
    assert errors == []


# --- 機械的事実の収集 ---------------------------------------------------


def test_snapshot_records_head_and_trigger(core, repo: Path):
    snapshot = core.collect_snapshot(repo, "auto")
    assert "trigger: auto" in snapshot
    assert "head:" in snapshot
    assert "(不明)" not in snapshot.split("head:")[1].splitlines()[0]


def test_snapshot_lists_changed_files(core, repo: Path):
    (repo / "new.txt").write_text("x", encoding="utf-8")
    snapshot = core.collect_snapshot(repo, "manual")
    assert "new.txt" in snapshot


def test_porcelain_path_keeps_the_whole_path(core):
    """★行頭を固定長で切らない。

    ``git status --porcelain=v1`` の状態コードは 2 文字だが、片方が空白の
    こともある (` M path`)。3 文字目から切ると、未追跡 (`?? path`) では
    正しくても、変更済みではパスの先頭 1 文字を食う。
    """
    assert core._porcelain_path("?? home/x.md") == "home/x.md"
    assert core._porcelain_path(" M home/x.md") == "home/x.md"
    assert core._porcelain_path("M  home/x.md") == "home/x.md"
    assert core._porcelain_path("A  home/x.md") == "home/x.md"
    # リネームは新しい側を採る
    assert core._porcelain_path("R  old.md -> new.md") == "new.md"


def test_snapshot_does_not_truncate_modified_paths(core, repo: Path):
    """変更済みファイルのパスが欠けないこと（上のバグの実地確認）。"""
    target = repo / "home" / "deep" / "tracked.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add"], cwd=repo, check=True)
    target.write_text("y", encoding="utf-8")

    snapshot = core.collect_snapshot(repo, "auto")
    assert "home/deep/tracked.md" in snapshot
    assert "ome/deep/tracked.md" not in snapshot.replace("home/deep/tracked.md", "")


def test_snapshot_truncates_long_file_lists(core, repo: Path):
    for index in range(core.MAX_LISTED_FILES + 8):
        (repo / f"f{index}.txt").write_text("x", encoding="utf-8")
    snapshot = core.collect_snapshot(repo, "auto")
    assert "ほか" in snapshot, "打ち切りの注記が無い"
    assert snapshot.count("  - f") <= core.MAX_LISTED_FILES


def test_snapshot_outside_git_does_not_crash(core, tmp_path: Path):
    snapshot = core.collect_snapshot(tmp_path / "nope", "auto")
    assert "## Snapshot" in snapshot


# --- 書き込み -----------------------------------------------------------


def test_write_snapshot_creates_skeleton_when_missing(core, skill, repo: Path):
    """記録が無くても、機械的事実だけは残す（空よりマシ）。"""
    data = {"session_id": "sess-1111", "cwd": str(repo), "trigger": "auto"}
    result = core.write_snapshot(data, module=skill)

    assert result["ok"] is True
    assert result["created"] is True

    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "## Snapshot" in text
    assert "(未記入" in text, "意味内容が未記入であることが分かる形になっていない"


def test_write_snapshot_preserves_existing_content(core, skill, repo: Path):
    data = {"session_id": "sess-2222", "cwd": str(repo), "trigger": "manual"}
    paths = skill.resolve_paths("sess-2222", repo)
    target = Path(paths["checkpoint"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WRITTEN, encoding="utf-8")

    result = core.write_snapshot(data, module=skill)
    assert result["ok"] is True
    assert result["created"] is False

    text = target.read_text(encoding="utf-8")
    assert "達成条件。" in text
    assert "covered_through: msg-42" in text
    assert "trigger: manual" in text


def test_write_snapshot_without_session_id_is_not_an_error(core, skill, repo: Path):
    result = core.write_snapshot({"cwd": str(repo)}, module=skill)
    assert result["ok"] is False


def test_write_snapshot_without_skill_is_not_an_error(core, repo: Path, monkeypatch):
    """スキル未配備でも落とさない。"""
    monkeypatch.setattr(core, "load_skill_module", lambda *a, **k: None)
    result = core.write_snapshot({"session_id": "s", "cwd": str(repo)})
    assert result["ok"] is False


# --- 復帰 ---------------------------------------------------------------


def test_read_checkpoint_returns_own_file(core, skill, repo: Path):
    paths = skill.resolve_paths("sess-3333", repo)
    target = Path(paths["checkpoint"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WRITTEN, encoding="utf-8")

    text = core.read_checkpoint({"session_id": "sess-3333", "cwd": str(repo)}, module=skill)
    assert text is not None
    assert "達成条件。" in text


def test_read_checkpoint_never_reads_another_session(core, skill, repo: Path):
    """★他セッションの記録を読まない。

    保存先をセッション別にした目的がここにある。固定名を探しに行くと、
    別セッションの本文を注入してしまう。
    """
    other = skill.resolve_paths("sess-other", repo)
    Path(other["checkpoint"]).parent.mkdir(parents=True, exist_ok=True)
    Path(other["checkpoint"]).write_text("他セッションの記録", encoding="utf-8")
    # 固定名も置いてみる（昔の設計の名残を拾わないこと）
    (repo / ".tmp" / "checkpoint.md").write_text("固定名の記録", encoding="utf-8")

    text = core.read_checkpoint({"session_id": "sess-mine", "cwd": str(repo)}, module=skill)
    assert text is None


def test_read_checkpoint_without_session_id(core, skill, repo: Path):
    assert core.read_checkpoint({"cwd": str(repo)}, module=skill) is None


# --- 入力の読み取り -----------------------------------------------------


def test_session_id_accepts_both_key_styles(core):
    assert core.session_id_of({"session_id": "a"}) == "a"
    assert core.session_id_of({"sessionId": "b"}) == "b"
    assert core.session_id_of({}) == ""


def test_trigger_is_optional(core):
    assert core.trigger_of({"trigger": "auto"}) == "auto"
    assert core.trigger_of({}) == ""


# --- hook 本体 ----------------------------------------------------------


def run_hook(name: str, stdin: str) -> subprocess.CompletedProcess:
    path = ROOT / "home" / "dot_claude" / "hooks" / f"executable_{name}.py"
    return subprocess.run(
        [sys.executable, str(path)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_precompact_hook_never_blocks(repo: Path):
    """★自動圧縮を絶対にブロックしない。

    context-limit エラーからの回復として発火した自動圧縮を止めると、元の
    エラーが表面化して現在のリクエストが失敗する。機械記録のためにユーザの
    作業を失わせるのは割に合わない。
    """
    payload = f'{{"session_id": "s1", "cwd": "{repo}", "trigger": "auto"}}'
    done = run_hook("checkpoint_precompact", payload)
    assert done.returncode == 0


def test_precompact_hook_survives_broken_input():
    done = run_hook("checkpoint_precompact", "これは JSON ではない")
    assert done.returncode == 0


def test_restore_hook_reports_when_nothing_to_restore(repo: Path):
    payload = f'{{"session_id": "unknown", "cwd": "{repo}"}}'
    done = run_hook("checkpoint_restore", payload)
    assert done.returncode == 0
    assert "見つかりません" in done.stdout


def test_restore_hook_survives_broken_input():
    done = run_hook("checkpoint_restore", "{")
    assert done.returncode == 0
