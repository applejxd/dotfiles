"""自由区・raw finish のプレビュー・/board への pi.json の配線 (S3b)。実 git の一時リポジトリで確かめる。

自由区の接頭辞は、**主 worktree (git の common dir) の HEAD** の pi.json だけから読む。
feature 自身の HEAD の pi.json (エージェントが書ける) は信じない。fixture には架空の名前だけを使う。
see docs/change/0057-per-project-integrate.md
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_harness import (
    FIXTURES,
    bash_call,
    env,  # noqa: F401  (S7 の試験が使う fixture)
    run_pi,
)
from test_pi_judge_ts import _node

FZ = ROOT / "test" / "agents" / "pi" / "freezone_driver.mjs"
GATE = ROOT / "test" / "agents" / "pi" / "integration_gate_driver.mjs"
BOARD = ROOT / "test" / "agents" / "pi" / "board_collect_driver.mjs"
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
REL = ".agents/config/pi.json"
SECRET = "SECRET-TOKEN-XYZ"
PROTECTED = ["main", "master", "develop", "production", "release/*", "hotfix/*"]
NOT_FEATURE = "feature/ ブランチではない"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *IDENT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def _node_run(script: Path, payload: dict) -> dict:
    out = subprocess.run(
        [_node(), str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _classify(cwd: Path, **extra) -> dict:
    return _node_run(FZ, {"cwd": str(cwd), **extra})


def _cfg(**integrate) -> str:
    return json.dumps({"integrate": integrate})


def _commit_cfg(repo: Path, text: str) -> None:
    p = repo / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", REL)
    _git(repo, "commit", "-q", "-m", "cfg")


@pytest.fixture
def main(tmp_path: Path) -> Path:
    path = tmp_path / "main"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "commit", "-q", "--allow-empty", "-m", "init")
    return path


def _linked(repo: Path, branch: str, name: str | None = None) -> Path:
    wt = repo.parent / (name or branch.replace("/", "_"))
    _git(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    return wt


# --- 1. 変えない (pi.json なし) -------------------------------------------------------


def test_without_pi_json_nothing_changes(main: Path):
    ok = _classify(_linked(main, "feature/x"))
    assert ok["free"] is True and ok["reason"] == "feature の linked worktree"
    assert "profile" not in ok
    bad = _classify(_linked(main, "bugfix/x"))
    assert bad["free"] is False and bad["reason"] == NOT_FEATURE
    assert _classify(main)["free"] is False
    wt = _linked(main, "feature/d")
    _git(wt, "checkout", "-q", "--detach")
    assert _classify(wt)["reason"] == "detached HEAD"


# --- 2. 主 worktree の設定を使う ------------------------------------------------------


def test_the_main_worktree_config_replaces_the_free_zone_prefix(main: Path):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    t = _classify(_linked(main, "task/x"))
    assert t["free"] is True, t
    assert t["profile"]["overridden"] is True
    f = _classify(_linked(main, "feature/x"))
    assert f["free"] is False
    assert "task/" in f["reason"] and "接頭辞" in f["reason"], f


def test_the_prefix_match_ignores_case(main: Path):
    """保護の判定 (isProtectedRef) と同じ流儀: 接頭辞の大文字小文字は区別しない。"""
    _commit_cfg(main, _cfg(free_zone_prefixes=["Task/"]))
    for branch in ("task/x", "Task/y"):
        t = _classify(_linked(main, branch))
        assert t["free"] is True, (branch, t)


def test_a_protected_branch_is_never_free_even_when_the_prefix_matches(main: Path):
    # 接頭辞の交差は検査で落ちる (設定全体が既定へ)。保護 ref 自体は常に自由区でない
    _commit_cfg(main, _cfg(free_zone_prefixes=["release/"]))
    wt = _linked(main, "release/1.0")
    r = _classify(wt)
    assert r["free"] is False
    assert r["profile"]["overridden"] is False
    assert [d["code"] for d in r["profile"]["diagnostics"]] == ["prefix_overlaps_protected"]
    assert _classify(_linked(main, "feature/x"))["free"] is True  # 既定のまま


def test_protection_is_still_checked_for_an_allowed_prefix(main: Path):
    # 保護が後から広がる (引数) と、接頭辞に合っても自由区でない
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    wt = _linked(main, "task/x")
    assert _classify(wt)["free"] is True
    r = _classify(wt, protected=["task/*"])
    assert r["free"] is False


# --- 3. feature 自身の設定は無視する (最重要) -----------------------------------------


def test_the_feature_own_head_config_is_ignored(main: Path):
    wt = _linked(main, "wip/x")
    _commit_cfg(wt, _cfg(free_zone_prefixes=["wip/"]))
    # feature 自身の HEAD には blob がある (実 git で確かめる)
    assert "pi.json" in _git(wt, "ls-tree", "-r", "--name-only", "HEAD")
    r = _classify(wt)
    assert r["free"] is False, r
    assert "profile" not in r or r["profile"]["overridden"] is False


def test_the_feature_cannot_widen_even_when_main_has_a_config(main: Path):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    wt = _linked(main, "wip/x")
    _commit_cfg(wt, _cfg(free_zone_prefixes=["wip/"]))
    assert _classify(wt)["free"] is False


def test_an_old_feature_without_the_file_follows_the_main_config(main: Path):
    wt_old = _linked(main, "task/old")  # pi.json を持たない古いブランチ
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    assert "pi.json" not in _git(wt_old, "ls-tree", "-r", "--name-only", "HEAD")
    assert _classify(wt_old)["free"] is True


def test_the_feature_cannot_narrow_the_main_config_by_its_own_file(main: Path):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    wt = _linked(main, "task/x")
    _commit_cfg(wt, "{}")  # 自分で空に
    assert _classify(wt)["free"] is True


# --- 5. 無効な設定 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"integrate": {"free_zone_prefixes": ["task/"]',  # 壊れた JSON
        _cfg(free_zone_prefixes=["task/"], bogus=1),
        json.dumps({"protected_refs": ["x"], "integrate": {"free_zone_prefixes": ["task/"]}}),
        _cfg(free_zone_prefixes=["task/"], target="nope"),
    ],
)
def test_an_invalid_main_config_falls_back_to_the_default(main: Path, text: str):
    _commit_cfg(main, text)
    assert _classify(_linked(main, "feature/x"))["free"] is True
    r = _classify(_linked(main, "task/x"))
    assert r["free"] is False
    assert r["profile"]["diagnostics"], r


def test_diagnostics_never_carry_the_input_body(main: Path):
    _commit_cfg(main, '{"integrate": {"' + SECRET + '": 1, "free_zone_prefixes": "' + SECRET + '"')
    r = _classify(_linked(main, "task/x"))
    assert SECRET not in json.dumps(r)
    _commit_cfg(main, json.dumps({SECRET: 1, "integrate": {"free_zone_prefixes": [SECRET]}}))
    r = _classify(_linked(main, "task/y"))
    assert r["free"] is False and SECRET not in json.dumps(r)


def test_a_symlinked_main_config_is_invalid(main: Path):
    (main / "real.json").write_text(_cfg(free_zone_prefixes=["task/"]), encoding="utf-8")
    (main / ".agents" / "config").mkdir(parents=True)
    try:
        (main / REL).symlink_to("../../real.json")
    except OSError:
        pytest.skip("symlink を作れない")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "link")
    r = _classify(_linked(main, "task/x"))
    assert r["free"] is False
    assert r["profile"]["diagnostics"][0]["code"] == "not_regular_file"
    assert _classify(_linked(main, "feature/x"))["free"] is True


# --- 6. 未コミット・10. キャッシュ -----------------------------------------------------


def test_an_uncommitted_edit_is_ignored(main: Path):
    wt = _linked(main, "task/x")
    (main / ".agents" / "config").mkdir(parents=True)
    (main / REL).write_text(_cfg(free_zone_prefixes=["task/"]), encoding="utf-8")
    assert _classify(wt)["free"] is False
    _git(main, "add", REL)
    assert _classify(wt)["free"] is False  # ステージだけでも効かない
    _git(main, "commit", "-q", "-m", "cfg")
    assert _classify(wt)["free"] is True


def test_a_change_of_the_main_head_changes_the_next_decision_within_one_process(main: Path):
    wt = _linked(main, "task/x")
    cfg = [
        json.dumps({"integrate": {"free_zone_prefixes": ["task/"]}}),
        "{}",
        _cfg(free_zone_prefixes=["feature/"]),
    ]
    out = _node_run(
        FZ,
        {
            "fn": "seq",
            "cwd": str(wt),
            "steps": [
                {"classify": True},
                {"write": [str(main / REL), cfg[0]]},
                {"git": ["-C", str(main), "add", REL]},
                {"git": ["-C", str(main), "commit", "-q", "-m", "a"]},
                {"classify": True},
                {"write": [str(main / REL), cfg[2]]},
                {"git": ["-C", str(main), "add", REL]},
                {"git": ["-C", str(main), "commit", "-q", "-m", "b"]},
                {"classify": True},
            ],
        },
    )
    assert [r["free"] for r in out] == [False, True, False]


def test_a_forged_worktree_admin_dir_outside_the_common_dir_is_not_free(main: Path, tmp_path: Path):
    """本物の linked worktree の管理ディレクトリは <common dir>/worktrees/<id>。

    .git ファイルを書き換えて、別の場所の管理ディレクトリ (commondir だけ本物) を指す偽の worktree は、自由区にしない。
    """
    wt = _linked(main, "feature/x")
    assert _classify(wt)["free"] is True
    admin = Path(_git(wt, "rev-parse", "--absolute-git-dir").strip())
    common = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    forged = tmp_path / "forged-admin"
    shutil.copytree(admin, forged)
    (forged / "commondir").write_text(f"{common}\n", encoding="utf-8")
    (wt / ".git").write_text(f"gitdir: {forged}\n", encoding="utf-8")
    r = _classify(wt)
    assert r["free"] is False, r
    assert "管理ディレクトリ" in r["reason"], r


def test_a_detached_main_worktree_with_a_config_is_not_a_trusted_source(main: Path):
    """設定がある主 HEAD が detached なら、設定元として信じない (自由区にしない)。"""
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    _git(main, "checkout", "-q", "--detach")
    r = _classify(_linked(main, "task/x"))
    assert r["free"] is False and "detached" in r["reason"], r
    r = _classify(_linked(main, "feature/x"))
    assert r["free"] is False and "detached" in r["reason"], r


def test_a_detached_main_worktree_without_a_config_is_not_free(main: Path):
    """C2 の例外 (fail closed): 設定が無くても、主 HEAD が detached なら自由区にしない。

    以前は「設定が無い = 既定」として自由区だった。しかしそれだと、主 HEAD を切り替えて設定を隠す偽装と区別できない。
    確認が増える側の変更 (設定が無いリポジトリでも、主 worktree は保護ブランチ上にある前提)。
    """
    _git(main, "checkout", "-q", "--detach")
    r = _classify(_linked(main, "feature/x"))
    assert r["free"] is False and "detached" in r["reason"], r


@pytest.mark.parametrize(("branch", "free"), [("main", True), ("develop", True), ("topic", False)])
def test_the_main_branch_must_be_protected_to_be_a_config_source(
    main: Path, branch: str, free: bool
):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    if branch != "main":
        _git(main, "checkout", "-q", "-b", branch)
    r = _classify(_linked(main, "task/x"), protected=PROTECTED)
    assert r["free"] is free, r
    if not free:
        assert "保護ブランチではない" in r["reason"] and "topic" not in r["reason"], r


def test_a_non_protected_main_branch_without_a_config_is_not_free(main: Path):
    """C2 の例外 (fail closed): 設定が無くても、主 HEAD が非保護ブランチなら自由区にしない。"""
    _git(main, "checkout", "-q", "-b", "topic")
    r = _classify(_linked(main, "feature/x"), protected=PROTECTED)
    assert r["free"] is False and "保護ブランチではない" in r["reason"], r


@pytest.mark.parametrize("branch", ["main", "develop", "production"])
def test_a_protected_main_branch_without_a_config_keeps_the_default(main: Path, branch: str):
    if branch != "main":
        _git(main, "checkout", "-q", "-b", branch)
    assert _classify(_linked(main, "feature/x"), protected=PROTECTED)["free"] is True


def test_hiding_the_narrowing_config_by_switching_the_main_head_does_not_restore_the_default(
    main: Path,
):
    """主設定が feature/ を除外 → 主 HEAD を設定の無い非保護ブランチへ切り替えても、既定の feature/ は復活しない。"""
    _git(main, "branch", "topic/old")  # 設定の無いコミット
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    wt = _linked(main, "feature/x")
    assert _classify(wt, protected=PROTECTED)["free"] is False
    _git(main, "symbolic-ref", "HEAD", "refs/heads/topic/old")  # 主 worktree の HEAD の切り替え
    assert REL not in _git(main, "ls-tree", "-r", "--name-only", "HEAD")  # 切り替えは効いている
    r = _classify(wt, protected=PROTECTED)
    assert r["free"] is False, r


def test_hiding_the_narrowing_config_by_detaching_the_main_head_does_not_restore_the_default(
    main: Path,
):
    old = _git(main, "rev-parse", "HEAD").strip()  # 設定の無いコミット
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    wt = _linked(main, "feature/x")
    _git(wt, "update-ref", "--no-deref", "main-worktree/HEAD", old)
    assert REL not in _git(main, "ls-tree", "-r", "--name-only", "HEAD")
    r = _classify(wt, protected=PROTECTED)
    assert r["free"] is False, r


# --- 3b. 設定元 (主 HEAD) の偽装 (E2・E3) と読み取りの失敗 ---------------------------------


def _wide_commit(wt: Path) -> str:
    _commit_cfg(wt, _cfg(free_zone_prefixes=["wip/"]))
    return _git(wt, "rev-parse", "HEAD").strip()


def test_e2_forging_the_main_head_via_main_worktree_head_ref_does_not_widen(main: Path):
    wt = _linked(main, "wip/x")
    wide = _wide_commit(wt)
    _git(wt, "update-ref", "--no-deref", "main-worktree/HEAD", wide)
    # 偽装は効いている (主 worktree の HEAD が detached で、広い設定のコミットを指す)
    assert _git(main, "rev-parse", "HEAD").strip() == wide
    r = _classify(wt)
    assert r["free"] is False, r


def test_e3_replacing_the_main_head_commit_does_not_widen(main: Path):
    wt = _linked(main, "wip/x")
    wide = _wide_commit(wt)
    head = _git(main, "rev-parse", "HEAD").strip()
    _git(wt, "replace", head, wide)
    assert REL in _git(
        main, "ls-tree", "-r", "--name-only", "HEAD"
    )  # 素の git では置換が効いている
    assert _classify(wt)["free"] is False


def _loose_object(repo: Path, oid: str) -> Path:
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    p = common / "objects" / oid[:2] / oid[2:]
    assert p.exists(), p
    return p


def test_a_narrowing_main_config_that_cannot_be_read_does_not_fall_back_to_the_default(main: Path):
    wt = _linked(main, "feature/x")
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    assert _classify(wt)["free"] is False  # 狭まっている (読めている間)
    blob = _git(main, "rev-parse", f"HEAD:{REL}").strip()
    _loose_object(main, blob).unlink()
    r = _classify(wt)
    assert r["free"] is False and "設定を読めない" in r["reason"], r


def test_a_main_head_commit_that_cannot_be_read_is_not_free(main: Path):
    wt = _linked(main, "feature/x")
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    _loose_object(main, _git(main, "rev-parse", "HEAD").strip()).unlink()
    r = _classify(wt)
    assert r["free"] is False and "設定を読めない" in r["reason"], r


def test_a_repo_without_a_config_is_still_free_after_the_read_failure_cases(main: Path):
    assert _classify(_linked(main, "feature/x"))["free"] is True


def test_the_profile_note_has_diagnostic_codes_only(main: Path):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"], some_unknown_key=1))
    r = _classify(_linked(main, "task/x"))
    diags = r["profile"]["diagnostics"]
    assert diags and all(list(d) == ["code"] for d in diags), r
    assert "some_unknown_key" not in json.dumps(r)


# --- 7. 統合ゲート -------------------------------------------------------------------


def _gate(cwd: Path, command: str) -> dict:
    d = {"decision": "allow", "reason": "ok", "source": "rule"}
    return _node_run(GATE, {"cases": [{"d": d, "input": {"command": command}, "cwd": str(cwd)}]})[0]


def test_the_gate_uses_the_same_free_zone_decision(main: Path):
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    cmd = "git merge origin/x"  # head の統合 (自由区の外なら必須確認)
    assert _gate(_linked(main, "task/x"), cmd)["decision"] == "allow"
    ask = _gate(_linked(main, "feature/x"), cmd)
    assert ask["decision"] == "ask" and ask.get("mustConfirm") is True


def test_the_gate_ignores_the_feature_own_config(main: Path):
    wt = _linked(main, "wip/x")
    _commit_cfg(wt, _cfg(free_zone_prefixes=["wip/"]))
    ask = _gate(wt, "git merge origin/x")
    assert ask["decision"] == "ask" and ask.get("mustConfirm") is True


# --- 8. raw finish のプレビュー ------------------------------------------------------


def _preview(cwd: Path, **extra) -> dict:
    return _node_run(
        FZ, {"fn": "preview", "cwd": str(cwd), "protected": PROTECTED, "target": "develop", **extra}
    )


def test_preview_is_unchanged_without_a_config_or_with_free_zone_only(main: Path):
    assert _preview(main)["blocked"] is None
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    assert _preview(main)["blocked"] is None


def test_preview_is_blocked_when_target_or_source_prefixes_change(main: Path):
    _commit_cfg(main, _cfg(target="production"))
    r = _preview(main)
    assert r["blocked"] and "pi.json" in r["blocked"], r
    _git(main, "rm", "-q", REL)
    _git(main, "commit", "-q", "-m", "rm")
    assert _preview(main)["blocked"] is None
    _commit_cfg(main, _cfg(source_prefixes=["task/"]))
    assert _preview(main)["blocked"]


def test_preview_is_blocked_when_only_the_feature_head_overrides(main: Path):
    """cwd (feature) の HEAD だけが設定を変えているときも止める (主 worktree 側だけでは見落とす)。"""
    wt = _linked(main, "feature/x")
    assert _preview(wt)["blocked"] is None
    _commit_cfg(wt, _cfg(source_prefixes=["task/"]))
    r = _preview(wt)
    assert r["blocked"] and "pi.json" in r["blocked"], r


def test_preview_with_an_invalid_config_is_unchanged(main: Path):
    _commit_cfg(main, _cfg(source_prefixes=["task/"], bogus=1))
    assert _preview(main)["blocked"] is None


def test_preview_target_equal_to_the_default_is_not_a_change(main: Path):
    _commit_cfg(main, _cfg(target="develop"))
    assert _preview(main)["blocked"] is None


@pytest.mark.parametrize("feature_side", ["none", "deleted", "default", "invalid"])
def test_preview_also_reads_the_main_worktree_config(main: Path, feature_side: str):
    """feature (cwd) 側で設定を消す・既定にすると、主 worktree の設定があるのにプレビューが解除されてはいけない。"""
    wt = _linked(main, "feature/x")
    _commit_cfg(main, _cfg(target="production"))
    if feature_side == "deleted":
        _commit_cfg(wt, _cfg(target="production"))
        _git(wt, "rm", "-q", REL)
        _git(wt, "commit", "-q", "-m", "rm")
    elif feature_side == "default":
        _commit_cfg(wt, _cfg())
    elif feature_side == "invalid":
        _commit_cfg(wt, "{")
    r = _preview(wt)
    assert r["blocked"] and "pi.json" in r["blocked"], r


def test_preview_is_blocked_when_the_main_config_cannot_be_read(main: Path):
    wt = _linked(main, "feature/x")
    _commit_cfg(main, _cfg(free_zone_prefixes=["task/"]))
    assert _preview(wt)["blocked"] is None
    blob = _git(main, "rev-parse", f"HEAD:{REL}").strip()
    _loose_object(main, blob).unlink()
    assert _preview(wt)["blocked"]


def test_preview_in_a_linked_worktree_without_any_config_is_unchanged(main: Path):
    assert _preview(_linked(main, "feature/x"))["blocked"] is None


# --- 9. /board -----------------------------------------------------------------------


def _board(cwd: Path, defaults: bool = True, target: str = "develop") -> dict:
    p: dict = {"op": "collect", "cwd": str(cwd), "now": 1_000_000_000_000}
    if defaults:
        p["profileDefaults"] = {
            "protectedRefs": PROTECTED,
            "target": target,
            "sourcePrefixes": ["feature/", "bugfix/"],
            "freeZonePrefixes": ["feature/"],
        }
    out = subprocess.run(
        [_node(), str(BOARD), json.dumps(p)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def test_board_without_a_config_is_unchanged(main: Path):
    _linked(main, "feature/x")
    _linked(main, "bugfix/y")
    with_defaults, without = _board(main), _board(main, defaults=False)
    assert with_defaults["lines"] == without["lines"]
    assert len(with_defaults["input"]["worktreeStates"]) == 2
    assert not any("pi.json" in line for line in with_defaults["lines"])


def test_board_uses_the_project_source_prefixes(main: Path):
    _commit_cfg(main, _cfg(source_prefixes=["task/"]))
    t, f = _linked(main, "task/x"), _linked(main, "feature/x")
    r = _board(main)
    states = r["input"]["worktreeStates"]
    assert str(t) in states and str(f) not in states, states
    assert any("feature x" in line for line in r["lines"])
    assert any("他 feature/x" in line for line in r["lines"])
    assert sum("pi.json" in line for line in r["lines"]) == 1


def test_board_compares_against_the_effective_target(main: Path):
    """pi.json の target (保護に入っている production) に対する ahead/behind を出す (develop ではない)。"""
    _commit_cfg(main, _cfg(target="production"))
    _git(main, "branch", "develop")
    _git(main, "checkout", "-q", "-b", "production")
    _git(main, "commit", "-q", "--allow-empty", "-m", "p1")
    _git(main, "commit", "-q", "--allow-empty", "-m", "p2")
    _git(main, "checkout", "-q", "main")
    wt = _linked(main, "feature/x")
    _git(wt, "commit", "-q", "--allow-empty", "-m", "f1")
    st = _board(main)["input"]["worktreeStates"][str(wt)]
    assert (st["behind"], st["ahead"]) == (2, 1), st  # develop (= main) なら (0, 1)
    _git(main, "rm", "-q", REL)
    _git(main, "commit", "-q", "-m", "rm")
    st = _board(main)["input"]["worktreeStates"][str(wt)]
    assert (st["behind"], st["ahead"]) == (0, 1), st  # 設定が無いときは develop との差


@pytest.mark.parametrize("config", [None, "{"])
def test_board_compares_against_the_global_target_when_the_config_is_missing_or_invalid(
    main: Path, config: str | None
):
    """設定が無い・無効のときも、比較先は profileDefaults の全体の target (production)。develop に戻らない。"""
    if config is not None:
        _commit_cfg(main, config)
    _git(main, "branch", "develop")
    _git(main, "checkout", "-q", "-b", "production")
    _git(main, "commit", "-q", "--allow-empty", "-m", "p1")
    _git(main, "commit", "-q", "--allow-empty", "-m", "p2")
    _git(main, "checkout", "-q", "main")
    wt = _linked(main, "feature/x")
    _git(wt, "commit", "-q", "--allow-empty", "-m", "f1")
    st = _board(main, target="production")["input"]["worktreeStates"][str(wt)]
    assert (st["behind"], st["ahead"]) == (2, 1), st
    st = _board(main)["input"]["worktreeStates"][str(wt)]
    assert (st["behind"], st["ahead"]) == (0, 1), st  # 全体の target が develop なら develop との差


def test_board_shows_nothing_for_a_config_equal_to_the_default(main: Path):
    _commit_cfg(main, _cfg())  # {"integrate": {}} は有効で、既定と同じ
    _linked(main, "feature/x")
    r = _board(main)
    assert not any("pi.json" in line for line in r["lines"]), r["lines"]
    assert len(r["input"]["worktreeStates"]) == 1


def test_board_shows_only_a_diagnostic_code_for_an_invalid_config(main: Path):
    _commit_cfg(main, json.dumps({SECRET: 1, "integrate": {"source_prefixes": ["task/"]}}))
    _linked(main, "feature/x")
    r = _board(main)
    lines = [line for line in r["lines"] if "pi.json" in line]
    assert len(lines) == 1 and "unknown_key" in lines[0], lines
    assert SECRET not in json.dumps(r)
    assert len(r["input"]["worktreeStates"]) == 1  # 既定のまま (feature/ は出る)


# --- 11. S7: execute 直前の統合ゲートの再判定 (index.ts) -------------------------------


def _s7_setup(penv: dict, free_zone_prefix: str) -> tuple[Path, Path]:
    """主 repo (main) に pi.json (自由区 = free_zone_prefix) をコミットし、feature/x の linked worktree を proj にする。"""
    main_repo = penv["tmp"] / "s7main"
    main_repo.mkdir()
    _git(main_repo, "init", "-q", "-b", "main")
    _git(main_repo, "commit", "-q", "--allow-empty", "-m", "init")
    _commit_cfg(main_repo, _cfg(free_zone_prefixes=[free_zone_prefix]))
    wt = penv["tmp"] / "s7wt"
    _git(main_repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    _git(main_repo, "branch", "side", "feature/x")  # feature/x の先 (fast-forward できる)
    _git(main_repo, "checkout", "-q", "side")
    _git(main_repo, "commit", "-q", "--allow-empty", "-m", "s1")
    _git(main_repo, "checkout", "-q", "main")
    # 統合ゲート (pi.confirm.integration) を有効にする
    path = penv["harness"] / "rules.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    rules["judge"]["common"].setdefault("pi", {}).setdefault("confirm", {})["integration"] = True
    path.write_text(json.dumps(rules), encoding="utf-8")
    penv["proj"] = wt
    return main_repo, wt


def _s7_effect(main_repo: Path) -> str:
    """tool_call の後 (execute の前) に、主設定を feature/ を自由区にしないものへ差し替えてコミットする。"""
    cfg = main_repo / REL
    git = f"git -c user.name=t -c user.email=t@example.com -c commit.gpgsign=false -C {main_repo}"
    body = _cfg(free_zone_prefixes=["task/"])
    return f"printf '%s' '{body}' > {cfg} && {git} add {REL} && {git} commit -q -m narrow"


@pytest.mark.skipif(shutil.which("pi") is None, reason="pi is not installed")
def test_s7_the_integration_gate_is_rechecked_just_before_execute(env):  # noqa: F811
    """tool_call では自由区で許可 → 実行前に主設定が変わる → execute で確認が必要として止まり、統合は実行されない。"""

    main_repo, wt = _s7_setup(env, "feature/")
    head = _git(wt, "rev-parse", "HEAD").strip()
    cmd = "git merge --ff-only side"
    # 対照: 副作用が無ければ、自由区として確認なしで統合が実行される
    run_pi(env, bash_call(cmd), PI_HARNESS_BYPASS="1")
    assert _git(wt, "rev-parse", "HEAD").strip() != head, (
        "対照が成り立たない (自由区の統合が実行されない)"
    )

    _git(wt, "reset", "-q", "--hard", head)
    proc = run_pi(
        env,
        bash_call(cmd),
        extra=("-e", str(FIXTURES / "side_effect.ts")),
        SIDE_EFFECT_CMD=_s7_effect(main_repo),
        PI_HARNESS_BYPASS="1",
    )
    assert "実行前の判定で止めた" in proc.stdout, (proc.stdout, proc.stderr)
    assert "narrow" in _git(main_repo, "log", "-1", "--format=%s"), (
        "副作用 (主設定の変更) が起きていない"
    )
    assert _git(wt, "rev-parse", "HEAD").strip() == head, "統合が実行された"
