"""非同期承認の保存層 (``home/dot_config/pi/harness/pending-ops.ts``。CHG-0055 の P2)。

``test/agents/pi/pending_ops_driver.mjs`` が、使い捨ての git リポジトリで ``pending-ops.ts`` を直接動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。競合の試験は、ドライバーが自分自身を子プロセスとして並行に起動する。
確かめるのは、設計の契約 (記録を信頼しない入力として読む・ref の遷移の排他・段階・結果の 4 値・人の決着・期限・hook を動かさない) の、
保存層に当たる部分。承認の画面・実行・通知は P4 以降。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_ops_driver.mjs"

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


def test_a_saved_record_round_trips_and_leaves_the_repository_untouched(table):
    r = table["roundtrip"]
    assert r["saved"] == {"ok": True, "duplicate": False, "idShape": True, "ref": True}
    assert r["readOk"] and r["sameParams"] and r["kind"] == "action" and r["trailerId"]
    assert (
        r["listed"] == [{"state": "pending", "kind": "action", "id": True}]
        and r["count"] == 1
        and r["keyRefs"] == 1
    )
    # HEAD・ブランチ・インデックス・作業ツリーは動かない (オブジェクトと refs/pi/ だけ)
    assert r["untouched"]


@pytest.mark.parametrize(
    "case",
    [
        "not_json",
        "unknown_key",
        "params_not_string",
        "digest_mismatch",
        "schema_2",
        "extra_file",
        "wrong_file_name",
        "no_kind_trailer",
        "id_mismatch",
        "request_mismatch",
        "too_large",
        "symbolic_ref",
        "bad_id",
    ],
)
def test_forged_or_malformed_records_are_refused(table, case):
    f = table["forged"]
    assert f["baseline"]["ok"] is True  # 同じ作り方の正しい記録は読める (偽造の試験が有効)
    assert f[case]["ok"] is False and f[case]["reason"], case
    assert f["main_unchanged"] is True


def test_format_classification_never_falls_back_to_legacy(table):
    c = table["classify"]
    assert c["legacy"] == "legacy" and c["action"] == "action"
    # 新形式を名乗るのに構造が合わないものと、record.json だけの tree を、旧形式として扱わない
    assert (
        c["legacy_claiming_action"] == "invalid" and c["record_json_without_trailer"] == "invalid"
    )
    assert c["missing_object"] == "invalid"


def test_the_legacy_cleanup_only_touches_legacy_entries(table):
    r = table["legacy_reconcile"]
    # 古い時刻の名前でも、新形式と不正な形式は消さない。旧形式は従来どおり消える
    assert r["newFormatKept"] and r["invalidKept"] and r["legacyDropped"]
    assert r["droppedRefs"] == ["refs/pi/pending/000000000000003"]


def test_duplicate_requests_are_not_created_while_undecided(table):
    d = table["dedupe"]
    assert d["second_is_duplicate"] and d["different_params_new"] and d["worktree_is_part_of_key"]
    # 決着 (success) した後の同じ要求は、新しく作れる。unknown (実行器) の間は作らせず、人が決着させたら作れる
    assert (
        d["after_done_new"]
        and d["unknown_blocks"]
        and d["resolve_unknown_ok"]
        and d["after_resolve_new"]
    )
    assert d["supersedes_plain_rerequest"] is None  # supersedes は retry のときだけ付く
    assert d["keys"] == 3  # 決着した要求の鍵は外れている


def test_concurrent_saves_of_the_same_request_create_exactly_one(table):
    c = table["concurrent_save"]
    assert c["crashes"] == 0 and c["oks"] == 4 and c["created"] == 1 and c["ids"] == 1
    assert c["pendingRefs"] == 1 and c["keys"] == 1


def test_limits_are_enforced_and_never_look_like_no_pending(table):
    lim = table["limits"]
    assert lim["r1"] and lim["r2"] and lim["r3"] == "limit"
    assert lim["duplicate_at_limit"]  # 上限でも、既存と同じ要求は既存を返す
    assert lim["big"] == "invalid" and lim["truncated_save"] == "limit"
    assert lim["list_truncated"] is True and lim["list_len"] == 1
    assert table["invalid_input"] == {"action": "invalid", "param": "invalid", "premise": "invalid"}


def test_begin_approval_is_a_compare_and_swap_with_exclusion(table):
    b = table["begin"]
    assert b["wrongOid"] == "invalid" and b["first"] and b["stage"] == "reserved"
    assert b["pendingGone"] and b["running"] == 1
    assert b["second"] == "mismatch"  # 2 回目は、pending が無く、running が既にあるので失敗する
    assert table["begin_race"] == {"oks": 1, "running": 1}  # 3 プロセスが競合しても、ちょうど 1 つ
    assert table["begin_invalid"] == {"owner": "invalid", "id": "invalid"}


def test_a_swapped_symbolic_ref_does_not_drag_a_normal_branch_along(table):
    s = table["begin_symref_swap"]
    assert s["ok"] is False and s["mainUnchanged"] is True and s["runningCreated"] is False


def test_stages_reserved_and_started(table):
    s = table["stages"]
    assert s["back"] and s["pendingRestored"] and s["runningCleared"]
    assert s["started"] and s["sameAttemptId"]
    assert s["startedTwice"] == "mismatch"  # 古い OID からは、もう進められない
    assert s["returnStarted"] == "refused"  # 開始した試行は、未実行として戻せない
    assert s["startedFromStarted"] == "refused"


@pytest.mark.parametrize("outcome", ["success", "failed_confirmed", "not_executed", "unknown"])
def test_each_outcome_is_recorded_as_done_with_the_attempt_as_parent(table, outcome):
    r = table["results"][outcome]
    assert r["ok"] and r["done"] and not r["running"]
    assert r["result"] == outcome and r["resolvedBy"] == "executor" and r["parentIsAttempt"]
    # 実行器の unknown だけは、人が決着させるまで鍵を残す
    assert r["keyKept"] is (outcome == "unknown")


def test_a_malformed_result_is_refused_and_leaves_the_attempt_running(table):
    b = table["results"]["bad"]
    assert b == {"outcome": "invalid", "list": "invalid", "stillRunning": True}


def test_a_human_cannot_settle_an_attempt_whose_executor_may_be_alive(table):
    r = table["resolve"]
    assert r["alive"] == "refused"
    assert r["unknown_unconfirmed"] == "refused"  # 確認できないときは、利用者の明示が要る
    assert r["stale_oid"] == "mismatch" and r["stage_mismatch_pending"] == "refused"
    assert r["unknown_confirmed"] is True
    assert r["success_result"]["outcome"] == "success" and r["success_result"]["by"] == "human"
    # 利用者が明示したことが、結果の証拠に残る
    assert "利用者が、実行者は止まっていると明示した" in r["success_result"]["evidence"][0]


def test_resolving_by_stage(table):
    r = table["resolve"]
    # 開始前: pending へ戻す・放棄するだけ。成功とは言えない
    assert (
        r["reserved_success_refused"] == "refused"
        and r["reserved_to_pending"]
        and r["reserved_pending_restored"]
    )
    assert r["reserved_abandon"] and r["abandon_outcome"] == "not_executed"
    # 開始後: 結果で決着させる。放棄は不可
    assert (
        r["started_abandon_refused"] == "refused"
        and r["failed"]
        and r["failed_outcome"] == "failed_confirmed"
    )
    # retry は、古い試行を決着させ、新しい要求として作り直す (再承認が要る)
    assert r["retry"] == {
        "ok": True,
        "newPending": True,
        "supersedes": True,
        "oldDone": True,
        "oldRunning": False,
    }
    assert table["resolve_unknown_not_unknown"] == "refused"


def test_retention_removes_only_expired_new_format_entries(table):
    r = table["reconcile"]
    ids = r["ids"]
    assert r["fresh"] == 0
    assert r["later"] == [f"refs/pi/pending/{ids['a']}"]  # 30 日を過ぎた pending
    assert r["muchLater"] == [f"refs/pi/done/{ids['c']}"]  # 90 日を過ぎた結果
    # running と旧形式は、いつまでも消さない
    assert r["runningLeft"] == [f"refs/pi/running/{ids['b']}"]
    assert r["pendingLeft"] == ["refs/pi/pending/000000000000777"]
    assert r["doneLeft"] == [] and r["keysLeft"] == 1  # 残る鍵は、running の分だけ


def test_nothing_runs_from_hooks_or_signing_and_the_repository_is_untouched(table):
    s = table["safe"]
    assert s["allOk"] and s["hookRan"] is False and s["untouched"]


def test_records_made_in_a_linked_worktree_are_visible_and_approvable_from_the_main_one(table):
    assert table["linked"] == {
        "savedInLinked": True,
        "visibleFromMain": True,
        "beganFromMain": True,
    }
