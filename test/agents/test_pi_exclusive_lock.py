"""統合の実行を守る排他ロック (``home/dot_config/pi/harness/exclusive-lock.ts``。CHG-0055 の P8c)。

``test/agents/pi/exclusive_lock_driver.mjs`` が、使い捨ての git リポジトリで ``exclusive-lock.ts`` を直接動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。競合の試験は、ドライバーが自分自身を子プロセスとして並行に起動する。
確かめるのは fail-closed の回復規則: 自動で回復するのは「検証できた同一の試行が reserved で、owner が gone」の 1 通りだけ。
読めない・symbolic・不正なロックは、自動では消えない。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "exclusive_lock_driver.mjs"

pytestmark = [
    pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い"),
    pytest.mark.skipif(
        sys.platform == "win32", reason="Windows は未検証 (POSIX の hook・symlink を使う)"
    ),
]


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


def test_acquire_release_and_double_acquire(table):
    b = table["basic"]
    assert b["a"] == "ok" and b["refUnderLock"] and b["mainUnchanged"]
    assert b["b"] == "held" and b["bHolder"]["attemptId"] == "att-1"
    assert b["readA"]["holder"]["attemptId"] == "att-1" and b["readA"]["hasOwner"]
    # 他者の OID・名前空間外の ref は解放できない
    assert b["bogusRelease"] is False and b["foreignRelease"] is False and b["stillHeld"] == "held"
    assert b["released"] is True and b["missing"] == "missing"
    assert b["relAgain"] is False and b["reacquire"] == "ok"


def test_concurrent_acquire_has_exactly_one_winner(table):
    for r in table["race"]:
        assert r["oks"] == 1 and r["crashes"] == 0 and r["refs"] == 1
        assert set(r["others"]) == {"held"}


@pytest.mark.parametrize("attempt", ["reserved", "started", "absent", "mismatch", "unreadable"])
@pytest.mark.parametrize("owner", ["alive", "gone", "unknown"])
def test_recovery_table_only_reserved_gone_recovers(table, attempt, owner):
    r = table["recovery"][f"{attempt}/{owner}"]
    if (attempt, owner) == ("reserved", "gone"):
        assert r["code"] == "ok" and r["recovered"] == "reserved_gone" and r["kept"]
        return
    assert r["recovered"] is None and r["kept"], "回復していないなら、元のロックが残る"
    expected = {
        "reserved": "held",
        "started": "stale_started" if owner == "gone" else "held",
    }.get(attempt, "unverifiable")
    assert r["code"] == expected


def test_a_failing_probe_is_unverifiable_and_gets_the_holder(table):
    r = table["recovery"]
    assert r["throws"] == {"code": "unverifiable", "kept": True}
    assert r["probeArg"]["attemptId"] == "att-1"


def test_concurrent_recovery_has_exactly_one_winner(table):
    for r in table["recover_race"]:
        assert r["barrierPassed"], "全員が同じ旧ロックを読んで probe に入った"
        assert r["oks"] == 1 and r["recovered"] == 1 and r["crashes"] == 0
        assert set(r["others"]) == {"held"} and len(r["others"]) == 3
        assert r["oldGone"] and r["holderIsWinner"] and r["refs"] == 1
    assert table["new_holder_not_stolen"] == {"code": "held", "kept": True}


def test_stale_handle_never_removes_a_newer_lock(table):
    s = table["stale_handle"]
    assert s["relA"] and s["b"] == "ok"
    assert s["staleRelease"] is False and s["bStillHeld"]
    assert s["recovered"] == "reserved_gone"
    assert s["staleAfterRecovery"] is False and s["recoveredStillHeld"]


@pytest.mark.parametrize(
    "case",
    [
        "not_json",
        "unknown_key",
        "bad_running_id",
        "bad_owner",
        "bad_schema",
        "extra_file",
        "wrong_name",
        "symbolic",
        "missing_object",
        "dangling_symbolic",
        "symbolic_loop",
        "empty_loose",
        "garbage_loose",
        "bad_attempt_id",
        "bad_at",
        "oversize_blob",
    ],
)
def test_invalid_symbolic_or_unreadable_locks_are_never_removed(table, case):
    inv = table["invalid"]
    assert (
        inv["good_baseline"]["state"] == "held"
    )  # 同じ作り方の正しいロックは読める (偽造の試験が有効)
    c = inv[case]
    assert c["state"] in ("invalid", "unreadable"), "不存在に畳まない"
    assert c["code"] in ("invalid_lock", "git_failed")
    assert c["kept"] and c["mainSame"]
    assert c["code"] == ("git_failed" if c["state"] == "unreadable" else "invalid_lock")
    assert inv["symbolic_main_unchanged"] is True


def test_key_is_per_common_dir(table):
    k = table["keys"]
    assert k["shape"] and k["linked"] and k["subdir"] and k["symlink"] and k["gitDirEnvIgnored"]
    assert k["other"], "別リポジトリは別の鍵"
    assert k["sharedLock"] == {"a": "ok", "b": "held"}, "別 worktree からのロックを、本体も見る"
    assert k["relativeCwd"], "相対パスの cwd でも同じ鍵"
    assert k["bare"] == {"key": True, "a": "ok", "b": "held", "read": "held", "rel": True}
    if k["sha256"] is None:
        pytest.skip("git が SHA-256 リポジトリに対応していない")
    assert k["sha256"] == {
        "a": "ok",
        "oidLen": 64,
        "b": "held",
        "read": "held",
        "recovered": "reserved_gone",
        "rel": True,
    }


def test_hooks_and_signing_never_run(table):
    s = table["safe"]
    assert s["acquired"] and s["released"]
    assert s["hookRan"] is False and s["untouched"]


def test_lock_refs_do_not_appear_in_the_pending_list(table):
    r = table["list"]
    assert r["acquired"] and r["onlyPending"] and r["count"] == 1 and r["lockRefs"] == 1
    assert r["lockSurvivesReconcile"]


def test_force_release_is_a_cas_on_the_expected_oid(table):
    f = table["force"]
    assert f["wrong"] is False and f["stillHeld"] == "held"
    assert f["right"] is True and f["again"] is False
    assert f["invalidRelease"] is True, "不正な内容でも、期待 OID が合えば人は消せる"
    assert f["symbolic"] is False and f["mainExists"]


def test_public_api(table):
    assert {"lockKeyOf", "readLock", "acquireLock", "releaseLock", "forceRelease"} <= set(
        table["api"]
    )
