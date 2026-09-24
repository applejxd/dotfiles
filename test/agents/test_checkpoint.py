"""checkpoint skill の保存先解決と検査 (checkpoint.py) の挙動を確認する。

compaction を跨いだ復帰では「自分の記録だけを、壊さずに読める」ことが
最優先なので、そこを押さえる。特に次の 3 つは設計上の約束なので回帰させない。

- 保存先は常にセッション別。別セッションのファイルへ触れない
- セッション横断の GC をしない (稼働中の他セッションを消さないため)
- 鮮度は「その要求の固定境界」と比べる。現在の会話地点とは比べない

Run with: ``uv run --with pytest --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    ROOT
    / "home"
    / "dot_config"
    / "opencode"
    / "skills"
    / "checkpoint"
    / "scripts"
    / "executable_checkpoint.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("checkpoint_cli", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["checkpoint_cli"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cp():
    return load_module()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """テスト用の git リポジトリ。除外設定の検証に使う。

    ★利用者のグローバル除外（`~/.config/git/ignore`）を遮断する。
    そこに `.tmp/` があると `ensure_ignored` は「既に無視されている」と判断して
    何も書かないため、遮断しないと環境しだいで結果が変わる。
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    empty = tmp_path / "empty-excludes"
    empty.write_text("", encoding="utf-8")
    subprocess.run(
        ["git", "config", "core.excludesFile", str(empty)], cwd=tmp_path, check=True
    )
    return tmp_path


def valid_checkpoint(boundary: str = "msg-1") -> str:
    return (
        f"<!-- checkpoint: v1\n"
        f"     session: abc12345\n"
        f"     covered_through: {boundary}\n"
        f"-->\n"
        "# Checkpoint — sample\n\n"
        "## Goal\n達成条件を 1 行で。\n\n"
        "## Constraints\n- 制約 A\n\n"
        "## State\n- 完了: X\n\n"
        "## Evidence\n- `pytest -q`: 3 passed\n\n"
        "## Next\n- 次の 1 手\n\n"
        "## Refs\n- docs/spec/x.md — 手順の確認用\n"
    )


# --- 保存先の解決 -------------------------------------------------------


def test_paths_are_always_session_scoped(cp, tmp_path: Path):
    """同じセッションなら常に同じ、別セッションとは必ず違うパスになる。"""
    a1 = cp.resolve_paths("session-aaaa-1111", tmp_path)
    a2 = cp.resolve_paths("session-aaaa-1111", tmp_path)
    b = cp.resolve_paths("session-bbbb-2222", tmp_path)

    assert a1 == a2, "同じセッションは常に同じ保存先へ戻ること"

    for key in ("checkpoint", "prev", "state"):
        assert a1[key] != b[key], f"{key} が別セッションと衝突している"

    # 固定名を奪い合わないので、所有権の交渉もロックも要らない
    assert Path(a1["checkpoint"]).name != "checkpoint.md"


def test_paths_resolve_repo_root_from_subdirectory(cp, git_repo: Path):
    """hook の cwd がサブディレクトリでも、保存先はリポジトリ直下になる。"""
    nested = git_repo / "a" / "b"
    nested.mkdir(parents=True)

    from_root = cp.resolve_paths("session-x", git_repo)
    from_nested = cp.resolve_paths("session-x", nested)

    assert from_nested["checkpoint"] == from_root["checkpoint"]
    assert Path(from_nested["base"]).parent == git_repo.resolve()


def test_paths_outside_git_fall_back_to_cwd(cp, tmp_path: Path, monkeypatch):
    """git が使えなくても解決できる。

    pytest の tmp_path は redirect-tmp の都合でリポジトリ内に作られるため、
    「git が答えない」状況を直接再現して確かめる。
    """
    monkeypatch.setattr(cp, "_run_git", lambda *a, **k: None)
    paths = cp.resolve_paths("session-x", tmp_path)
    assert Path(paths["base"]).parent == tmp_path


def test_session_id_without_usable_characters_is_rejected(cp, tmp_path: Path):
    with pytest.raises(ValueError):
        cp.resolve_paths("----", tmp_path)


# --- GC をしないこと ----------------------------------------------------


