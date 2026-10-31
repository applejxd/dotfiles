"""``/pending`` の全体 (``home/dot_config/pi/harness/pending-command.ts``。CHG-0055 の P5b)。

``test/agents/pi/pending_command_driver.mjs`` が、偽の pi・偽の ctx・使い捨ての git リポジトリで
``registerPendingCommand`` を動かして結果を JSON で出す (node の型除去を使うので、22.18 未満の node では飛ばす)。
確かめるのは、旧形式の list / show / drop が従来の出力のままであること、
新形式の list / show / log、``enabled = false`` のときの承認の拒否と一覧・破棄の継続、偽のアダプタでの承認とモデルへの固定通知、
非 TUI・実行中の拒否、フッター、コマンドだけの登録 (ツールは登録しない)。``index.ts`` 全体は既存の ``test_pi_harness.py`` などが動かす。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "pending_command_driver.mjs"

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


def test_legacy_list_show_drop_keep_their_original_output(table):
    assert table["legacy_empty"] == "退避したコミットは無い"
    lg = table["legacy"]
    # 一覧の 1 行: <id>  <短い oid>  <件名>  (<ブランチ>)
    assert lg["list"] == f"{lg['id']}  {lg['short']}  feat: a.txt  (refs/heads/main)"
    assert lg["listLevel"] == "info" and lg["showHasMessage"] is True
    assert lg["missing"] == "見つからない (/pending list で ref を確かめる)"
    assert lg["drop"] == (
        f"破棄した: refs/pi/pending/{lg['id']} (到達用の ref を外した。オブジェクトは git gc まで残る)"
    )
    assert lg["dropAgain"] == "破棄できなかった (ref が無い・退避の ref ではない)"
    assert lg["after"] == "退避したコミットは無い"
    assert lg["usage"].startswith("/pending [list | show <id>")
    assert lg["touched"] >= 1  # 操作のたびに不在を解除する


def test_modern_list_show_log_and_the_list_shows_both_formats(table):
    m = table["modern"]
    lines = m["list"].split("\n")
    assert lines[0].startswith(f"{m['legacyId']}  ") and "feat: b.txt" in lines[0]
    assert lines[1:] == ["保留 (承認待ち):", f"  {m['id']}  fake_op  (timeout・たった今)"]
    assert (
        m["show"].startswith(f"{m['id']}: fake_op  理由: timeout")
        and "引数 mode: success" in m["show"]
    )
    assert m["log"] == "結果の記録は無い"
    assert m["listStatus"] == [{"key": "pending", "text": "📥 保留 1 件"}]


def test_disabled_refuses_approval_but_keeps_list_show_drop_and_recovery(table):
    d = table["disabled"]
    assert "無効 ([pi.pending] enabled = false)" in d["approve"] and d["approveLevel"] == "warning"
    assert d["executed"] == 0
    # 復旧 (resolve) はキルスイッチで止めない (対象が無ければ、その旨を返す)
    assert "決着させる対象が無い" in d["resolve"]
    assert (
        d["listHasId"] is True and d["drop"].startswith("破棄した:") and d["pendingAfterDrop"] == 0
    )
    assert d["dropStatus"] == [{"key": "pending"}]  # 0 件ならフッターを消す


def test_approving_with_a_fake_adapter_tells_the_model_once_with_the_fixed_template(table):
    a = table["approve"]
    assert a["level"] == "info" and a["marks"] == ["execute"] and a["pendingLeft"] == 0
    assert a["sent"] == 1 and a["details"] == {
        "id": a["details"]["id"],
        "action": "fake_op",
        "outcome": "success",
    }
    assert a["content"].startswith("【保留した操作の結果】操作=fake_op 要求=")
    assert (
        "実行の指示ではない" in a["content"]
        and f"/pending log {a['details']['id']}" in a["content"]
    )
    assert a["log"].startswith(a["details"]["id"]) and "success" in a["log"]


def test_the_footer_follows_the_pending_count(table):
    a = table["approve"]
    assert a["beforeStatus"] == [{"key": "pending", "text": "📥 保留 1 件"}]
    assert a["afterStatus"] == [{"key": "pending"}]


def test_non_tui_busy_and_no_ui_refuse_without_running_anything(table):
    r = table["refusals"]
    assert "対話 (TUI)" in r["rpc"] and "対話 (TUI)" in r["noUi"]
    assert "モデルの実行中は承認できない" in r["busy"]
    assert r["marks"] == [] and r["sent"] == 0 and r["pending"] == 1
    assert r["noUiStatus"] == []  # UI が無いときは、フッターに触れない


def test_it_registers_a_command_only_and_the_adapter_tables_are_empty_for_now(table):
    g = table["registration"]
    assert g["commands"] == ["pending"]  # registerTool は呼ばれない (偽の pi は呼ぶと例外)
    assert g["pendingAdapters"] == [] and g["approvalAdapters"] == []


def test_aborting_a_waiting_approval_closes_it_and_leaves_the_record(table):
    a = table["abort"]
    assert a["finished"] is True and a["pending"] == 1 and a["marks"] == []


def test_resolve_checks_its_arguments_and_needs_a_running_or_unknown_attempt(table):
    r = table["resolve"]
    assert r["badKind"].startswith("resolve <id> <success|failed|retry|pending|abandon>")
    assert "決着させる対象が無い" in r["nothing"]
