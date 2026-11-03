"""確認の提示 (``home/dot_config/pi/harness/confirm-present.ts`` の ``presentConfirm``)。

``test/agents/pi/confirm_present_driver.mjs`` が、偽の ui で動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。``guarded_action`` の確認 (actions.ts) と、
保留の承認 (CHG-0055) が共用する部品で、選択・期限・取消・「全文を見る」の押し直しだけを持つ。
承認・拒否・時間切れの分類は呼び出し側 (``test_pi_action_view.py`` / ``test_pi_actions_harness.py``) が見る。

see docs/change/closed/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "confirm_present_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_the_chosen_value_is_returned_with_a_backstop_timeout(table):
    c = table["chosen"]
    assert c["result"] == {"choice": "承認して実行", "timedOut": False, "error": False}
    # 組み込みの期限は、自前の期限より遅くして保険にだけ使う
    assert c["select"] == [
        {
            "title": "T",
            "options": ["承認して実行", "全文を見る", "拒否"],
            "opts": {"hasSignal": True, "timeout": 1000 + table["backstop_ms"], "aborted": False},
        }
    ]


def test_no_timeout_means_no_timer_and_no_builtin_timeout(table):
    n = table["no_timeout"]
    assert n["result"] == {"choice": "拒否", "timedOut": False, "error": False}
    assert "timeout" not in n["select"][0]["opts"]  # JSON では undefined のキーが落ちる


def test_the_own_timer_is_the_only_thing_that_reports_a_timeout(table):
    assert table["timeout"] == {"timedOut": True, "error": False}
    # 呼び出し元の中断は時間切れではない
    assert table["caller_abort"] == {"timedOut": False, "error": False}
    assert "choice" not in table["timeout"] and "choice" not in table["caller_abort"]
    # すでに中断されていれば、select には中断済みの signal が渡る
    a = table["already_aborted"]
    assert a["result"] == {"timedOut": False, "error": False}
    assert a["select"][0]["opts"]["aborted"] is True


def test_an_exception_from_select_is_an_error_without_a_choice(table):
    assert table["select_throws"] == {"timedOut": False, "error": True}


def test_view_full_opens_the_viewer_lazily_and_asks_again(table):
    v = table["view_full"]
    assert v["result"] == {"choice": "承認して実行", "timedOut": False, "error": False}
    assert v["selects"] == 2 and v["custom"] == 1 and v["editor"] == 0
    assert v["made"] == 1  # 全文は、押されたときに作る
    nv = table["view_full_not_pressed"]
    assert nv["made"] == 0 and nv["custom"] == 0 and nv["result"]["choice"] == "承認して実行"


def test_view_full_falls_back_to_the_editor_without_custom_ui(table):
    e = table["view_full_editor"]
    assert e["result"]["choice"] == "拒否"
    assert e["editor"] == [{"title": "全文", "text": "本文"}]


def test_a_failing_viewer_returns_to_the_confirmation(table):
    t = table["viewer_throws"]
    assert t["result"]["choice"] == "承認して実行" and t["selects"] == 2


def test_a_failing_second_select_does_not_loop_forever(table):
    s = table["second_select_throws"]
    # 前の選択 (全文を見る) を持ち越さず、error で返る
    assert s["result"] == {"timedOut": False, "error": True} and s["selects"] == 2


def test_view_full_without_content_is_returned_as_is(table):
    w = table["view_full_without_content"]
    assert w["result"]["choice"] == "全文を見る" and w["selects"] == 1