def test_writing_never_touches_other_sessions(cp, tmp_path: Path):
    """★保存はセッション横断の削除をしない。

    件数や日数で消すと、稼働中の別セッションの checkpoint と Pending まで
    消えてしまう。保存先を分離した目的そのものが壊れるので回帰させない。
    """
    mine = cp.resolve_paths("session-mine", tmp_path)
    other = cp.resolve_paths("session-other", tmp_path)

    Path(other["checkpoint"]).parent.mkdir(parents=True, exist_ok=True)
    Path(other["checkpoint"]).write_text("他セッションの記録", encoding="utf-8")
    Path(other["state"]).write_text('{"state": "requested"}', encoding="utf-8")

    for index in range(30):
        cp.atomic_write(Path(mine["checkpoint"]), f"世代 {index}")

    assert Path(other["checkpoint"]).read_text(encoding="utf-8") == "他セッションの記録"
    assert Path(other["state"]).exists()


# --- アトミック書き込み -------------------------------------------------


def test_atomic_write_leaves_no_temporary_files(cp, tmp_path: Path):
    target = tmp_path / "nested" / "checkpoint.md"
    cp.atomic_write(target, "本文")

    assert target.read_text(encoding="utf-8") == "本文"
    leftovers = [p.name for p in target.parent.iterdir() if p.name.startswith(".checkpoint-")]
    assert leftovers == []


def test_atomic_write_replaces_existing_content(cp, tmp_path: Path):
    target = tmp_path / "checkpoint.md"
    cp.atomic_write(target, "古い")
    cp.atomic_write(target, "新しい")
    assert target.read_text(encoding="utf-8") == "新しい"


# --- 構造検査 -----------------------------------------------------------


def test_structure_lint_accepts_valid_checkpoint(cp):
    errors, _ = cp.lint(valid_checkpoint())
    assert errors == []


def test_structure_lint_reports_missing_heading(cp):
    text = valid_checkpoint().replace("## Evidence\n- `pytest -q`: 3 passed\n\n", "")
    errors, _ = cp.lint(text)
    assert any("## Evidence" in e for e in errors)


def test_structure_lint_reports_wrong_order(cp):
    text = (
        "# Checkpoint\n\n"
        "## Goal\nx\n\n"
        "## Constraints\nx\n\n"
        "## Evidence\nx\n\n"
        "## State\nx\n\n"
        "## Next\nx\n\n"
        "## Refs\nx\n"
    )
    errors, _ = cp.lint(text)
    assert any("順序" in e for e in errors)


def test_machine_section_is_outside_the_budget(cp):
    """機械節は意味内容の予算と取り合わせない。"""
    body = valid_checkpoint()
    machine = "<!-- machine: -->\n## Snapshot\n" + ("x" * 5000)

    errors, _ = cp.lint(body + machine, budget=2000)
    assert errors == []


def test_budget_counts_only_semantic_content(cp):
    text = valid_checkpoint().replace("達成条件を 1 行で。", "y" * 3000)
    errors, _ = cp.lint(text, budget=2000)
    assert any("予算" in e for e in errors)


def test_budget_error_names_the_section_to_cut(cp):
    """★全体の文字数だけ告げると、書き手が当てずっぽうで削ることになる。"""
    text = valid_checkpoint().replace("- 完了: X", "- " + "z" * 2500)
    errors, _ = cp.lint(text, budget=2000)
    assert len(errors) == 1
    message = errors[0]
    assert "超過" in message
    assert "内訳" in message
    # 最も大きい節が先頭に来ること（削る先が一目で分かる）
    head = message.split("内訳: ", 1)[1]
    assert head.startswith("## State"), head


def test_long_fence_outside_refs_is_rejected(cp):
    fence = "```\n" + "line\n" * 20 + "```\n"
    text = valid_checkpoint().replace("## Evidence\n", f"## Evidence\n{fence}")
    errors, _ = cp.lint(text)
    assert any("コードブロック" in e for e in errors)


def test_long_fence_inside_refs_is_allowed(cp):
    fence = "```\n" + "line\n" * 20 + "```\n"
    text = valid_checkpoint().rstrip("\n") + "\n" + fence
    errors, _ = cp.lint(text)
    assert errors == []


def test_multiple_next_items_are_warning_not_error(cp):
    text = valid_checkpoint().replace("## Next\n- 次の 1 手\n", "## Next\n- A\n- B\n")
    errors, warnings = cp.lint(text)
    assert errors == []
    assert any("Next" in w for w in warnings)


