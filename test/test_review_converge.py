"""home/dot_claude/skills/review-loop/scripts/converge.py: 収束・step back 判定（表駆動）。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "home" / "dot_claude" / "skills" / "review-loop" / "scripts" / "converge.py"

_spec = importlib.util.spec_from_file_location("converge_under_test", SCRIPT)
assert _spec and _spec.loader
cv = importlib.util.module_from_spec(_spec)
sys.modules["converge_under_test"] = cv
_spec.loader.exec_module(cv)


def F(id_, sev="BLOCKER", cls="impl", fp=None, status="open", fix=False):
    """指摘 1 件。"""
    return {
        "id": id_,
        "severity": sev,
        "cause_class": cls,
        "fingerprint": fp or f"fp-{id_}",
        "status": status,
        "introduced_by_fix": fix,
    }


def R(n, *findings, cost=0.5):
    return {"round": n, "cost_usd": cost, "findings": list(findings)}


STEP = {"stepback": {"decision": "x"}}


def jsonl(*records):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"


def run(*records, **cfg):
    rounds, steps = cv.parse_records(jsonl(*records))
    return cv.evaluate(rounds, steps, cv.Config(**cfg))


def blocker_rounds(*classes, earlier="verified", last="open"):
    """ラウンドごとに新しい BLOCKER を 1 件ずつ出す。前の指摘は既定で verified にして T6 を避ける。"""
    n = len(classes)
    return [
        R(i + 1, F(f"B{i + 1}", cls=c, status=last if i == n - 1 else earlier))
        for i, c in enumerate(classes)
    ]


# ---- 収束 ----


def test_converged_when_all_verified():
    res = run(R(1, F("a", status="verified"), F("b", "MAJOR", status="verified")))
    assert res["verdict"] == "converged"
    assert res["triggers"] == []


def test_converged_with_only_minor_and_nit_open():
    res = run(R(1, F("a", status="verified"), F("m", "MINOR"), F("n", "NIT")))
    assert res["verdict"] == "converged"


def test_clean_first_round_is_converged():
    assert run(R(1))["verdict"] == "converged"


def test_fixed_but_not_verified_is_not_converged():
    res = run(R(1, F("a", status="fixed")))
    assert res["verdict"] == "continue"
    assert res["metrics"]["unresolved_blocker"] == 1


def test_last_round_with_fixed_minor_not_converged():
    res = run(R(1, F("a", status="verified"), F("m", "MINOR", status="fixed")))
    assert res["verdict"] == "continue"


def test_empty_last_round_does_not_verify_fixed_blocker():
    res = run(R(1, F("a", status="fixed")), R(2))
    assert res["verdict"] == "continue"


def test_later_verified_overrides_earlier_open():
    res = run(R(1, F("a")), R(2, F("a", status="verified")))
    assert res["verdict"] == "converged"


def test_accepted_risk_is_stop_not_converged():
    res = run(R(1, F("a", status="accepted")))
    assert res["verdict"] == "stop"
    assert res["metrics"]["accepted_bm"] == 1


def test_converged_overrides_triggers():
    res = run(
        *blocker_rounds("spec", "impl", "scope", last="verified"),
        R(4, F("B4", status="verified", cls="impl")),
    )
    assert res["verdict"] == "converged"
    assert "T2" in res["triggers"]  # 収束していても triggers は参考情報として残る


def test_no_records_continue():
    assert run()["verdict"] == "continue"


# ---- T1 ----


def test_t1_fires_on_two_recurrences():
    res = run(*blocker_rounds("impl", "scope", "impl", "spec", "impl"))
    assert "T1" in res["triggers"]


def test_t1_not_on_one_recurrence():
    res = run(R(1, F("a", cls="impl", status="verified")), R(2, F("b", cls="impl")))
    assert "T1" not in res["triggers"]


def test_t1_counts_rounds_not_findings():
    res = run(R(1, F("a", cls="impl"), F("b", cls="impl"), F("c", cls="impl")))
    assert "T1" not in res["triggers"]


def test_t1_ignores_major():
    res = run(*[R(i, F(f"m{i}", "MAJOR", cls="impl", status="verified")) for i in (1, 2, 3)])
    assert "T1" not in res["triggers"]


def test_t1_same_id_reported_again_is_not_recurrence():
    res = run(R(1, F("a")), R(2, F("a")), R(3, F("a")))
    assert "T1" not in res["triggers"]


def test_t1_threshold_is_configurable():
    recs = [R(1, F("a", status="verified")), R(2, F("b", status="verified"))]
    assert "T1" not in run(*recs)["triggers"]
    assert "T1" in run(*recs, recur=1)["triggers"]


# ---- T2 ----


def test_t2_fires_at_third_round_with_different_classes():
    res = run(*blocker_rounds("spec", "scope", "principle"))
    assert "T2" in res["triggers"]
    assert res["verdict"] == "stepback"


def test_t2_not_at_two_rounds():
    assert "T2" not in run(*blocker_rounds("spec", "scope"))["triggers"]


def test_t2_not_when_streak_broken():
    recs = [
        R(1, F("a", cls="spec", status="verified")),
        R(2, F("b", cls="scope", status="verified")),
        R(3, F("m", "MAJOR", status="verified")),
        R(4, F("c", cls="impl", status="verified")),
        R(5, F("d", cls="premise", status="verified")),
    ]
    assert "T2" not in run(*recs)["triggers"]


def test_t2_not_when_all_same_class():
    res = run(*blocker_rounds("impl", "impl", "impl"))
    assert "T2" not in res["triggers"]
    assert "T1" in res["triggers"]


def test_t2_needs_new_blockers_not_reappearing():
    res = run(R(1, F("a", cls="spec")), R(2, F("a", cls="spec")), R(3, F("a", cls="spec")))
    assert "T2" not in res["triggers"]


def test_t2_streak_configurable():
    assert "T2" in run(*blocker_rounds("spec", "scope"), streak=2)["triggers"]


# ---- T3 ----


def test_t3_fires_on_two_consecutive_fix_induced():
    res = run(
        R(1, F("a", status="verified")),
        R(2, F("b", fix=True, status="verified")),
        R(3, F("c", fix=True, status="verified")),
    )
    assert "T3" in res["triggers"]


def test_t3_not_when_not_consecutive():
    res = run(
        R(1, F("a", fix=True, status="verified")),
        R(2, F("b", status="verified")),
        R(3, F("c", fix=True, status="verified")),
    )
    assert "T3" not in res["triggers"]


def test_t3_ignores_non_blocker():
    res = run(
        R(1, F("a", "MAJOR", fix=True, status="verified")),
        R(2, F("b", "MAJOR", fix=True, status="verified")),
    )
    assert "T3" not in res["triggers"]


def test_t3_single_is_not_enough():
    assert "T3" not in run(R(1, F("a", fix=True)))["triggers"]


# ---- T4 ----


def test_t4_same_fingerprint_open_twice():
    res = run(R(1, F("a", fp="x")), R(2, F("b", fp="x")))
    assert "T4" in res["triggers"]


def test_t4_not_when_fixed_in_between():
    res = run(R(1, F("a", fp="x")), R(2, F("a", fp="x", status="fixed")), R(3, F("b", fp="x")))
    assert "T4" not in res["triggers"]


def test_t4_ignores_minor():
    res = run(R(1, F("a", "MINOR", fp="x")), R(2, F("b", "MINOR", fp="x")))
    assert "T4" not in res["triggers"]


def test_t4_different_fingerprints_do_not_fire():
    res = run(R(1, F("a", fp="x")), R(2, F("b", fp="y")))
    assert "T4" not in res["triggers"]


# ---- T5 ----


def test_t5_count_fires_at_threshold():
    findings = [F(f"m{i}", "MAJOR", status="verified") for i in range(15)]
    assert "T5" in run(R(1, *findings))["triggers"]
    res = run(R(1, *findings, F("last", "MAJOR")))
    assert "T5" in res["triggers"]
    assert res["verdict"] == "stepback"


def test_t5_count_below_threshold():
    res = run(R(1, *[F(f"m{i}", "MAJOR") for i in range(14)]))
    assert "T5" not in res["triggers"]


def test_t5_count_across_rounds():
    res = run(
        R(1, *[F(f"a{i}", "MAJOR", status="verified") for i in range(8)]),
        R(2, *[F(f"b{i}", "MAJOR") for i in range(7)]),
    )
    assert "T5" in res["triggers"]


def test_t5_cost_over_threshold():
    res = run(R(1, F("a", "MAJOR"), cost=3.0), R(2, F("a", "MAJOR"), cost=3.5))
    assert "T5" in res["triggers"]
    assert res["metrics"]["cost_usd"] == 6.5


def test_t5_cost_equal_threshold_not_fire():
    res = run(R(1, F("a", "MAJOR"), cost=3.0), R(2, F("a", "MAJOR"), cost=3.0))
    assert "T5" not in res["triggers"]


def test_t5_cost_configurable():
    res = run(R(1, F("a", "MAJOR"), cost=3.0), cost=2.0)
    assert "T5" in res["triggers"]


def test_t5_minor_not_counted():
    res = run(R(1, *[F(f"m{i}", "MINOR") for i in range(20)]))
    assert "T5" not in res["triggers"]


# ---- T6 ----


def test_t6_two_blockers_at_round_three():
    res = run(R(1), R(2), R(3, F("a"), F("b")))
    assert "T6" in res["triggers"]


def test_t6_not_before_round_three():
    res = run(R(1), R(2, F("a"), F("b")))
    assert "T6" not in res["triggers"]


def test_t6_one_blocker_not_enough():
    res = run(R(1), R(2), R(3, F("a")))
    assert "T6" not in res["triggers"]


def test_t6_resolved_blockers_not_counted():
    res = run(
        R(1, F("a", fp="p"), F("b", fp="q")),
        R(2, F("a", status="verified", fp="p"), F("b", status="verified", fp="q")),
        R(3),
    )
    assert "T6" not in res["triggers"]


def test_t6_fixed_unverified_still_counts():
    res = run(R(1, F("a", status="fixed"), F("b", status="fixed")), R(2), R(3))
    assert "T6" in res["triggers"]


# ---- T7 ----


def test_t7_single_surface_open():
    res = run(R(1, F("a", "MAJOR", cls="surface-open")))
    assert res["triggers"] == ["T7"]
    assert res["verdict"] == "stepback"


def test_t7_without_surface_open():
    assert "T7" not in run(R(1, F("a", cls="scope")))["triggers"]


# ---- 複数同時・上限・stop ----


def test_multiple_triggers_reported_together():
    res = run(*blocker_rounds("spec", "scope", "impl", "impl", "impl", earlier="open"))
    assert {"T1", "T2", "T6"} <= set(res["triggers"])
    assert res["verdict"] == "stepback"


def test_round_limit_stop_without_triggers():
    recs = [R(i, F(f"m{i}", "MAJOR", fp=f"p{i}", status="verified")) for i in range(1, 6)] + []
    recs[-1] = R(5, F("m5", "MAJOR", fp="p5"))
    res = run(*recs)
    assert res["verdict"] == "stop"
    assert "上限" in " ".join(res["reasons"])


def test_below_round_limit_continue():
    res = run(R(1, F("m1", "MAJOR")))
    assert res["verdict"] == "continue"


def test_limit_with_triggers_prefers_stepback():
    res = run(*blocker_rounds("spec", "scope", "principle", "impl", "premise", earlier="open"))
    assert res["verdict"] == "stepback"


def test_stepback_twice_then_stop():
    recs = [STEP, STEP, *blocker_rounds("spec", "scope", "principle")]
    res = run(*recs)
    assert res["verdict"] == "stop"
    assert res["metrics"]["stepbacks"] == 2


def test_stepback_once_still_stepback():
    res = run(STEP, *blocker_rounds("spec", "scope", "principle"))
    assert res["verdict"] == "stepback"


def test_stepback_resets_segment():
    res = run(*blocker_rounds("spec", "scope", "principle"), STEP, R(1, F("n", cls="impl")))
    assert res["verdict"] == "continue"
    assert res["metrics"]["rounds"] == 1
    assert res["metrics"]["stepbacks"] == 1


def test_stepback_then_converged_after_two():
    res = run(STEP, STEP, R(1, F("a", status="verified")))
    assert res["verdict"] == "converged"


def test_max_stepbacks_configurable():
    res = run(STEP, *blocker_rounds("spec", "scope", "principle"), max_stepbacks=1)
    assert res["verdict"] == "stop"


# ---- 実例の再現 ----


def test_case_git_push_five_reviews_t2_at_third():
    """git_push: 5 回の review で毎回別分類の BLOCKER。3 回目で T2 が発火する。"""
    classes = ["spec", "principle", "surface-open", "premise", "scope"]
    seen = []
    for n in range(1, 6):
        recs = [
            R(i + 1, F(f"R{i + 1}", cls=classes[i], status="fixed"), cost=1.68) for i in range(n)
        ]
        seen.append(run(*recs)["triggers"])
    assert "T2" not in seen[0] and "T2" not in seen[1]
    assert "T2" in seen[2]
    assert "T7" in seen[2]  # 面が開いていた（外部プログラム起動）


def test_case_git_push_cost_reaches_t5_by_round_four():
    recs = [
        R(i, F(f"R{i}", cls=c, status="fixed"), cost=1.68)
        for i, c in enumerate(["spec", "principle", "scope", "premise"], 1)
    ]
    assert "T5" in run(*recs)["triggers"]  # 4 × 1.68 = 6.72 > 6


def test_case_full_guard_redesign_relaxation_class_three_times():
    """フルガード再設計: 『緩和』クラス（ここでは premise）が #5・#21・#32 の 3 回。BLOCKER 計 12 件。"""
    recs = [
        R(1, F("5-1", cls="premise"), F("5-2", cls="principle", status="verified"), cost=2.1),
        R(
            2,
            F("21-1", cls="premise"),
            F("21-2", cls="impl", status="verified"),
            F("21-3", cls="scope", status="verified"),
            cost=1.5,
        ),
        R(
            3,
            F("32-1", cls="premise"),
            F("32-2", cls="impl", status="verified"),
            F("32-3", cls="spec", status="verified"),
            cost=0.9,
        ),
    ]
    res = run(*recs)
    assert "T1" in res["triggers"]
    assert res["metrics"]["new_blocker_rounds_by_class"]["premise"] == 3
    assert res["verdict"] == "stepback"


