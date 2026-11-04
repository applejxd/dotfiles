"""B3: スケジューラの wake_parent (承認待ちなど) を、実機向け接着層 (work/driver-run.ts) が利用者へ通知する試験。

driver は ``work_driver_run_driver.mjs``。see docs/spec/work/driver-run.md#起動の通知
"""

from __future__ import annotations

import re

import pytest
from test_work_driver_run import SRC, case

# ── 再現: T 承認済み・U 未承認・T が U に依存 ──


def test_awaiting_approval_starts_nothing_and_notifies_once():
    r = case("wakeApproval")
    assert r["ok"] == [True, True]  # 台帳へ入った (空振りではない)
    assert r["first"]["spawns"] == 0
    assert r["first"]["notes"] == 1


def test_awaiting_approval_message_guides_goal_approve():
    f = case("wakeApproval")["first"]
    assert "/goal approve" in f["msg"] and "\n" not in f["msg"]


def test_awaiting_approval_is_an_alert_level_warning():
    assert case("wakeApproval")["first"]["level"] == "warning"


def test_same_reason_is_not_repeated_on_next_ticks():
    r = case("wakeApproval")
    assert r["again"] == {"spawns": 0, "notes": 1}


def test_ticks_while_waiting_do_not_write_to_the_ledger():
    assert case("wakeApproval")["seqSame"] is True


def test_notification_does_not_create_an_approval():
    r = case("wakeApproval")
    assert r["after"] == {"U": False, "T": True}  # U は未承認のまま (通知側が承認しない)


def test_after_user_approval_the_task_starts():
    r = case("wakeApproval")
    assert r["ap"] is True and r["spawnedAfter"] == ["U"]  # 依存先の U が先に起動する


# ── 通知の送り口が失敗しても tick が続く ──


def test_notify_failure_does_not_stop_the_tick():
    r = case("wakeNotifyThrows")
    assert r["calls"] == 1 and r["live"] == 0 and r["spawns"] == 0


def test_notify_failure_is_not_retried_every_tick():
    assert case("wakeNotifyThrows")["calls"] == 1


def test_default_sink_uses_ctx_ui_notify_when_ui_exists():
    r = case("wakeDefaultSink")
    assert len(r["notes"]) == 1 and "/goal approve" in r["notes"][0][0] and r["spawns"] == 0


# ── 理由ごとの扱い (選別の表の事象) ──

EXPECT = {
    "awaiting_approval": ("wait.plan-approval", "alert"),
    "provider_exhausted": ("resource.429", "line"),
    "budget": ("budget.paused", "line"),
    "failed": ("run.failed", "line"),
    "all_done": ("goal.done", "alert"),
    "stuck": ("wait.confirm", "alert"),
    "invalid_writes:T1": ("run.warning", "line"),
    "zzz": ("wait.confirm", "alert"),  # 未知の理由は黙らせず、確認の待ちにする
}


@pytest.mark.parametrize("reason", list(EXPECT))
def test_wake_reason_maps_to_notice_event_and_show(reason):
    w = case("wakeReasons")[reason]
    assert (w["event"], w["show"]) == EXPECT[reason]
    assert w["message"] and "\n" not in w["message"]


@pytest.mark.parametrize("reason", ["awaiting_approval", "stuck", "all_done"])
def test_user_waits_are_never_silent(reason):
    assert case("wakeReasons")[reason]["show"] != "silent"


# ── 実装の不変条件 (ソース) ──


def test_source_handles_wake_effect_through_notices_table():
    src = SRC.read_text(encoding="utf-8")
    assert 'e.kind === "wake"' in src and "select(w.event)" in src


def test_source_never_builds_approval_events():
    src = SRC.read_text(encoding="utf-8")
    assert not re.search(r'makeEvent\(\s*"plan\.approved"|"plan\.approved"', src)
