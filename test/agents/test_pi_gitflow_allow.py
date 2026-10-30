"""/gitflow-allow (利用者専用の逃がし口。CHG-0049) の表試験。

``test/agents/pi/gitflow_allow_driver.mjs`` に偽の facts を JSON で渡し、``parseAllowArgs`` /
``describeAllowance`` / ``permits`` / ``gate`` (allow つき) / ``isProtectedWorktree`` / ``headName`` を動かす。
node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "gitflow_allow_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

TOP = "/repo"
COMMON = "/repo/.git"
DEV = "refs/heads/develop"
MAIN = "refs/heads/main"
FEATURE = "refs/heads/feature/x"
NOW = 1_000_000_000
MIN = 60_000


def run(cases: list[dict]) -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps([{**c, "id": str(i)} for i, c in enumerate(cases)]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    return {"consts": out["__consts"], "results": [out[str(i)] for i in range(len(cases))]}


def one(case: dict):
    return run([case])["results"][0]


def branch(ref: str) -> dict:
    return {"kind": "branch", "ref": ref}


def wt(top: str = TOP, head: dict | None = None, primary: bool = True) -> dict:
    return {
        "kind": "worktree",
        "top": top,
        "commonDir": COMMON,
        "primary": primary,
        "head": head or branch(DEV),
    }


def allowance(
    scope: str = "all", head: str = DEV, top: str = TOP, expires: int = NOW + 5 * MIN
) -> dict:
    return {"top": top, "head": head, "scope": scope, "expires": expires}


def state(a: dict | None, now: int = NOW) -> dict:
    return {"allowance": a, "now": now}


# 1. parseAllowArgs


def parse(text: str) -> dict:
    return one({"kind": "parse", "text": text})


def test_parse_constants() -> None:
    """既定 10 分・上限 60 分。"""
    c = run([])["consts"]
    assert c == {"DEFAULT_MINUTES": 10, "MAX_MINUTES": 60}


@pytest.mark.parametrize("text", ["", "   "])
def test_parse_empty_grants_all_for_default_minutes(text: str) -> None:
    """空は grant・all・10 分。"""
    assert parse(text) == {"ok": True, "action": "grant", "scope": "all", "minutes": 10}


@pytest.mark.parametrize("scope", ["edit", "commit", "all"])
def test_parse_scope_only(scope: str) -> None:
    """範囲だけなら、時間は既定の 10 分。"""
    assert parse(scope) == {"ok": True, "action": "grant", "scope": scope, "minutes": 10}


@pytest.mark.parametrize(("text", "minutes"), [("30", 30), ("1", 1), ("60", 60)])
def test_parse_minutes_only(text: str, minutes: int) -> None:
    """数字だけは分。範囲は all。1 と 60 は境界で ok。"""
    assert parse(text) == {"ok": True, "action": "grant", "scope": "all", "minutes": minutes}


@pytest.mark.parametrize("text", ["commit 5", "5 commit", "  commit   5 "])
def test_parse_scope_and_minutes_in_any_order(text: str) -> None:
    """範囲と時間は順不同。空白の多重も許す。"""
    assert parse(text) == {"ok": True, "action": "grant", "scope": "commit", "minutes": 5}


@pytest.mark.parametrize("word", ["off", "status"])
def test_parse_off_and_status_alone(word: str) -> None:
    """off / status は単独のときだけ。"""
    assert parse(word) == {"ok": True, "action": word}


@pytest.mark.parametrize(
    "text",
    [
        "off 5",
        "5 off",
        "status edit",
        "edit off",
        "off status",
        "edit edit",
        "edit commit",
        "all edit",
        "5 10",
        "edit 5 10",
        "0",
        "61",
        "999",
        "edit 0",
        "commit 61",
        "foo",
        "-5",
        "1.5",
        "edit,commit",
        "edit 5m",
        "EDIT",
    ],
)
def test_parse_errors_mention_usage(text: str) -> None:
    """不正な組み合わせ・範囲外 (丸めず拒否)・未知の語は error で、使い方を含む。"""
    r = parse(text)
    assert r["ok"] is False
    assert "/gitflow-allow" in r["error"]


# 2. describeAllowance


def test_describe_within_expiry_shows_top_head_scope_and_minutes_left() -> None:
    """期限内は top・head・範囲の文言と、あと約 N 分 (切り上げ)。"""
    a = allowance(scope="edit", expires=NOW + 5 * MIN)
    s = one({"kind": "describe", "allowance": a, "now": NOW})
    assert TOP in s and DEV in s and "直接の編集 (edit / write)" in s and "あと約 5 分" in s


@pytest.mark.parametrize(
    ("left_ms", "minutes"),
    [(1, 1), (1000, 1), (MIN, 1), (MIN + 1, 2), (59 * MIN + 1, 60)],
)
def test_describe_rounds_minutes_up_with_minimum_one(left_ms: int, minutes: int) -> None:
    """残りは切り上げで、最小 1 分。"""
    s = one({"kind": "describe", "allowance": allowance(expires=NOW + left_ms), "now": NOW})
    assert f"あと約 {minutes} 分" in s


@pytest.mark.parametrize(
    ("scope", "text"),
    [
        ("edit", "直接の編集 (edit / write)"),
        ("commit", "コミット (guarded_action の git_commit)"),
        ("all", "直接の編集とコミット"),
    ],
)
def test_describe_scope_text(scope: str, text: str) -> None:
    """範囲ごとの文言。"""
    assert text in one({"kind": "describe", "allowance": allowance(scope=scope), "now": NOW})


@pytest.mark.parametrize("delta", [0, -1, -10 * MIN])
def test_describe_expired_is_null(delta: int) -> None:
    """期限ちょうど・過ぎていれば null。"""
    assert (
        one({"kind": "describe", "allowance": allowance(expires=NOW + delta), "now": NOW}) is None
    )


def test_describe_null_allowance_is_null() -> None:
    """allowance が null なら null。"""
    assert one({"kind": "describe", "allowance": None, "now": NOW}) is None


# 3. permits


def permits(
    a: dict | None, op: str, owner: dict | None = None, now: int = NOW, *, no_state: bool = False
):
    owner = owner or {"top": TOP, "head": branch(DEV)}
    case = {"kind": "permits", "op": op, "owner": owner}
    if not no_state:
        case["allow"] = state(a, now)
    return one(case)


@pytest.mark.parametrize(
    ("scope", "op", "want"),
    [
        ("edit", "edit", True),
        ("edit", "commit", False),
        ("commit", "commit", True),
        ("commit", "edit", False),
        ("all", "edit", True),
        ("all", "commit", True),
    ],
)
def test_permits_scope(scope: str, op: str, want: bool) -> None:
    """scope は edit が edit だけ、commit が commit だけ、all が両方。"""
    assert permits(allowance(scope=scope), op) is want


def test_permits_requires_same_top() -> None:
    """top が違えば false。"""
    assert permits(allowance(top="/other"), "edit") is False


def test_permits_requires_same_head() -> None:
    """head が違えば false (develop の許可で main は不可)。"""
    a = allowance(head=DEV)
    assert permits(a, "edit", {"top": TOP, "head": branch(MAIN)}) is False
    assert permits(a, "edit", {"top": TOP, "head": branch(DEV)}) is True


def test_permits_detached_head_matches_by_name() -> None:
    """detached は "detached" という名前で照合する。branch の許可は効かない。"""
    det = {"top": TOP, "head": {"kind": "detached"}}
    assert permits(allowance(head="detached"), "edit", det) is True
    assert permits(allowance(head=DEV), "edit", det) is False


def test_permits_expiry_boundary() -> None:
    """now が expires 以上なら false。1 ミリ秒前は true。"""
    a = allowance(expires=NOW + MIN)
    assert permits(a, "edit", now=NOW + MIN - 1) is True
    assert permits(a, "edit", now=NOW + MIN) is False
    assert permits(a, "edit", now=NOW + 2 * MIN) is False


def test_permits_without_allow_or_allowance_is_false() -> None:
    """allow 未指定・allowance が null は false。"""
    assert permits(None, "edit", no_state=True) is False
    assert permits(None, "edit") is False


# 4. gate + allow


def facts(owners: dict | None = None, model: str = "gitflow-lite") -> dict:
    return {"owners": owners if owners is not None else {TOP: wt()}, "models": {COMMON: model}}


def g_edit(f: dict, allow: dict | None, path: str = "/repo/src/a.py", tool: str = "edit") -> dict:
    c = {"kind": "gate", "tool": tool, "input": {"path": path}, "cwd": TOP, "facts": f}
    if allow is not None:
        c["allow"] = allow
    return one(c)


def g_commit(f: dict, allow: dict | None, cwd: str = TOP) -> dict:
    c = {
        "kind": "gate",
        "tool": "action",
        "input": {"action": "git_commit"},
        "cwd": cwd,
        "facts": f,
    }
    if allow is not None:
        c["allow"] = allow
    return one(c)


@pytest.mark.parametrize("tool", ["edit", "write"])
def test_gate_allow_all_passes_edit_and_write(tool: str) -> None:
    """許可 (all) があれば、develop の本体への edit / write は pass。"""
    assert g_edit(facts(), state(allowance()), tool=tool) == {"kind": "pass"}


def test_gate_allow_all_passes_git_commit() -> None:
    """許可 (all) があれば git_commit も pass。"""
    assert g_commit(facts(), state(allowance())) == {"kind": "pass"}


def test_gate_scope_edit_keeps_commit_denied() -> None:
    """scope=edit では git_commit は deny のまま。edit は pass。"""
    a = state(allowance(scope="edit"))
    assert g_commit(facts(), a)["kind"] == "deny"
    assert g_edit(facts(), a)["kind"] == "pass"


def test_gate_scope_commit_keeps_edit_denied() -> None:
    """scope=commit では edit は deny のまま。git_commit は pass。"""
    a = state(allowance(scope="commit"))
    assert g_edit(facts(), a)["kind"] == "deny"
    assert g_commit(facts(), a) == {"kind": "pass"}


def test_gate_allow_for_another_branch_does_not_apply() -> None:
    """head が feature の許可は、develop の編集・コミットを許さない。"""
    a = state(allowance(head=FEATURE))
    assert g_edit(facts(), a)["kind"] == "deny"
    assert g_commit(facts(), a)["kind"] == "deny"


def test_gate_allow_for_develop_does_not_apply_to_main() -> None:
    """develop の許可は、main の worktree には効かない。"""
    f = facts({TOP: wt(head=branch(MAIN))})
    a = state(allowance(head=DEV))
    assert g_edit(f, a)["kind"] == "deny"
    assert g_commit(f, a)["kind"] == "deny"
    assert g_edit(f, state(allowance(head=MAIN))) == {"kind": "pass"}


def test_gate_allow_for_another_top_does_not_apply() -> None:
    """別の worktree の許可は効かない。"""
    a = state(allowance(top="/other"))
    assert g_edit(facts(), a)["kind"] == "deny"
    assert g_commit(facts(), a)["kind"] == "deny"


def test_gate_expired_allow_returns_to_deny() -> None:
    """期限切れ (now が expires 以上) は deny に戻る。"""
    a = state(allowance(expires=NOW + MIN), now=NOW + MIN)
    assert g_edit(facts(), a)["kind"] == "deny"
    assert g_commit(facts(), a)["kind"] == "deny"


def test_gate_null_allowance_is_deny() -> None:
    """allowance が null なら deny。"""
    assert g_edit(facts(), state(None))["kind"] == "deny"
    assert g_commit(facts(), state(None))["kind"] == "deny"


def test_gate_allow_does_not_open_the_git_dir() -> None:
    """`.git/` の中は、許可があっても deny (lite)。"""
    f = facts({COMMON: {"kind": "git-dir", "commonDir": COMMON}})
    assert g_edit(f, state(allowance()), path="/repo/.git/config")["kind"] == "deny"


def test_gate_allow_does_not_relax_unknown_owner() -> None:
    """持ち主を読めないときは、許可があっても edit は confirm、git_commit は deny のまま。"""
    f = facts({TOP: {"kind": "unknown", "why": "boom"}})
    a = state(allowance())
    r = g_edit(f, a)
    assert r["kind"] == "confirm" and r["key"]
    assert g_commit(f, a)["kind"] == "deny"


def test_gate_allow_does_not_relax_unreadable_head() -> None:
    """HEAD を読めないときも、許可は効かない (confirm / deny のまま)。"""
    f = facts({TOP: wt(head={"kind": "unreadable"})})
    a = state(allowance(head="unreadable"))
    assert g_edit(f, a)["kind"] == "confirm"
    assert g_commit(f, a)["kind"] == "deny"


def test_gate_allow_does_not_relax_unknown_model() -> None:
    """モデルが unknown のときは、許可があっても edit は confirm、git_commit は deny のまま。"""
    f = facts(model="unknown")
    a = state(allowance())
    assert g_edit(f, a)["kind"] == "confirm"
    assert g_commit(f, a)["kind"] == "deny"


@pytest.mark.parametrize("with_state", [False, True])
def test_gate_without_allowance_matches_existing_results(with_state: bool) -> None:
    """許可が無い (未指定・null) ときの結果は従来どおり (test_pi_gitflow_guard.py と同じ)。"""
    a = state(None) if with_state else None
    assert g_edit(facts(), a)["kind"] == "deny"
    assert "gitflow_feature_start" in g_edit(facts(), a)["reason"]
    assert g_commit(facts(), a)["kind"] == "deny"
    assert g_edit(facts(model="unknown"), a)["kind"] == "confirm"
    assert g_edit(facts(model="other"), a) == {"kind": "pass"}
    assert (
        g_edit(facts({COMMON: {"kind": "git-dir", "commonDir": COMMON}}), a, path="/repo/.git/x")[
            "kind"
        ]
        == "deny"
    )
    assert g_edit(facts({TOP: {"kind": "unknown", "why": "x"}}), a)["kind"] == "confirm"
    assert g_commit(facts({TOP: {"kind": "unknown", "why": "x"}}), a)["kind"] == "deny"
    assert g_commit(facts(model="unknown"), a)["kind"] == "deny"


# 5. isProtectedWorktree / headName


def protected(owner: dict):
    return one({"kind": "protected", "owner": owner})


@pytest.mark.parametrize("ref", [DEV, MAIN])
def test_protected_primary_develop_and_main(ref: str) -> None:
    """develop・main の primary は保護の対象。"""
    assert protected(wt(head=branch(ref))) is True


def test_protected_feature_is_false() -> None:
    """feature は対象外。"""
    assert protected(wt("/repo/.tmp/worktrees/x", branch(FEATURE), False)) is False


def test_protected_detached_depends_on_primary() -> None:
    """本体の detached は対象、linked の detached は対象外。"""
    det = {"kind": "detached"}
    assert protected(wt(head=det, primary=True)) is True
    assert protected(wt("/lw", det, primary=False)) is False


def test_protected_unreadable_head_is_false() -> None:
    """HEAD を読めない worktree は、許可を出せる状態ではない。"""
    assert protected(wt(head={"kind": "unreadable"})) is False


@pytest.mark.parametrize(
    "owner",
    [
        {"kind": "git-dir", "commonDir": COMMON},
        {"kind": "no-repo"},
        {"kind": "unknown", "why": "x"},
    ],
)
def test_protected_non_worktree_owners_are_false(owner: dict) -> None:
    """git-dir・no-repo・unknown は対象外。"""
    assert protected(owner) is False


def test_head_name() -> None:
    """branch は ref、detached は "detached"、unreadable は "unreadable"。"""
    r = run(
        [
            {"kind": "headName", "head": branch(DEV)},
            {"kind": "headName", "head": {"kind": "detached"}},
            {"kind": "headName", "head": {"kind": "unreadable"}},
        ]
    )["results"]
    assert r == [DEV, "detached", "unreadable"]
