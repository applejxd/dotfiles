"""git_commit の確認の表示 (``home/dot_config/pi/harness/actions.ts`` の要約・「全文を見る」・編集)。

``test/agents/pi/action_view_driver.mjs`` が、偽の ctx (TUI 相当) で ``executeAction`` を直接動かして結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。RPC の経路は ``test_pi_actions_harness.py`` が見る。

see docs/spec/guard/pi-extensions.md#guarded_action
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "action_view_driver.mjs"
APPROVE, VIEW, EDIT, REJECT = "承認して実行", "全文を見る", "編集して承認", "拒否"

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


def test_the_summary_threshold_is_lines_chars_and_files(table):
    n = table["needs"]
    # 小さい変更は、要約せずに全文を出す (本文 5 行・300 字・ファイル 5 件が境界)
    assert n["small"] is False
    assert n["lines5"] is False and n["lines6"] is True
    assert n["chars300"] is False and n["chars301"] is True
    assert n["files5"] is False and n["files6"] is True
    # git_commit 以外 (gh の投稿) と、プレビューの無い呼び出しは、要約しない
    assert n["not_commit"] is False and n["no_preview"] is False


def test_the_summary_shows_the_subject_the_size_and_the_top_files(table):
    s = table["summary"]
    # 件名が最初の行。絶対パスは出さない (狭い画面で折り返す)。作業ツリーの最後の要素と、ブランチ、短縮 HEAD は、件名と全文の行数のあと
    lines = s.splitlines()
    assert lines[0] == "feat: subject line" and "message:" not in s
    assert lines[1] == "  (全 7 行・39 字。「全文を見る」で全文)"
    assert lines[2] == "repo child main @ aaaaaaaa" and "/work" not in s
    # 本文の 2 行目以降は要約に出さない
    assert "- a" not in s
    # ファイルは上位 5 件と残りの件数、合計の行 (棒グラフは出さない)
    assert s.count(".txt  1") == 5 and "他 3 ファイル" in s and "8 files +8 -0" in s
    assert "|" not in s and "+++" not in s
    assert len(s.splitlines()) <= 14


def test_the_summary_prefers_the_dir_argument_over_the_absolute_path(table):
    s = table["summary_dir"]
    assert s.splitlines()[2] == "dir .tmp/worktrees/x main @ aaaaaaaa" and "/very/long" not in s


def test_the_summary_lines_fit_a_narrow_terminal_counting_wide_characters_twice(table):
    u = table["util"]
    assert (u["width_ascii"], u["width_cjk"]) == (3, 6)
    assert u["clip_none"] == "abc" and u["clip_ascii"] == "abcd…" and u["clip_cjk"] == "日本語…"
    lines = table["summary_narrow"].splitlines()
    assert lines[0].endswith("…") and lines[1].endswith("…")
    assert all(w <= 38 for w in (_width(line) for line in lines)), lines


def _width(s: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def test_the_stat_drops_the_bar_graph_and_keeps_the_exact_totals(table):
    u = table["util"]
    # 棒グラフの +/- は縮尺されて正確ではないので、ファイルごとは変更行の合計だけ。正確な内訳は合計行
    assert u["stat"].splitlines() == [
        "docs/a.md  1",
        "src/b.ts  102",
        "img.png  bin",
        "3 files +70 -33",
    ]
    assert u["stat_one"] == "1 file +1 -0"


def test_the_full_details_also_go_to_the_chat_but_the_dialog_keeps_the_summary(table):
    # TUI で途中経過が描かれるかは未確認。描かれなくても、見ずに承認することはないように、ダイアログに要約を残す
    big = table["big_approve"]["calls"]
    assert (
        len(big["progress"]) == 1
        and "- a" in big["progress"][0]
        and "実行する argv" in big["progress"][0]
    )
    assert (
        "feat: subject line" in big["select"][0]["title"].split("\n")[2]
    )  # 見出し・空行の次が件名
    assert table["small_commit"]["calls"]["progress"] == []  # 小さい変更はダイアログに全文


def test_a_small_commit_shows_the_full_text_without_a_view_option(table):
    r = table["small_commit"]
    (call,) = r["calls"]["select"]
    assert call["options"] == [APPROVE, EDIT, REJECT]
    assert "message (全文):\nfix: small" in call["title"] and "実行する argv" in call["title"]
    assert r["result"]["ok"] is True and r["advanced"] is True


def test_a_big_commit_shows_a_summary_with_a_view_option(table):
    r = table["big_approve"]
    (call,) = r["calls"]["select"]
    assert call["options"] == [APPROVE, VIEW, EDIT, REJECT]
    assert "feat: subject line" in call["title"] and "実行する argv" not in call["title"]
    assert "- a" not in call["title"]  # 本文の 2 行目以降は、要約には出ない
    assert r["calls"]["editor"] == []
    assert (
        r["result"]["ok"] is True and r["advanced"] is True and r["subject"] == "feat: subject line"
    )


def test_the_view_option_opens_the_full_text_and_returns_to_the_same_confirmation(table):
    r = table["big_view_then_approve"]
    assert len(r["calls"]["select"]) == 2  # 全文を見たあと、同じ確認に戻る
    assert r["calls"]["select"][0] == r["calls"]["select"][1]
    (ed,) = r["calls"]["editor"]
    assert "全文" in ed["title"] and "読むだけ" in ed["title"]
    for needle in ("- a", "- e", "実行する argv", "プレビュー:"):
        assert needle in ed["text"], ed["text"]
    # 見ただけでは、内容は変わらない (承認した内容のとおりに実行する)
    assert (
        r["result"]["ok"] is True and r["advanced"] is True and r["subject"] == "feat: subject line"
    )


def test_viewing_twice_and_then_refusing_does_not_commit(table):
    r = table["big_view_twice_then_reject"]
    assert len(r["calls"]["select"]) == 3 and len(r["calls"]["editor"]) == 2
    assert r["result"]["ok"] is False and r["result"]["text"].startswith("not approved:")
    assert r["advanced"] is False


def test_the_result_repeats_the_text_only_when_it_was_edited(table):
    # 承認した内容のとおりなら、本文は再掲しない (承認した画面と同じなので)。編集したときだけ、実際に使った内容を返す
    for key in ("small_commit", "big_approve", "big_view_then_approve"):
        text = table[key]["result"]["text"]
        assert (
            "実行した内容は、承認した内容のとおり" in text and "実際に使った最終の内容" not in text
        ), key
    edited = table["big_edit"]
    assert edited["result"]["ok"] is True and edited["advanced"] is True
    assert edited["subject"] == "feat: edited subject"
    assert "実際に使った最終の内容 (編集した):" in edited["result"]["text"]
    assert "feat: edited subject" in edited["result"]["text"]