def test_case_worktree_remove_narrowing_converges():
    """worktree remove の例外: 範囲を狭めて 3〜4 手で収束（トリガーなし・最後は収束）。"""
    res = run(
        R(1, F("a", "MAJOR", cls="scope", status="fixed")),
        R(2, F("a", "MAJOR", cls="scope", status="verified"), F("b", "MINOR")),
    )
    assert res["verdict"] == "converged"


# ---- 入力エラー・決定性・CLI ----


@pytest.mark.parametrize(
    "record",
    [
        {"round": 1},  # findings 欠落
        {"findings": []},  # round 欠落
        {"round": 0, "findings": []},
        {"round": "1", "findings": []},
        {"round": 1, "findings": [{"id": "a"}]},  # キー欠落
        {"round": 1, "findings": [F("a", sev="CRITICAL")]},  # 未知の severity
        {"round": 1, "findings": [F("a", cls="typo")]},
        {"round": 1, "findings": [F("a", status="done")]},
        {"round": 1, "findings": [F("a"), F("a")]},  # 重複 id
        {"round": 1, "cost_usd": -1, "findings": []},
        {"round": 1, "findings": [{**F("a"), "introduced_by_fix": "yes"}]},
        {"stepback": "x"},
    ],
)
def test_invalid_input_raises(record):
    with pytest.raises(cv.InputError):
        cv.parse_records(jsonl(record))


