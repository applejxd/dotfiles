"""harness/judge/gitflow_gate.ts と judge/call.ts の tighten の表試験 (CHG-0049)。

``test/agents/pi/gitflow_guard_driver.mjs`` に、偽の facts (git も実リポジトリも読まない) を JSON で渡して
純関数 ``gate`` / ``isGated`` / ``tighten`` を動かす。node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "gitflow_guard_driver.mjs"
GOLDEN = HERE / "golden" / "common.json"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

TOP = "/repo"
COMMON = "/repo/.git"
FEATURE_TOP = "/repo/.tmp/worktrees/x"


def run(cases: list[dict]) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def branch(ref: str) -> dict:
    return {"kind": "branch", "ref": ref}


def wt(top: str = TOP, head: dict | None = None, primary: bool = True) -> dict:
    return {
        "kind": "worktree",
        "top": top,
        "commonDir": COMMON,
        "primary": primary,
        "head": head or branch("refs/heads/develop"),
    }


def facts(owners: dict | None = None, model: str = "gitflow-lite", **kw) -> dict:
    return {
        "owners": owners if owners is not None else {TOP: wt()},
        "models": {COMMON: model},
        **kw,
    }


def edit(path: str, f: dict, tool: str = "edit", cwd: str = TOP) -> dict:
    return {"kind": "gate", "tool": tool, "input": {"path": path}, "cwd": cwd, "facts": f}


def commit(f: dict, cwd: str = TOP, action: str = "git_commit") -> dict:
    return {"kind": "gate", "tool": "action", "input": {"action": action}, "cwd": cwd, "facts": f}


def one(case: dict) -> dict:
    return run([{**case, "id": "c"}])["c"]["result"]


def kind(case: dict) -> str:
    return one(case)["kind"]


# 1. 所属


@pytest.mark.parametrize("ref", ["refs/heads/develop", "refs/heads/main"])
@pytest.mark.parametrize("tool", ["edit", "write"])
def test_edit_in_protected_primary_worktree_is_denied(ref: str, tool: str) -> None:
    """develop / main の本体の作業ツリーへの edit / write は deny し、feature の起票へ案内する。"""
    r = one(edit("/repo/src/a.py", facts({TOP: wt(head=branch(ref))}), tool))
    assert r["kind"] == "deny"
    assert "gitflow_feature_start" in r["reason"]


def test_relative_new_file_is_judged_by_its_resolved_real_path() -> None:
    """親が無い相対パス (新規ファイル) は、facts.realPath が解決した結果で判定する。"""
    f = facts({TOP: wt(), FEATURE_TOP: wt(FEATURE_TOP, branch("refs/heads/feature/x"), False)})
    f["real"] = {"/repo/lnk/new.txt": "/repo/new.txt"}
    assert kind(edit("lnk/new.txt", f)) == "deny"
    f["real"] = {"/repo/lnk/new.txt": f"{FEATURE_TOP}/new.txt"}
    assert kind(edit("lnk/new.txt", f)) == "pass"


def test_symlink_is_judged_by_its_target() -> None:
    """シンボリックリンクは、リンクの置き場ではなく、facts.realPath が返す実体の持ち主で判定する。"""
    f = facts({TOP: wt(), "/other": wt("/other", branch("refs/heads/feature/y"), False)})
    # feature 側にあるリンクが、本体 (develop) の実体を指す → deny
    f["real"] = {"/other/link": "/repo/src/a.py"}
    assert kind(edit("/other/link", f)) == "deny"
    # 本体にあるリンクが、feature の実体を指す → pass
    f["real"] = {"/repo/link": "/other/a.py"}
    assert kind(edit("/repo/link", f)) == "pass"


def test_feature_worktree_is_passed() -> None:
    """head が refs/heads/feature/x の worktree は pass。"""
    f = facts({TOP: wt(), FEATURE_TOP: wt(FEATURE_TOP, branch("refs/heads/feature/x"), False)})
    assert kind(edit(f"{FEATURE_TOP}/src/a.py", f)) == "pass"


def test_editing_a_feature_worktree_file_from_the_primary_is_passed() -> None:
    """cwd が本体 (develop) でも、編集先の持ち主が feature の worktree なら pass。"""
    f = facts({TOP: wt(), FEATURE_TOP: wt(FEATURE_TOP, branch("refs/heads/feature/x"), False)})
    assert kind(edit(f"{FEATURE_TOP}/a.py", f, cwd=TOP)) == "pass"


def test_other_branches_are_passed() -> None:
    """develop / main 以外のブランチは pass。"""
    for ref in ("refs/heads/topic", "refs/heads/release/1", "refs/heads/developer"):
        assert kind(edit("/repo/a.py", facts({TOP: wt(head=branch(ref))}))) == "pass", ref


# 2. detached / unreadable


def test_detached_primary_is_denied_but_linked_worktree_is_passed() -> None:
    """本体の detached は deny。linked worktree の detached は pass (隔離 worker の例外)。"""
    det = {"kind": "detached"}
    assert kind(edit("/repo/a.py", facts({TOP: wt(head=det)}))) == "deny"
    linked = facts({TOP: wt(), "/lw": wt("/lw", det, False)})
    assert kind(edit("/lw/a.py", linked)) == "pass"


def test_unreadable_head_needs_confirmation() -> None:
    """HEAD を読めない worktree は confirm (key を持つ)。"""
    r = one(edit("/repo/a.py", facts({TOP: wt(head={"kind": "unreadable"})})))
    assert r["kind"] == "confirm" and r["key"]


# 3. .tmp/ の例外


def test_tmp_under_a_protected_worktree_is_passed() -> None:
    """保護された worktree の <top>/.tmp/ の下は pass。"""
    assert kind(edit("/repo/.tmp/s/1/note.txt", facts())) == "pass"


def test_tmp_exception_compares_path_segments_not_string_prefix() -> None:
    """<top>/.tmpfoo/x は .tmp の下ではない。"""
    assert kind(edit("/repo/.tmpfoo/x", facts())) == "deny"


def test_tmp_exception_uses_the_resolved_path() -> None:
    """.tmp/../src/x を解決した結果が top の中 (.tmp の外) なら deny。.tmp のリンクが外を指しても deny。"""
    f = facts()
    f["real"] = {"/repo/.tmp/../src/x": "/repo/src/x", "/repo/.tmp/link": "/repo/src/y"}
    assert kind(edit("/repo/.tmp/../src/x", f)) == "deny"
    assert kind(edit("/repo/.tmp/link", f)) == "deny"


# 4. モデル


@pytest.mark.parametrize("model", ["none", "other"])
def test_non_lite_models_are_passed(model: str) -> None:
    """.gitflow が無い／gitflow-lite でない構成は pass。"""
    assert kind(edit("/repo/a.py", facts(model=model))) == "pass"


def test_unknown_model_needs_confirmation() -> None:
    """運用を読めないときは confirm (key を持つ)。gitflow-lite のときだけ deny。"""
    r = one(edit("/repo/a.py", facts(model="unknown")))
    assert r["kind"] == "confirm" and r["key"]
    assert kind(edit("/repo/a.py", facts(model="gitflow-lite"))) == "deny"


@pytest.mark.parametrize(
    ("model", "want"),
    [("gitflow-lite", "deny"), ("other", "pass"), ("none", "pass"), ("unknown", "confirm")],
)
def test_git_dir_follows_the_model(model: str, want: str) -> None:
    """.git の中は、gitflow-lite のときだけ deny。"""
    f = facts({COMMON: {"kind": "git-dir", "commonDir": COMMON}}, model=model)
    assert kind(edit("/repo/.git/config", f)) == want


# 5. owner


def test_no_repo_is_passed_and_unknown_owner_needs_confirmation() -> None:
    """git の外は pass、持ち主を読めなければ confirm。"""
    assert kind(edit("/elsewhere/a", facts({}))) == "pass"
    r = one(edit("/repo/a", facts({TOP: {"kind": "unknown", "why": "boom"}})))
    assert r["kind"] == "confirm" and r["key"]


# 6. git_commit


def test_commit_on_protected_head_is_denied() -> None:
    """保護された head で gitflow-lite の git_commit は deny。"""
    r = one(commit(facts()))
    assert r["kind"] == "deny" and "gitflow_feature_start" in r["reason"]


def test_commit_in_feature_worktree_is_passed() -> None:
    """feature worktree の git_commit は pass。"""
    f = facts({TOP: wt(), FEATURE_TOP: wt(FEATURE_TOP, branch("refs/heads/feature/x"), False)})
    assert kind(commit(f, cwd=FEATURE_TOP)) == "pass"


def test_other_actions_are_not_gated() -> None:
    """git_commit 以外の action は対象外 (git を読まず pass)。"""
    out = run(
        [
            {
                "id": "i",
                "kind": "isGated",
                "tool": "action",
                "input": {"action": "gitflow_feature_commit"},
                "facts": facts(),
            },
            {"id": "g", **commit(facts(), action="gitflow_feature_commit")},
        ]
    )
    assert out["i"]["gated"] is False
    assert out["g"]["result"] == {"kind": "pass"}


def test_commit_with_unreadable_state_is_denied_not_confirmed() -> None:
    """コミットは、状態を読めないとき confirm でなく deny。"""
    assert kind(commit(facts({TOP: {"kind": "unknown", "why": "x"}}))) == "deny"
    assert kind(commit(facts({TOP: wt(head={"kind": "unreadable"})}))) == "deny"
    assert kind(commit(facts(model="unknown"))) == "deny"


# 7. isGated


def test_is_gated_only_for_edit_write_with_string_path_and_git_commit() -> None:
    """edit / write は path が文字列のときだけ対象。read や bash は対象外で、git (facts) を一度も呼ばない。"""
    f = facts()
    cases = {
        "edit": ("edit", {"path": "a"}),
        "write": ("write", {"path": "a"}),
        "edit_no_path": ("edit", {}),
        "edit_num": ("edit", {"path": 5}),
        "edit_null": ("edit", None),
        "read": ("read", {"path": "a"}),
        "bash": ("bash", {"command": "ls"}),
        "commit": ("action", {"action": "git_commit"}),
    }
    out = run(
        [
            {"id": k, "kind": "isGated", "tool": t, "input": i, "facts": f}
            for k, (t, i) in cases.items()
        ]
    )
    assert [k for k, v in out.items() if v["gated"]] == ["edit", "write", "commit"]
    assert all(sum(v["calls"].values()) == 0 for v in out.values())
    # 対象外の gate も git を呼ばない
    g = run(
        [{"id": "r", "kind": "gate", "tool": "read", "input": {"path": "/repo/a"}, "facts": f}]
    )["r"]
    assert g["result"] == {"kind": "pass"} and sum(g["calls"].values()) == 0


# 8. 案内文


def test_guide_mentions_setup_script_only_when_action_is_not_ready() -> None:
    """固定操作を実行できない環境では、案内に scripts/gitflow-setup.sh を足す。"""
    ready = one(edit("/repo/a", facts(actionReady=True)))["reason"]
    not_ready = one(edit("/repo/a", facts(actionReady=False)))["reason"]
    assert "gitflow_feature_start" in ready and "scripts/gitflow-setup.sh" not in ready
    assert "gitflow_feature_start" in not_ready and "scripts/gitflow-setup.sh" in not_ready


def test_action_id_in_guide_exists_in_golden_actions() -> None:
    """案内が示す action id が、[[pi.actions]] 由来の actions に実在する。"""
    ids = {a["id"] for a in json.loads(GOLDEN.read_text(encoding="utf-8"))["pi"]["actions"]}
    assert "gitflow_feature_start" in ids
    reason = one(edit("/repo/a", facts()))["reason"]
    assert any(i in reason for i in ids)


# 9. tighten


BASE_ALLOW = {"decision": "allow", "reason": "ok", "source": "rule"}
BASE_ASK = {"decision": "ask", "reason": "ask", "source": "rule"}
BASE_DENY = {"decision": "deny", "reason": "no", "source": "rule"}


def tighten(base: dict, g: dict) -> dict:
    return run([{"id": "t", "kind": "tighten", "base": base, "gate": g}])["t"]


def test_tighten_keeps_base_deny() -> None:
    """base が deny なら、gate が何でも deny のまま。"""
    for g in (
        {"kind": "pass"},
        {"kind": "deny", "reason": "g"},
        {"kind": "confirm", "reason": "c", "key": "k"},
    ):
        assert tighten(BASE_DENY, g) == BASE_DENY


def test_tighten_gate_deny_wins() -> None:
    """gate が deny なら、base が allow / ask でも deny。"""
    for base in (BASE_ALLOW, BASE_ASK):
        r = tighten(base, {"kind": "deny", "reason": "g"})
        assert r["decision"] == "deny" and r["reason"] == "g"


def test_tighten_gate_confirm_becomes_must_confirm_ask() -> None:
    """gate が confirm なら ask + mustConfirm + gateKey。"""
    r = tighten(BASE_ALLOW, {"kind": "confirm", "reason": "c", "key": "k1"})
    assert r["decision"] == "ask" and r["mustConfirm"] is True and r["gateKey"] == "k1"


def test_tighten_gate_pass_keeps_base_and_never_loosens() -> None:
    """gate が pass なら base のまま。base が ask なら ask のまま (緩めない)。"""
    assert tighten(BASE_ALLOW, {"kind": "pass"}) == BASE_ALLOW
    assert tighten(BASE_ASK, {"kind": "pass"}) == BASE_ASK
