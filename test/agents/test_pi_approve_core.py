"""非同期承認の承認する側の「実行の核」(``home/dot_config/pi/harness/pending-approve.ts`` の ``runApproved`` など。CHG-0055 の P8c)。

``test/agents/pi/approve_core_driver.mjs`` が、偽の ctx・偽のアダプタ・本物の統合ロック (``exclusive-lock.ts``) で動かして結果を
JSON で出す (node の型除去を使うので、22.18 未満の node では飛ばす)。確かめるのは、統合の排他ロック (実行中だけ持つ・別の承認者が
持っていたら実行せず保留へ戻す・reserved で止まったものだけ回復する・started は回復しない)、停止を確認できなかった実行
(D9: running とロックを残し、結果を書かない)、承認者の cwd の契約 (runsHere)、承認側の再判定 (authorize)、resolve の厳格化と
ロックの解放、一覧と unlock。

see docs/change/0055-async-approval.md#p8c-の決定-v2
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "approve_core_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_an_exclusive_operation_holds_the_lock_only_while_it_runs(table):
    s = table["lock_scope"]
    # 実行の最中は、ロックが 1 本ある。終われば外れている
    assert s["exclusive"]["marks"] == ["execute:peek", "locks:1"]
    assert s["exclusive"]["afterLocks"] == 0
    assert s["exclusive"]["level"] == "info"
    assert s["exclusive"]["result"]["outcome"] == "success"
    # 排他でない操作は、ロックを取らない (従来どおり)
    assert s["plain"]["marks"] == ["execute:peek", "locks:0"] and s["plain"]["afterLocks"] == 0


def test_a_bare_result_body_is_still_accepted_as_stopped(table):
    p = table["plain_body"]
    assert p["level"] == "info" and p["states"] == {
        "pending": False,
        "running": False,
        "done": True,
    }
    assert p["result"]["outcome"] == "success" and p["afterLocks"] == 0


def test_an_unconfirmed_stop_keeps_running_and_the_lock_and_writes_no_result(table):
    u = table["unconfirmed"]
    assert u["level"] == "error"
    assert "停止を確認できなかった" in u["text"] and "--confirm-stopped" in u["text"]
    # running と統合ロックを残し、結果 (done) も、pending への戻しもしない
    assert u["states"] == {"pending": False, "running": True, "done": False}
    assert u["result"] is None
    assert u["locks"] == 1 and u["holderIsThisRun"] is True
    # モデルへは、固定の文だけ (再実行しない)
    assert len(u["sent"]) == 1 and "再実行しない" in u["sent"][0]
    assert "停止を確認できない" not in u["sent"][0]  # 証拠の文字列は載せない


def test_a_thrown_executor_is_unconfirmed_when_exclusive_and_unknown_otherwise(table):
    t = table["thrown"]
    assert t["exclusive"]["level"] == "error"
    assert t["exclusive"]["states"] == {"pending": False, "running": True, "done": False}
    assert t["exclusive"]["result"] is None and t["exclusive"]["locks"] == 1
    # 排他でない操作は、従来どおり unknown を記録する
    assert t["plain"]["states"] == {"pending": False, "running": False, "done": True}
    assert t["plain"]["result"]["outcome"] == "unknown"


def test_a_stopped_but_unknown_result_is_recorded_and_the_lock_is_released(table):
    s = table["stopped_unknown"]
    assert s["level"] == "error"
    assert s["states"] == {"pending": False, "running": False, "done": True}
    assert s["result"]["outcome"] == "unknown" and s["result"]["by"] == "executor"
    assert s["locks"] == 0


def test_a_result_that_cannot_be_saved_keeps_the_lock(table):
    f = table["finish_failure"]
    assert f["level"] == "error" and "結果を保存できなかった" in f["text"]
    assert f["locks"] == 1


def test_a_live_holder_blocks_without_running_and_the_record_returns_to_pending(table):
    h = table["held_by_alive"]
    assert h["level"] == "warning" and "排他ロック" in h["text"] and "実行していない" in h["text"]
    assert h["marks"] == []
    assert h["states"] == {"pending": True, "running": False, "done": False}
    assert h["lockStillOthers"] is True


def test_only_a_reserved_and_gone_holder_is_recovered(table):
    r = table["recovered_reserved"]
    assert r["level"] == "info" and r["marks"] == ["execute:stopped_ok"]
    assert r["result"]["outcome"] == "success" and r["locks"] == 0
    assert (
        r["otherRunning"] is True
    )  # 回復したのはロックだけ。止まった試行の running は、人が決める
    s = table["stale_started"]
    assert s["level"] == "warning" and s["marks"] == []
    assert s["states"] == {"pending": True, "running": False, "done": False}
    assert s["lockStillOthers"] is True


def test_the_approver_must_run_inside_the_target_worktree_and_unobservable_is_a_refusal(table):
    r = table["runs_here"]
    for key in ("outside", "unobservable", "thrown"):
        v = r[key]
        # 確認の画面を出す前に断る。実行も、状態の遷移もしない
        assert (
            v["level"] == "warning"
            and v["selects"] == 0
            and v["marks"] == []
            and v["pending"] is True
        )
        assert "統合先" in v["text"]
    assert r["inside"]["level"] == "info" and r["inside"]["marks"] == ["execute:stopped_ok"]


def test_authorize_refuses_before_planning_and_screens(table):
    a = table["authorize"]
    assert a["refused"]["level"] == "warning" and a["refused"]["selects"] == 0
    assert a["refused"]["marks"] == [] and a["refused"]["pending"] is True
    assert "この役割では操作できない" in a["refused"]["text"]
    assert a["seen"] == ["fake_op"]
    assert a["allowed"]["level"] == "info" and a["allowed"]["marks"] == ["execute:stopped_ok"]


def test_resolving_an_exclusive_started_attempt_needs_an_explicit_stop_confirmation_even_if_the_owner_is_gone(
    table,
):
    r = table["resolve_exclusive"]
    no = r["withoutConfirm"]
    assert no["level"] == "warning" and "--confirm-stopped" in no["text"]
    assert no["running"] is True and no["locks"] == 1
    yes = r["withConfirm"]
    assert yes["level"] == "info" and yes["running"] is False and yes["done"] is True
    assert yes["locks"] == 0  # 決着した試行のロックだけ、外す
    assert any("停止" in e and "明示" in e for e in yes["result"]["evidence"])


def test_resolving_another_attempt_does_not_touch_the_lock(table):
    s = table["resolve_scope"]
    assert s["level"] == "info" and s["lockUnchanged"] is True and s["mineRunning"] is True


def test_the_list_shows_the_lock_only_when_there_is_one(table):
    ll = table["list_lock"]
    assert "統合ロック" not in ll["before"]
    assert (
        "統合ロック" in ll["during"]
        and ll["holder"] in ll["during"]
        and "/pending unlock" in ll["during"]
    )


def test_unlock_releases_only_an_orphan_lock_after_confirmation(table):
    u = table["unlock"]
    assert u["orphanOk"] is True
    assert u["dialogOptions"] == ["ロックを外す", "閉じる"]
    assert u["closed"].startswith("閉じた") and u["afterClose"] == 1
    assert u["unlocked"]["level"] == "info" and u["afterUnlock"] == 0
    assert "ロックは無い" in u["none"]
    # 実行中の試行 (running) があるロックは、外さない (resolve が外す)
    assert u["refused"]["level"] == "warning" and "resolve" in u["refused"]["text"]
    assert u["refused"]["locks"] == 1 and u["refused"]["running"] is True


def test_an_exclusive_operation_with_a_bare_unknown_or_malformed_result_is_unconfirmed(table):
    f = table["fail_closed"]
    for key in ("plainUnknown", "invalid"):
        v = f[key]
        # 停止を確かめられない: running とロックを残し、結果は書かない
        assert v["level"] == "error" and v["result"] is None and v["locks"] == 1
        assert v["states"] == {"pending": False, "running": True, "done": False}
    # 排他でない操作は、従来どおり unknown を記録する (ロックは無い)
    n = f["invalidNonExclusive"]
    assert n["states"] == {"pending": False, "running": False, "done": True}
    assert n["result"]["outcome"] == "unknown" and n["locks"] == 0


def test_a_holder_naming_a_different_attempt_is_not_recovered(table):
    m = table["mismatch"]
    assert m["level"] == "warning" and m["marks"] == [] and m["pending"] is True
    assert m["lockStillOthers"] is True


def test_authorize_that_throws_refuses(table):
    a = table["authorize_throw"]
    assert a["level"] == "warning" and a["marks"] == [] and a["selects"] == 0
    assert a["pending"] is True


def test_the_strict_running_read_and_the_probe_never_fold_failures_into_absent(table):
    s = table["strict"]
    assert s["absent"] == "absent"
    assert s["present"] == {"state": "present", "matches": True}
    # symbolic ref (dangling・loop を含む)・不正な id は、「無い」と言わず読み取り失敗にする
    assert (
        s["dangling"] == "unreadable" and s["loop"] == "unreadable" and s["badId"] == "unreadable"
    )
    # 壊れた loose ref (列挙に警告が出て落ちる)、実在する ref を指す symbolic ref (列挙されるが symref が立つ) も、「無い」と言わない
    assert s["garbage"] == "unreadable" and s["symbolicToExisting"] == "unreadable"
    # 存在しないオブジェクトを指す ref は ref としてはある。試行を読めないので、probe が読めないとする
    assert s["missingObject"] == "present"
    p = s["probes"]
    assert p["missingObject"] == {"attempt": "unreadable", "owner": "unknown"}
    assert p["absent"] == {"attempt": "absent", "owner": "unknown"}
    assert p["dangling"] == {"attempt": "unreadable", "owner": "unknown"}
    assert p["loop"] == {"attempt": "unreadable", "owner": "unknown"}
    assert p["mismatch"] == {"attempt": "mismatch", "owner": "unknown"}
    assert p["reserved"] == {"attempt": "reserved", "owner": "alive"}