def test_stale_snapshot_at_in_header_is_flagged(cp):
    """★旧雛形の名残。hook はヘッダを触らないので永久に空のまま残る。"""
    text = valid_checkpoint().replace(
        "     covered_through: msg-1\n",
        "     covered_through: msg-1\n     snapshot_at:\n",
    )
    errors, warnings = cp.lint(text)
    assert errors == [], "復帰は妨げないので警告に留めること"
    assert any("snapshot_at" in w for w in warnings)


def test_snapshot_at_in_machine_section_is_not_flagged(cp):
    """機械節の snapshot_at が正本。こちらを警告してはいけない。"""
    text = valid_checkpoint() + (
        "\n<!-- machine: ここから下は PreCompact が上書きする。"
        "意味内容の予算に含めない -->\n"
        "## Snapshot\n\n- snapshot_at: 2026-09-19T15:59:37+09:00\n"
    )
    _, warnings = cp.lint(text)
    assert not any("snapshot_at" in w for w in warnings)


# --- 鮮度検査 -----------------------------------------------------------


def test_freshness_compares_against_the_request_boundary(cp):
    """★固定境界と比べる。保存や検査自身で境界が進んでも合格すること。"""
    text = valid_checkpoint(boundary="msg-7")

    errors, _ = cp.lint(text, boundary="msg-7")
    assert errors == [], "要求の境界と一致しているなら、その後に会話が伸びても合格する"


def test_freshness_rejects_stale_checkpoint(cp):
    """古い checkpoint が構造的に正常でも、新しい要求は満たさない。"""
    text = valid_checkpoint(boundary="msg-1")
    errors, _ = cp.lint(text, boundary="msg-9")
    assert any("covered_through" in e for e in errors)


def test_structure_only_skips_freshness(cp):
    """境界を渡さない単体実行では鮮度を見ない。"""
    text = valid_checkpoint(boundary="msg-1")
    errors, _ = cp.lint(text, boundary=None)
    assert errors == []


def test_header_is_parsed(cp):
    header = cp.parse_header(valid_checkpoint(boundary="msg-3"))
    assert header["covered_through"] == "msg-3"
    assert header["session"] == "abc12345"


def test_missing_header_is_not_fatal_for_structure(cp):
    text = valid_checkpoint()
    text = text[text.index("# Checkpoint") :]
    errors, _ = cp.lint(text)
    assert errors == []


# --- git の除外設定 -----------------------------------------------------


def test_ensure_ignored_adds_exclude_entry(cp, git_repo: Path):
    """.gitignore を触らずに除外へ足す。"""
    paths = cp.resolve_paths("session-x", git_repo)
    result = cp.ensure_ignored(paths)

    assert result["git"] is True
    assert result["ignored"] is True
    assert not (git_repo / ".gitignore").exists(), ".gitignore は共有ファイルなので触らない"

    rel = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    exclude = Path(rel)
    if not exclude.is_absolute():
        exclude = git_repo / exclude
    assert ".tmp/" in exclude.read_text(encoding="utf-8")

    for key in ("checkpoint", "prev", "state"):
        done = subprocess.run(
            ["git", "check-ignore", "-q", paths[key]],
            cwd=git_repo,
            check=False,
        )
        assert done.returncode == 0, f"{key} が無視されていない"


def test_ensure_ignored_is_idempotent(cp, git_repo: Path):
    paths = cp.resolve_paths("session-x", git_repo)
    cp.ensure_ignored(paths)
    second = cp.ensure_ignored(paths)
    assert second["updated"] is False


def test_ensure_ignored_skips_writing_when_already_ignored(cp, git_repo: Path):
    """★利用者のグローバル除外が `.tmp/` を持つ環境を再現する。

    この場合 `ensure_ignored` は何も書かない。目的は「無視されている」ことで
    あって、除外ファイルへ書くこと自体ではないため。
    """
    excludes = git_repo / "user-excludes"
    excludes.write_text(f"{cp.TMP_DIRNAME}/\n", encoding="utf-8")
    subprocess.run(
        ["git", "config", "core.excludesFile", str(excludes)], cwd=git_repo, check=True
    )

    paths = cp.resolve_paths("session-x", git_repo)
    result = cp.ensure_ignored(paths)

    assert result["ignored"] is True
    assert result["updated"] is False, "既に無視されているなら書かない"