def test_invalid_json_raises():
    with pytest.raises(cv.InputError):
        cv.parse_records("{not json\n")


def test_non_increasing_round_raises():
    with pytest.raises(cv.InputError):
        cv.parse_records(jsonl(R(2), R(2)))


def test_blank_lines_are_skipped():
    rounds, steps = cv.parse_records("\n" + jsonl(R(1)) + "\n\n")
    assert len(rounds) == 1 and steps == 0


def test_deterministic():
    recs = blocker_rounds("spec", "scope", "impl", "impl", earlier="open")
    assert run(*recs) == run(*recs)


def test_cli_check_outputs_json(tmp_path):
    p = tmp_path / "rounds.jsonl"
    p.write_text(jsonl(*blocker_rounds("spec", "scope", "principle")), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check", str(p)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["verdict"] == "stepback"
    assert set(out) == {"verdict", "triggers", "reasons", "metrics"}


def test_cli_invalid_input_exit_2(tmp_path):
    p = tmp_path / "rounds.jsonl"
    p.write_text('{"round": 1}\n', encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check", str(p)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 2
    assert "error" in json.loads(proc.stdout)


def test_cli_missing_file_exit_2(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check", str(tmp_path / "none.jsonl")],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 2


def test_cli_threshold_option(tmp_path):
    p = tmp_path / "rounds.jsonl"
    p.write_text(jsonl(R(1, F("a", "MAJOR"), cost=3.0)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "check", str(p), "--cost", "2"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert "T5" in json.loads(proc.stdout)["triggers"]


def test_cli_explain_lists_all_triggers():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "explain"], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0
    for name in ("T1", "T2", "T3", "T4", "T5", "T6", "T7"):
        assert f"{name}:" in proc.stdout
