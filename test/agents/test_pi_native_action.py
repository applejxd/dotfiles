"""``executeAction`` 経由の保存専用の操作 (``native-action.ts``。CHG-0055 の P8c)。

``test/agents/pi/native_action_driver.mjs`` が偽の ctx で ``executeAction`` を動かす
(node の型除去を使うので、22.18 未満の node では飛ばす)。確かめるのは、``git_integrate`` が
確認画面にも argv 実行にも進まず保存だけされること、子・無効・mode 外・前提の失敗は拒否で保存しないこと、
argv が空の操作を実行する経路が無いこと。

see docs/change/0055-async-approval.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "native_action_driver.mjs"

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


def test_git_integrate_is_saved_without_a_confirm_or_an_execution(table):
    r = table["ok"]
    assert r["selects"] == []  # 確認画面に進まない
    assert r["result"]["ok"] is False and r["result"]["text"].startswith("not approved:")
    assert r["refs"] == 1 and r["reasons"] == ["request"] and r["headSame"] is True
    assert r["saved"] == [{"action": "git_integrate", "reason": "request", "duplicate": False}]


def test_the_model_is_told_it_was_not_run_and_where_to_approve(table):
    r = table["ok"]
    text = r["result"]["text"]
    assert "未実行" in text and f"保留 {r['id']}" in text and "再試行しない" in text
    assert "/pending approve" in text and "保留した操作" in text
    assert "子" in text and "idle" in text and "依存しない作業を続け" not in text
    # 15 桁の ID を打たせない: 一覧から選ぶ。短く添えるなら末尾 4 桁
    assert "一覧から選ぶ" in text and f"/pending approve {r['id'][-4:]}" in text
    assert f"/pending approve {r['id']}" not in text


def test_a_duplicate_request_is_reported(table):
    r = table["dup"]
    assert (
        r["refs"] == 1
        and r["saved"][0]["duplicate"] is True
        and "すでに保留中" in r["result"]["text"]
    )


@pytest.mark.parametrize("case", ["child", "disabled", "mode", "captureFails"])
def test_a_refused_request_saves_nothing(table, case):
    r = table[case]
    assert r["result"]["ok"] is False and r["refs"] == 0 and r["saved"] == [] and r["selects"] == []
    assert r["headSame"] is True


def test_a_failed_save_says_nothing_was_run_with_the_reason(table):
    text = table["captureFails"]["result"]["text"]
    assert (
        "保存できなかった" in text
        and "実行していない" in text
        and "premise" in text
        and "前提を取れない" in text
    )


def test_an_operation_with_empty_argv_is_never_executed(table):
    r = table["empty"]
    assert r["result"]["ok"] is False and "argv が空の操作は実行できない" in r["result"]["text"]
    assert r["refs"] == 0