def test_ensure_ignored_outside_git_is_not_an_error(cp, tmp_path: Path, monkeypatch):
    """git の外でも失敗にしない（読み取り専用の作業を止めないため）。"""
    monkeypatch.setattr(cp, "_run_git", lambda *a, **k: None)
    paths = cp.resolve_paths("session-x", tmp_path)
    result = cp.ensure_ignored(paths)
    assert result["git"] is False
    assert result["ignored"] is True


# --- CLI ----------------------------------------------------------------


def run_cli(args: list[str], stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_paths_emits_json(tmp_path: Path):
    done = run_cli(["paths", "--session", "session-x", "--cwd", str(tmp_path)])
    assert done.returncode == 0
    payload = json.loads(done.stdout)
    assert payload["checkpoint"].endswith(".md")
    assert payload["state"].endswith(".state.json")


def test_cli_lint_returns_failure_for_broken_file(tmp_path: Path):
    target = tmp_path / "checkpoint.md"
    target.write_text("# Checkpoint\n\n本文だけ\n", encoding="utf-8")
    done = run_cli(["lint", str(target), "--structure"])
    assert done.returncode == 1
    assert "error:" in done.stderr


def test_cli_lint_missing_file_is_failure_not_crash(tmp_path: Path):
    done = run_cli(["lint", str(tmp_path / "nope.md"), "--structure"])
    assert done.returncode == 1


def test_cli_write_keeps_previous_generation(tmp_path: Path):
    target = tmp_path / "checkpoint.md"
    prev = tmp_path / "checkpoint.prev.md"

    run_cli(["write", str(target)], stdin="第 1 世代")
    run_cli(["write", str(target), "--keep-prev", str(prev)], stdin="第 2 世代")

    assert target.read_text(encoding="utf-8") == "第 2 世代"
    assert prev.read_text(encoding="utf-8") == "第 1 世代"


# ---------------------------------------------------------------------------
# snapshot (checkpoint-plugin が圧縮の直前に呼ぶ)
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "a.txt").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True
    )
    return root


