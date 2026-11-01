"""`/pending approve` の巡回 (CHG-0058 の段 1。``pending-command.ts`` の巡回と ``pending-approve.ts`` の計画・実行の分離)。

``test/agents/pi/pending_patrol_driver.mjs`` が、偽の pi・偽のアダプタ・使い捨ての git リポジトリで動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。確かめるのは、B8 (先頭は「ここで終える」)・B9 (モデルへの通知の遅延)・
B10 (Esc・中断で全体が止まる)・B4 (失敗で止まる)・B11 (不変の snapshot・構造化した結果)・始まる条件・上限・単件との一貫性。

see docs/change/0058-batch-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_patrol_driver.mjs"
STOP_HERE = "ここで終える（残りは保留のまま）"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


# ---- B8 ----


def test_patrol_screen_leads_with_stop_and_enter_does_not_approve(table):
    a = table["b8_first"]
    assert a["titles"][1].startswith("巡回 1/3")
    assert a["screenOptions"] == [STOP_HERE, "承認して実行", "全文を見る", "保留のまま次へ", "破棄"]
    assert a["selects"] == 2 and a["marks"] == [] and a["sent"] == 0
    assert a["pending"] == [True, True, True]
    assert a["final"]["text"].startswith("巡回を終えた (1 件を見た)")


def test_single_pending_keeps_the_original_screen(table):
    s = table["b8_single"]
    assert s["options"] == ["承認して実行", "全文を見る", "保留のまま閉じる", "破棄"]
    assert s["selects"] == 1 and s["marks"] == ["r1"]


# ---- 始まる条件 ----


def test_an_explicit_id_never_patrols(table):
    s = table["start_with_id"]
    assert s["selects"] == 1 and s["options"][0] == "承認して実行"
    assert s["marks"] == ["r2"] and s["pending"] == [True, False]


def test_hub_approval_starts_a_patrol(table):
    s = table["start_hub"]
    assert s["titles"][1].startswith("巡回 1/2") and s["marks"] == []


@pytest.mark.parametrize(("case", "needle"), [("busy", "モデルの実行中"), ("disabled", "無効")])
def test_guards_refuse_before_any_patrol_screen(table, case, needle):
    g = table["start_guards"][case]
    assert g["selects"] == 1 and g["marks"] == [] and needle in g["final"]["text"]
    assert g["final"]["level"] == "warning"


def test_non_tui_is_refused_without_a_screen(table):
    g = table["start_guards"]["rpc"]
    assert g["selects"] == 0 and g["marks"] == [] and "TUI" in g["final"]["text"]


# ---- B10 ----


@pytest.mark.parametrize("case", ["esc", "error", "abort"])
def test_esc_error_and_abort_stop_without_opening_the_next_screen(table, case):
    r = table["b10"][case]
    assert r["selects"] == 3  # 選択 + 1 件目 + 2 件目。3 件目は開かない
    assert r["marks"] == ["r1"]


def test_skip_to_next_does_not_stop_the_patrol(table):
    r = table["b10"]["next"]
    assert r["selects"] == 4 and r["marks"] == []
    assert "見送り 3" in r["final"]["text"]


def test_stop_here_ends_after_running_what_was_approved(table):
    r = table["b10"]["stop_here"]
    assert r["selects"] == 3 and r["marks"] == ["r1"]


# ---- B9 ----


def test_model_is_told_only_at_the_end_in_order(table):
    r = table["b9"]["ok"]
    assert r["marks"] == ["r1", "r2", "r3"] and r["sent"] == 3
    assert r["sentAtSelects"] == [4, 4, 4]  # 全部の画面が終わってから
    assert r["noteSent"] == [0, 0, 0]  # 利用者への通知は、その場で出る
    assert r["tags"] == sorted(r["tags"])


def test_model_is_told_even_after_an_exception(table):
    r = table["b9"]["exception"]
    assert r["sent"] == 2 and r["sentAtSelects"] == [3, 3]
    assert r["final"]["level"] == "error"


def test_model_is_told_even_after_esc(table):
    r = table["b9"]["esc"]
    assert r["sent"] == 1 and r["sentAtSelects"] == [3]


def test_awake_model_after_the_screen_stops_before_running(table):
    r = table["b9"]["awake_after_screen"]
    assert r["marks"] == [] and r["sent"] == 0 and "モデルの実行中" in r["final"]["text"]


def test_awake_model_before_an_item_stops_the_patrol(table):
    r = table["b9"]["awake_before_item"]
    assert r["selects"] == 2 and r["marks"] == ["r1"] and r["sent"] == 1


# ---- B4 ----


@pytest.mark.parametrize(
    "mode",
    ["failed_confirmed", "unknown_stopped", "unconfirmed", "not_executed", "savefail", "cleanup"],
)
def test_a_bad_second_item_stops_before_the_third_screen(table, mode):
    r = table["b4"][mode]
    assert r["selects"] == 3 and r["marks"] == ["r1", "r2"]
    assert r["third"] is True
    assert r["final"]["level"] in ("warning", "error")


def test_a_refused_plan_stops_the_patrol_and_says_why(table):
    r = table["b4"]["planfail"]
    assert r["selects"] == 2 and r["marks"] == ["r1"] and r["third"] is True
    assert "計画を作れない" in r["final"]["text"] and r["final"]["level"] == "warning"


def test_all_success_goes_through_every_item(table):
    r = table["b4"]["all_success"]
    assert r["selects"] == 4 and r["marks"] == ["r1", "r2", "r3"]
    assert (
        r["final"]["text"].startswith("巡回を終えた (3 件を見た)") and r["final"]["level"] == "info"
    )
    assert all(x["done"] and x["result"]["outcome"] == "success" for x in r["results"])


def test_discard_then_continue(table):
    r = table["b4"]["discard"]
    assert r["marks"] == ["r2"]
    assert r["first"] == {"pending": False, "running": False, "done": False}
    assert "承認して実行 1 (成功 1)・見送り 1・破棄 1" in r["final"]["text"]


# ---- B11 ----


def test_snapshot_is_frozen_and_carries_the_shown_oid(table):
    p = table["b11"]["plan"]
    assert p["ok"] and p["frozen"] and p["oidIsShown"]
    assert p["keys"] == ["adapter", "cwd", "env", "id", "oid", "plan", "record", "summary", "view"]


def test_a_changed_record_is_not_approved_from_the_old_screen(table):
    b = table["b11"]
    assert b["discarded"] == {"kind": "refused", "marks": []}
    assert b["taken"] == {"kind": "refused", "marks": []}
    assert b["patrol_discarded"]["marks"] == []
    # 置換 (同じ ID・別の OID): 古い表示を承認せず、置換後の記録は pending のまま残る
    assert b["replaced"] == {
        "sameId": True,
        "differentOid": True,
        "kind": "refused",
        "marks": [],
        "pending": True,
        "running": False,
        "done": False,
    }


def test_structured_result_tells_what_happened_per_executor_outcome(table):
    s = table["b11"]["structured"]
    ex = "executed"
    assert s["unconfirmed"] == {
        "kind": ex,
        "outcome": "unknown",
        "termination": "unconfirmed",
        "saved": False,
        "cleanup": False,
        "kept": True,
    }
    assert s["savefail"] == {
        "kind": ex,
        "outcome": "success",
        "termination": "stopped",
        "saved": False,
        "cleanup": False,
        "kept": True,
    }
    assert s["cleanup"] == {
        "kind": ex,
        "outcome": "success",
        "termination": "stopped",
        "saved": True,
        "cleanup": True,
        "kept": False,
    }
    assert s["failed_confirmed"] == {
        "kind": ex,
        "outcome": "failed_confirmed",
        "termination": "stopped",
        "saved": True,
        "cleanup": False,
        "kept": False,
    }
    assert s["not_executed"] == {
        "kind": ex,
        "outcome": "not_executed",
        "termination": "stopped",
        "saved": True,
        "cleanup": False,
        "kept": False,
    }
    assert s["unknown_stopped"] == {
        "kind": ex,
        "outcome": "unknown",
        "termination": "stopped",
        "saved": True,
        "cleanup": False,
        "kept": False,
    }


def test_a_failing_model_notification_does_not_change_the_recorded_result(table):
    # 通知は補助。失敗しても、保存した結果 (success・保存済み) を unknown に読み替えない
    t = table["b11"]["throwTell"]
    assert t == {
        "kind": "executed",
        "outcome": "success",
        "termination": "stopped",
        "saved": True,
        "kept": False,
        "doneOid": "match",
    }


def test_snapshot_is_a_deep_frozen_copy_apart_from_what_the_adapter_holds(table):
    d = table["b11"]["deep"]
    assert d["planFrozen"] and d["recordFrozen"] and d["writeThrows"] and d["separate"]
    # アダプターが持つ元の計画を書き換えても、実行されるのは表示した計画 (tag = deep)
    assert d["marks"] == ["deep"] and d["kind"] == "executed"


def test_a_plan_that_cannot_be_copied_is_refused_before_any_screen(table):
    u = table["b11"]["unclonable"]
    assert u["ok"] is False and "複製して固定できない" in u["text"]
    assert (
        u["pending"] is True and u["running"] is False and u["done"] is False and u["marks"] == []
    )


def test_done_oid_identifies_the_saved_result_record(table):
    d = table["b11"]["doneOids"]
    assert d == {
        "unconfirmed": "none",
        "savefail": "none",
        "cleanup": "match",
        "failed_confirmed": "match",
        "not_executed": "match",
        "unknown_stopped": "match",
    }


# ---- B10 (実行中の Esc) ----


def test_esc_while_running_stops_after_this_item_without_cancelling_it(table):
    e = table["esc_run"]
    # 実行は止めない (実行した操作は完了・記録される)。次の画面は開かない
    assert e["marks"] == ["esc-run"] and e["selects"] == 2
    assert e["states"][0]["done"] is True and e["states"][1]["pending"] is True
    assert "実行中に Esc が押された" in e["finalText"]
    # 入力の購読は、実行の間だけ (実行中は 1 つ、終われば解除)
    assert e["during"] == [{"tag": "esc-run", "handlers": 1}]
    assert e["subscribed"] == 1 and e["unsubscribed"] == 1 and e["handlersLeft"] == 0


def test_keys_other_than_esc_while_running_do_not_stop_the_patrol(table):
    e = table["esc_run"]
    assert e["noEscMarks"] == 2 and e["noEscSelects"] == 3


# ---- 補助の失敗が、巡回と通知を妨げない ----


def test_a_failing_footer_update_does_not_stop_the_patrol_or_hold_back_the_notices(table):
    s = table["status_throws"]
    assert s["marks"] == ["r1", "r2"] and s["selects"] == 3
    assert s["sent"] == 2 and s["sentAtSelects"] == [3, 3]
    assert "内部エラー" not in s["final"]["text"]


def test_a_lock_that_cannot_be_released_leaves_cleanup_and_stops_the_patrol(table):
    k = table["lock_release_fails"]
    assert k["marks"] == ["lockfail"] and k["selects"] == 2
    assert k["results"] == [{"outcome": "success", "by": "executor"}, None]
    assert k["states"][1]["pending"] is True
    assert "後片付けが残っている" in k["final"]["text"]
    assert "統合ロックを外せなかった" in k["one"]


def test_execution_result_is_structured(table):
    e = table["b11"]["executed"]
    assert e == {
        "kind": "executed",
        "outcome": "success",
        "termination": "stopped",
        "saved": True,
        "cleanup": False,
        "kept": False,
        "sent": 1,
        "result": {"outcome": "success", "by": "executor"},
    }


def test_busy_model_after_the_screen_refuses_and_keeps_pending(table):
    b = table["b11"]["busy"]
    assert b["kind"] == "refused" and b["pending"] is True and b["marks"] == ["r3"]


# ---- 上限・一貫性 ----


def test_patrol_stops_at_eight_items(table):
    c = table["cap"]
    assert c["selects"] == 9 and c["pendingLeft"] == 9 and c["sent"] == 0
    assert "8 件" in c["final"]["text"] and "上限" in c["final"]["text"]


def test_each_item_makes_the_same_records_as_a_single_approval(table):
    c = table["consistency"]
    done = {
        "pending": False,
        "running": False,
        "done": True,
        "result": {"outcome": "success", "by": "executor"},
    }
    assert c["patrol"] == [done, done] and c["single"] == done
    assert c["patrolLocks"] == 0 and c["patrolKeys"] == c["singleKeys"]
    assert c["sentDetails"] == ["success", "success"] and c["singleSent"] == ["success"]
