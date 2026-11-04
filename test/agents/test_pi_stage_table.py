"""bash の判定の「段の表」(``judge/verdict.ts``) の試験。
旧のカスケード (``judge/legacy_cascade.ts``。G7 で削除する oracle) と同じ出力になること。

- 所見の部分集合 (S2〜S9 の 8 段) × 6 役割 × 4 モードで、段の表と、
  旧のカスケードを所見の集合の関数として別に書いた仕様の評価器が一致する
- 段どうしの優先順位 (前の段が後の段に勝つ)、段内の順序、S6 の blind の事前集約、tools 検査・boundary・bypass の変換
- 実コマンドで、新の判定器と旧のカスケードが 6 役割 × 4 モードの全部で同じ応答になる (4 対の比較・blind・段内の順序・代表例の表)

段間の優先順位の実コマンドの試験は、役割の ``shell_deny`` にある ``git reset`` ではなく、通常の ask (``docker rm``) で行う
(explorer・committer・worker では ``git reset`` が S5 で deny になり、S6/S8 に届かない)。

see docs/spec/guard/pi-decide.md#bash-の評価順段の表
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from functools import lru_cache

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

PI = ROOT / "test" / "agents" / "pi"
GOLDEN = ROOT / "test" / "agents" / "golden"
DRIVER = PI / "verdict_driver.mjs"
ROLES = ["committer", "explorer", "implementer", "orchestrator", "reader", "worker"]
MODES = ["ask", "bypass", "boundary", "bypass+boundary"]
STAGES = ["S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]


def _run(*args, timeout=600):
    proc = subprocess.run(
        [_node(), "--experimental-strip-types", "--no-warnings", str(DRIVER), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    return json.loads(proc.stdout)


def _run_with_json(kind, payload):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return _run(kind, path)


# ─── 所見の部分集合の総当たり ─────────────────────────────────────────────────────────────────


def test_abstract_all_subsets_match_the_legacy_cascade_spec():
    out = _run("abstract")
    assert out["mismatches"] == [], out["mismatches"][:3]
    # 8 段の部分集合 (S6 は plain と blind) × 許可の有無 × 6 役割 × 4 モード
    assert out["total"] == (2**8 + 2**7) * 2 * 6 * 4
    assert out["total"] > 12000


# ─── 段の表の単体 (judgeBash に任意の所見を通す)。事例は import 時に全部登録し、1 回の node 起動で通す ──────────────

_UNIT: dict[str, dict] = {}


def _finding(stage, idx=0, **kw):
    base = {"stage": stage, "idx": idx, "reason": f"理由 {stage}/{idx}", "source": "rule"}
    if stage == "S2":
        base |= {"source": "check", "check": f"check_s2_{idx}"}
    if stage in ("S8", "S9"):
        base |= {"source": "check", "check": f"check_{stage}_{idx}"}
    if stage == "S7":
        base |= {"detail": "実コマンド"}
    return base | kw


def _case(name, F, role="implementer", covered=False, **kw):
    _UNIT[name] = {"F": F, "role": role, "covered": covered, "coveredReason": "許可の理由", **kw}


PAIRS_ST = [(a, b) for i, a in enumerate(STAGES) for b in STAGES[i + 1 :]]

for _role in ("implementer", "explorer"):
    for _s in STAGES:
        _case(f"alone/{_role}/{_s}", [_finding(_s)], _role)
    for _a, _b in PAIRS_ST:
        # 並びを逆 (後の段が先頭) にしても、段の順で決まる
        _case(f"pair/{_role}/{_a}>{_b}", [_finding(_b), _finding(_a)], _role)

_plain = _finding("S6", 0, reason="確認の理由")
_blind = _finding("S6", 5, reason="blind の理由", blind=True)
_case("s6/blind-last", [_plain, _blind])
_case("s6/blind-first", [_blind, _plain])
_case("s6/blind-only", [_blind])
_case("s6/plain-two", [_finding("S6", 3, reason="後"), _finding("S6", 1, reason="先")])
for _st in ("S2", "S9", "S5"):
    _case(f"idx/{_st}/fwd", [_finding(_st, 1, reason="先"), _finding(_st, 4, reason="後")])
    _case(f"idx/{_st}/rev", [_finding(_st, 4, reason="後"), _finding(_st, 1, reason="先")])
_case("tools/S2/reader", [_finding("S2")], "reader")
_case("tools/S3/reader", [_finding("S3")], "reader")
_case("tools/none/reader", [], "reader")
_case("tools/none/orchestrator", [], "orchestrator")
_case("cov/alone", [], covered=True)
_case("cov/with-s9", [_finding("S9")], covered=True)
_case("def/explorer", [], "explorer")
_case("def/implementer", [], "implementer")
_case("conv/default-ask/boundary", [], boundary=True)
_case("conv/default-ask/bypass", [], bypass=True)
_case("conv/rule-ask/boundary", [_finding("S9")], boundary=True)
_case("conv/rule-ask/bypass", [_finding("S9")], bypass=True)
_case("conv/must/bypass", [_finding("S6")], bypass=True)
_case("conv/must/boundary", [_finding("S8")], boundary=True)
_case("conv/deny/both", [_finding("S5")], bypass=True, boundary=True)


@lru_cache(maxsize=1)
def _unit_results():
    names = list(_UNIT)
    out = _run_with_json("judge", [_UNIT[n] for n in names])
    return dict(zip(names, out, strict=True))


def _u(name):
    return _unit_results()[name]


@pytest.mark.parametrize("role", ["implementer", "explorer"])
@pytest.mark.parametrize(("a", "b"), PAIRS_ST, ids=[f"{a}>{b}" for a, b in PAIRS_ST])
def test_an_earlier_stage_wins_over_a_later_stage(role, a, b):
    assert _u(f"pair/{role}/{a}>{b}") == _u(f"alone/{role}/{a}")


@pytest.mark.parametrize("stage", STAGES)
def test_each_stage_has_its_own_output(stage):
    got = _u(f"alone/implementer/{stage}")
    assert f"理由 {stage}/0" in got["reason"]
    if stage in ("S2", "S3", "S4", "S5"):
        assert got["decision"] == "deny"
    if stage in ("S6", "S7", "S8"):
        assert got["decision"] == "ask" and got["mustConfirm"] is True
    if stage == "S9":
        assert got["decision"] == "ask" and "mustConfirm" not in got


def test_s7_and_s9_change_with_a_deny_default_role():
    s7 = _u("alone/explorer/S7")
    assert s7["decision"] == "deny" and s7["reason"].endswith(
        "。この役割は shell で元に戻せない操作をしない"
    )
    s9 = _u("alone/explorer/S9")
    assert s9["decision"] == "deny" and s9["reason"].endswith(
        "この役割は既定が deny なので、承認で通さない (bypass でも通さない)"
    )
    assert s9["check"] == "check_S9_0"
    # S6 と S8 の必須確認は、既定が deny の役割でも ask のまま (E1: 段間の優先順位の根拠)
    assert _u("alone/explorer/S6")["decision"] == "ask"
    assert _u("alone/explorer/S8")["decision"] == "ask"


@pytest.mark.parametrize("name", ["blind-last", "blind-first", "blind-only"])
def test_s6_aggregates_blind_over_the_whole_stage(name):
    # E2: blind が段のどこかにあれば deny。順序・idx に依らない
    got = _u(f"s6/{name}")
    assert got["decision"] == "deny" and got["reason"] == "blind の理由"


def test_s6_without_blind_reports_the_smallest_idx():
    got = _u("s6/plain-two")
    assert got["reason"] == "先" and got["mustConfirm"] is True


@pytest.mark.parametrize("stage", ["S2", "S9", "S5"])
def test_within_a_stage_the_smaller_idx_decides(stage):
    assert _u(f"idx/{stage}/fwd") == _u(f"idx/{stage}/rev")
    assert "先" in _u(f"idx/{stage}/fwd")["reason"]


def test_s2_is_common_and_returns_before_the_tools_check():
    assert _u("tools/S2/reader")["reason"] == "理由 S2/0"
    for name in ("tools/S3/reader", "tools/none/reader", "tools/none/orchestrator"):
        assert _u(name)["decision"] == "deny" and "は bash を使えない" in _u(name)["reason"], name


def test_covered_allows_after_every_finding_and_the_default_is_last():
    assert _u("cov/alone")["decision"] == "allow"
    assert _u("cov/alone")["reason"] == "許可の理由" and _u("cov/alone")["source"] == "rule"
    assert _u("cov/with-s9")["decision"] == "ask"
    assert _u("def/explorer")["decision"] == "deny" and _u("def/explorer")["source"] == "default"
    assert (
        _u("def/implementer")["decision"] == "ask" and _u("def/implementer")["source"] == "default"
    )


def test_boundary_only_relaxes_a_default_ask():
    assert (
        _u("conv/default-ask/boundary")["decision"] == "allow"
        and _u("conv/default-ask/boundary")["sandboxed"] is True
    )
    assert _u("conv/rule-ask/boundary")["decision"] == "ask"
    assert _u("conv/must/boundary")["decision"] == "ask"
    assert _u("conv/deny/both")["decision"] == "deny"


def test_bypass_relaxes_an_ask_but_not_a_must_confirm():
    assert (
        _u("conv/default-ask/bypass")["decision"] == "allow"
        and _u("conv/default-ask/bypass")["bypassed"] is True
    )
    assert (
        _u("conv/rule-ask/bypass")["decision"] == "allow"
        and _u("conv/rule-ask/bypass")["bypassed"] is True
    )
    assert (
        _u("conv/must/bypass")["decision"] == "ask"
        and _u("conv/must/bypass")["mustConfirm"] is True
    )


# ─── 実コマンドで、新の判定器と旧のカスケードを比べる ─────────────────────────────────────────

# 4 対 (A&&B と B&&A の両順)。段間の優先順位は、通常の ask に docker rm を使う (E1)
PAIRS = {
    "confirm.bash+通常ask": ("gh pr create --title t --body b", "docker rm x"),
    "confirm.bash+local_git": ("gh pr create --title t --body b", "git branch -D x"),
    "local_git+confirm.checks": ("git clean -fd", "gh api -X POST repos/o/r/issues -f title=x"),
    "confirm.checks+通常ask": ("gh api -X POST repos/o/r/issues -f title=x", "docker rm x"),
}
# 役割ごとの 4 モード (ask・bypass・boundary・bypass+boundary) の期待。M=必須確認 ask、A=ask、L=allow、D=deny
_BASH = ("committer", "explorer", "implementer", "worker")
_NO_BASH = {"orchestrator": "DDDD", "reader": "DDDD"}
_ALL_M = dict.fromkeys(_BASH, "MMMM") | _NO_BASH
_ALL_D = dict.fromkeys(_BASH, "DDDD") | _NO_BASH
PAIR_EXPECT = {
    "confirm.bash+通常ask": _ALL_M,
    "confirm.bash+local_git": _ALL_M,
    "local_git+confirm.checks": {
        "committer": "DDDD",
        "explorer": "DDDD",
        "implementer": "MMMM",
        "worker": "MMMM",
    }
    | _NO_BASH,
    "confirm.checks+通常ask": _ALL_M,
}

BLIND = [
    "gh pr create --title t --body b && gh issue create --title t --body-file -",
    "gh issue create --title t --body-file - && gh pr create --title t --body b",
    'gh pr create --title t --body "$(cat f)"',
    'gh pr create --title t --body b && gh pr create --title "$(date)" --body c',
    "gh pr create --title t --body-file - && gh pr create --title t --body b",
    "gh pr create --title t --body b && gh pr edit 1 --body-file -",
    "gh pr create --title t --body b && gh pr create --title u --body-file -",
]

# E1: git reset は explorer・committer・worker の shell_deny (S5)。S6/S8 に届かない。implementer は M
_E1_EXPECT = {
    "committer": "DDDD",
    "explorer": "DDDD",
    "worker": "DDDD",
    "implementer": "MMMM",
} | _NO_BASH
ERRATA_E1 = {
    "gh api -X POST repos/o/r/issues -f title=x && git reset": _E1_EXPECT,
    "gh pr create --title t --body b && git reset": _E1_EXPECT,
}

# 段内の順序 (S2 の元の入力と cdVariant の同時ヒット・複数の確認パターン・複数の通常 ask)
ORDER_CMDS = {
    "s2-cdvariant": "cd .ssh && cat id_rsa",
    "s2-original": "cd ~/.ssh && cat id_rsa",
    "s2-both-hit": "cd ~/.ssh && cat id_rsa && sudo ls",
    "s2-both-hit-rev": "sudo ls && cd ~/.ssh && cat id_rsa",
    "s2-two-denies": "git push && sudo ls",
    "s2-two-denies-rev": "sudo ls && git push",
    "confirm-two": "gh pr create --title t --body b && gh issue close 1",
    "confirm-two-rev": "gh issue close 1 && gh pr create --title t --body b",
    "confirm-two-chezmoi": "docker rm x && chezmoi apply",
    "ask-two": "docker rm x && git clean -n",
    "ask-two-rev": "git clean -n && docker rm x",
    "local-git-two": "git clean -fd && git branch -D x",
    "local-git-two-rev": "git branch -D x && git clean -fd",
}

# 代表例の表 (契約 v2 手順 2 の再計算表。E1 で直した期待値)。implementer・worker・explorer・committer の 4 モード
_D = {"implementer": "DDDD", "worker": "DDDD", "explorer": "DDDD", "committer": "DDDD"}
_ALW = {"implementer": "ALLL", "worker": "ALLL", "explorer": "DDDD", "committer": "DDDD"}
_ALAL = {"implementer": "ALAL", "worker": "ALAL", "explorer": "DDDD", "committer": "DDDD"}
_MM = {"implementer": "MMMM", "worker": "MMMM", "explorer": "DDDD", "committer": "DDDD"}
REP = {
    "git clean -fd && gh api -X POST repos/o/r/issues -f title=x": _MM,
    "git log; unknown_command_xyz": _ALW,
    "git log | unknown_command_xyz": _ALW,
    "git log --output=x.txt": _ALW,
    "gh pr create --title t --body b && unknown_command_xyz": dict.fromkeys(_BASH, "MMMM"),
    "git commit -m x; git reset": _D,
    "git clean -n": _ALAL,
    "git worktree remove .tmp/worktrees/x": _ALW,
    "git restore --staged a.txt": _ALW | {"worker": "DDDD"},
    "git worktree remove -f .tmp/worktrees/x": _D,
    "git worktree remove ../x": _ALW,
    "ssh h git worktree remove x": _D,
    "git restore --staged a.txt && git status": _D,
    "bash -c 'git push'": _D,
    "find . -exec git push ;": _D,
    "$(echo git) push": _D,
    "g=git; $g push": _D,
    "p=push; git $p": _D,
    "find . -name x -exec rm {} +": _ALAL,
    "git $x": _ALW,
    "git branch -D x": _MM,
    "git status && git branch -D x": _MM,
}


def _all_commands():
    cmds = []
    for a, b in PAIRS.values():
        cmds += [f"{a} && {b}", f"{b} && {a}"]
    cmds += BLIND + list(ERRATA_E1) + list(ORDER_CMDS.values()) + list(REP)
    return list(dict.fromkeys(cmds))


@lru_cache(maxsize=1)
def _real_rows():
    by = {}
    for r in _run_with_json("real", _all_commands()):
        by.setdefault(r["command"], {})[(r["role"], r["mode"])] = r
    return by


def _label(res):
    if res["decision"] == "ask":
        return "M" if res.get("mustConfirm") else "A"
    return {"allow": "L", "deny": "D"}[res["decision"]]


def _labels(command, role):
    return "".join(_label(_real_rows()[command][(role, m)]["now"]) for m in MODES)


def _assert_same_as_legacy(command):
    rows = _real_rows()[command]
    assert len(rows) == len(ROLES) * len(MODES)
    for key, r in rows.items():
        assert json.dumps(r["now"], sort_keys=True) == json.dumps(r["old"], sort_keys=True), (
            command,
            key,
            r,
        )


def _assert_labels(command, expect):
    for role, want in expect.items():
        assert _labels(command, role) == want, (command, role)


def _reason(command, role="implementer", mode="ask"):
    return _real_rows()[command][(role, mode)]["now"]["reason"]


_PAIR_CASES = [(name, order) for name in PAIRS for order in ("ab", "ba")]


@pytest.mark.parametrize(("name", "order"), _PAIR_CASES, ids=[f"{n}-{o}" for n, o in _PAIR_CASES])
def test_four_pairs_match_the_legacy_cascade(name, order):
    a, b = PAIRS[name]
    command = f"{a} && {b}" if order == "ab" else f"{b} && {a}"
    _assert_same_as_legacy(command)
    _assert_labels(command, PAIR_EXPECT[name])


@pytest.mark.parametrize("command", BLIND)
def test_blind_in_any_segment_is_denied_for_every_role_and_mode(command):
    _assert_same_as_legacy(command)
    for role in ROLES:
        assert _labels(command, role) == "DDDD", (command, role)
    for role in _BASH:
        assert "本文を確認できない形" in _reason(command, role)


@pytest.mark.parametrize("command", list(ERRATA_E1))
def test_errata_e1_git_reset_is_a_role_shell_deny(command):
    _assert_same_as_legacy(command)
    _assert_labels(command, ERRATA_E1[command])
    for role in ("explorer", "committer", "worker"):
        assert "shell_deny" in _reason(command, role)


@pytest.mark.parametrize("name", list(ORDER_CMDS))
def test_in_stage_order_matches_the_legacy_cascade(name):
    _assert_same_as_legacy(ORDER_CMDS[name])


def test_s2_prefers_the_original_input_over_the_cd_variant():
    # 元の入力の検査 (DENY_NAMES) が先、cdVariant の検査 (PATH_NAMES) が後
    assert "sudo" in _reason(ORDER_CMDS["s2-both-hit"]) and "sudo" in _reason(
        ORDER_CMDS["s2-both-hit-rev"]
    )
    assert "id_rsa" in _reason(ORDER_CMDS["s2-cdvariant"])
    assert "id_rsa" in _reason(ORDER_CMDS["s2-original"])


def test_s2_denies_are_reported_by_check_order():
    # どちらも [bash] deny (check_policy_deny)。並びを逆にしても、段内は検査の順で、同じ検査 (セグメント順 → パターン順) の理由になる
    a, b = _reason(ORDER_CMDS["s2-two-denies"]), _reason(ORDER_CMDS["s2-two-denies-rev"])
    assert "deny パターン" in a and "deny パターン" in b
    assert "git push" in a and "sudo" in b


def test_confirm_patterns_follow_the_segment_order():
    assert "`gh pr create`" in _reason(ORDER_CMDS["confirm-two"])
    assert "`gh issue close`" in _reason(ORDER_CMDS["confirm-two-rev"])
    # confirm.bash は通常 ask より先
    assert "`chezmoi apply`" in _reason(ORDER_CMDS["confirm-two-chezmoi"])


def test_ordinary_asks_follow_the_segment_order():
    assert "`docker rm`" in _reason(ORDER_CMDS["ask-two"])
    assert "`git clean`" in _reason(ORDER_CMDS["ask-two-rev"])


def test_local_git_reports_the_first_segment():
    first, second = _reason(ORDER_CMDS["local-git-two"]), _reason(ORDER_CMDS["local-git-two-rev"])
    assert "git clean" in first.split("\n")[0] and "git branch" not in first.split("\n")[0]
    assert "git branch" in second.split("\n")[0] and "git clean" not in second.split("\n")[0]


# 代表例の表を、baseline の行 (凍結した現行の出力) と突き合わせる
@lru_cache(maxsize=1)
def _baseline_truth():
    rows = {}
    for line in (GOLDEN / "ts_baseline.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["kind"] == "truth":
            rows[(row["input"], row["role"], row["mode"])] = row
    return rows


def _tokenize(text):
    return text.replace(str(ROOT), "${ROOT}").replace(os.path.expanduser("~"), "${HOME}")


@pytest.mark.parametrize("command", list(REP))
def test_representative_table(command):
    _assert_same_as_legacy(command)
    _assert_labels(command, REP[command])
    base = _baseline_truth()
    for role in ROLES:
        for mode in MODES:
            now = _real_rows()[command][(role, mode)]["now"]
            row = base.get((command, role, mode))
            if row is None:
                continue
            want = (
                row["decision"],
                _tokenize(row["reason"]),
                row["source"],
                row.get("mustConfirm", False),
            )
            assert want == (
                now["decision"],
                _tokenize(now["reason"]),
                now["source"],
                now.get("mustConfirm", False),
            ), (command, role, mode)


def test_the_representative_table_is_mostly_in_the_baseline():
    base = _baseline_truth()
    missing = [c for c in REP if (c, "implementer", "ask") not in base]
    # baseline の真理値表に無いのは p=push; git $p (decide の行にある) だけ
    assert missing == ["p=push; git $p"]