def test_snapshot_creates_a_skeleton_with_machine_facts(tmp_path: Path):
    """圧縮前にスキルが走らなかった場合の保険。骨格 + 機械節を作る。"""
    root = _repo(tmp_path)
    done = run_cli(["snapshot", "--session", "ses_abc12345", "--cwd", str(root)])
    assert done.returncode == 0

    result = json.loads(done.stdout)
    assert result["ok"] is True and result["created"] is True

    text = Path(result["path"]).read_text(encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert f"- head: {head}" in text
    assert "## Snapshot" in text
    # 骨格の 6 節が揃っていること (lint --structure が通る形)。
    for heading in ("Goal", "Constraints", "State", "Evidence", "Next", "Refs"):
        assert f"## {heading}" in text


def test_snapshot_never_touches_the_written_content(tmp_path: Path):
    """★意味内容を上書きしないこと。

    機械節だけを差し替える。``updated_at`` も動かさない。ここを動かすと
    古い内容が「新鮮」に見えてしまう。
    """
    root = _repo(tmp_path)
    run_cli(["snapshot", "--session", "ses_abc12345", "--cwd", str(root)])
    paths = json.loads(
        run_cli(["paths", "--session", "ses_abc12345", "--cwd", str(root)]).stdout
    )
    target = Path(paths["checkpoint"])

    body = valid_checkpoint()
    target.write_text(body, encoding="utf-8")
    run_cli(["snapshot", "--session", "ses_abc12345", "--cwd", str(root)])

    after = target.read_text(encoding="utf-8")
    kept, _, _ = after.partition("<!-- machine:")
    assert kept.strip() == body.partition("<!-- machine:")[0].strip()


def test_snapshot_is_quiet_when_it_cannot_work(tmp_path: Path):
    """★失敗しても 0 で返すこと。圧縮の直前に走るので止めてはいけない。"""
    done = run_cli(["snapshot", "--session", "!!!", "--cwd", str(tmp_path)])
    assert done.returncode == 0
    assert json.loads(done.stdout)["ok"] is False


def test_the_pre_move_skill_is_removed_on_apply():
    """★移動前の ~/.claude/skills/checkpoint を配備先から消すこと。

    chezmoi は source から消えただけのファイルを削除しない。残すと
    OpenCode が**古い方を読む**（実測: SKILL.md の CLI パスが .claude を
    指し、snapshot サブコマンドが無い版が読み込まれた）。

    see docs/change/closed/0001-compaction-context-handover.md 「方針転換」
    """
    lines = [
        line.strip()
        for line in (ROOT / "home" / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
    ]
    assert ".claude/skills/checkpoint" in lines
    # source 側にも復活していないこと (同名があると apply が inconsistent で落ちる)
    assert not (ROOT / "home/dot_claude/skills/checkpoint").exists()


# ---------------------------------------------------------------------------
# sdd-docs への分離 (A1 と A2/B)
# ---------------------------------------------------------------------------

SKILLS = ROOT / "home/dot_config/opencode/skills"
# sdd-docs は OpenCode に依存しないので ~/.claude/skills 側に置く。
# そこは OpenCode がネイティブに監視し、~/.copilot/skills も張られている。
SDD_DOCS = ROOT / "home/dot_claude/skills/sdd-docs"
MOVED_REFERENCES = ("adr-template.md", "change-template.md", "research-template.md")


def test_the_documentation_procedure_lives_in_sdd_docs():
    """★A2 / B は sdd-docs skill が持つ。checkpoint は A1 だけ。

    分けたのは description が 2 つの仕事を名乗っていたため。あわせて plugin が
    A1 を自動化し、「先に保存」の順序を 1 ファイルで担保する必要が薄れた。

    see docs/spec/checkpoint.md 「スキルを A1 と A2/B に分けた」
    """
    assert (SDD_DOCS / "SKILL.md").exists()
    # 手順の実体が checkpoint 側へ戻っていないこと
    assert not (SKILLS / "checkpoint/references/procedure.md").exists()


def test_sdd_docs_does_not_depend_on_opencode():
    """★置き場は OpenCode への結合で決まる。

    checkpoint は plugin が絶対パスで読むので OpenCode 専用。sdd-docs は
    markdown と lint_docs.py だけなので、3 CLI に届く ~/.claude/skills へ置く。
    OpenCode 側へ戻すと、`skills` 設定という回避策に依存することになる。
    """
    assert not (SKILLS / "sdd-docs").exists()
    text = (SDD_DOCS / "SKILL.md").read_text(encoding="utf-8")
    for opencode_only in ("ctx.storage", "session.hook", "checkpoint.py"):
        assert opencode_only not in text


def test_the_templates_moved_to_sdd_docs():
    """★雛形は使う側 (sdd-docs) に置く。両方に置くと必ずずれる。"""
    for name in MOVED_REFERENCES:
        assert (SDD_DOCS / "references" / name).exists()
        assert not (SKILLS / "checkpoint/references" / name).exists()
    # checkpoint が使う雛形だけが残ること
    assert (SKILLS / "checkpoint/references/checkpoint-template.md").exists()


def test_the_checkpoint_skill_no_longer_claims_documentation():
    """★description が 2 つの仕事を名乗るとルーティングが濁る。

    「ADR を作って」で checkpoint が選ばれると、A1 の手順ごと読み込まれる。
    ADR に触れること自体は禁じない。sdd-docs へ誘導する否定文は有用なので、
    **自分の仕事として名乗る表現**と、手順の実体が戻ることだけを落とす。
    """
    text = (SKILLS / "checkpoint/SKILL.md").read_text(encoding="utf-8")
    description = next(line for line in text.splitlines() if line.startswith("description:"))
    assert "作成・更新も行う" not in description
    assert "sdd-docs" in description
    # 手順の実体が本体へ戻っていないこと (references は遅延読み込みだが本体は毎回読まれる)
    assert "## ADR の作成・更新" not in text


def test_the_moved_references_are_removed_on_apply():
    """★配備済みの旧パスを消すこと。残すと古い雛形が読まれる。

    references/ は checkpoint-template.md が残るのでディレクトリごとは消せない。
    移した 4 ファイルを個別に並べる。
    """
    lines = [
        line.strip()
        for line in (ROOT / "home" / ".chezmoiremove").read_text(encoding="utf-8").splitlines()
    ]
    base = ".config/opencode/skills/checkpoint/references"
    for name in (*MOVED_REFERENCES, "procedure.md"):
        assert f"{base}/{name}" in lines
    # ディレクトリごと消すと checkpoint-template.md まで巻き込む
    assert base not in lines
