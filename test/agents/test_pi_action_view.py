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


def test_the_commit_confirmation_is_always_a_summary_in_the_tui(table):
    n = table["needs"]
    # 小さい変更も要約する (狭い画面で、全角の本文・プレビュー・argv が折り返して大きくなるため)。境界の数値は無い
    for key in ("small", "lines5", "lines6", "chars300", "chars301", "files5", "files6"):
        assert n[key] is True, key
    # git_commit 以外 (gh の投稿) と、プレビューの無い呼び出しは、要約しない
    assert n["not_commit"] is False and n["no_preview"] is False


def test_the_summary_is_a_labeled_bullet_list_in_a_fixed_order(table):
    s = table["summary"]
    # リポジトリ名・ブランチ・件名の順。絶対パスは出さない (狭い画面で折り返す)。作業ツリーの最後の要素と、ブランチ、短縮 HEAD
    lines = s.splitlines()
    assert lines[:4] == [
        "・リポジトリ: child",
        "・ブランチ: main @ aaaaaaaa",
        "・件名: feat: subject line",
        "・変更: 8 files +8 -0",
    ]
    assert "/work" not in s and "message:" not in s and "本文" not in s
    # 本文の 2 行目以降は要約に出さない (本文の大きさの行も出さない)
    assert "- a" not in s
    # ファイルは上位 5 件と残りの件数を、変更の下に字下げで (棒グラフは出さない)
    assert [line for line in lines[4:] if line.startswith("    ")] == [
        f"    f{i}.txt  1" for i in range(5)
    ] + ["    … 他 3 ファイル"]
    assert "|" not in s and "+++" not in s
    assert len(lines) <= 11


def test_the_summary_prefers_the_dir_argument_over_the_absolute_path(table):
    s = table["summary_dir"]
    assert s.splitlines()[0] == "・リポジトリ: x" and "/very/long" not in s and ".tmp" not in s


def test_the_summary_shows_only_the_last_path_element_unless_names_collide(table):
    # 同名が無いファイルだけ最後の要素にする。同名 (a.ts)・リネーム表記 (=>)・要約の行はそのまま
    assert table["shorten"] == [
        "docs/a.ts  1",
        "src/a.ts  2",
        "b.ts  102",
        "logo.png  bin",
        "x/{a => b}/c.ts  3",
        "… 他 2 ファイル",
    ]


def test_the_summary_lines_fit_a_narrow_terminal_counting_wide_characters_twice(table):
    u = table["util"]
    assert (u["width_ascii"], u["width_cjk"]) == (3, 6)
    assert u["clip_none"] == "abc" and u["clip_ascii"] == "abcd…" and u["clip_cjk"] == "日本語…"
    lines = table["summary_narrow"].splitlines()
    assert all(w <= 38 for w in (_width(line) for line in lines)), lines
    # 件名は切らずに、字下げして折り返す (なくなる字が無い)
    end = next(i for i, line in enumerate(lines) if line.startswith("・変更"))
    subject = lines[2:end]
    assert subject[0].startswith("・件名: feat: ") and all(
        line.startswith("    ") for line in subject[1:]
    )
    assert len(subject) >= 2 and "…" not in "".join(subject)
    assert "長い件名" * 10 in "".join(line.removeprefix("・件名: ").strip() for line in subject)
    # 異常に長い件名でも、件名は 5 行までで末尾を … にする
    long = table["summary_long_subject"].splitlines()
    body = long[2:7]
    assert (
        body[-1].endswith("…")
        and long[7].startswith("・変更")
        and all(_width(line) <= 44 for line in long)
    )
    # ブランチ名が長いときはブランチ名を縮め、短縮 HEAD は残す (幅 46)
    branch = table["summary_long_branch"].splitlines()[1]
    assert (
        branch.startswith("・ブランチ: feature/x")
        and "…" in branch
        and branch.endswith(" @ aaaaaaaa")
        and _width(branch) <= 44
    )


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
    assert "・件名: feat: subject line" in big["select"][0]["title"].split(
        "\n"
    )  # 見出し・空行、リポジトリ、ブランチの次が件名
    # 小さい変更も、詳細をチャットに出し、ダイアログは要約
    assert len(table["small_commit"]["calls"]["progress"]) == 1


def test_a_small_commit_is_also_a_summary_with_a_view_option(table):
    r = table["small_commit"]
    (call,) = r["calls"]["select"]
    assert call["options"] == [APPROVE, VIEW, EDIT, REJECT]
    assert (
        "・件名: fix: small" in call["title"].split("\n") and "実行する argv" not in call["title"]
    )
    assert "message (全文)" not in call["title"] and "プレビュー:" not in call["title"]
    assert "実行する argv" in r["calls"]["progress"][0]
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


def test_the_view_option_falls_back_to_the_editor_without_the_custom_ui(table):
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


def test_the_full_text_viewer_starts_at_the_head_and_scrolls(table):
    # pi の editor は末尾にカーソルを置くので末尾から見える。全文ビューアは先頭から出し、スクロールできる
    r = table["big_view_viewer"]
    assert r["calls"]["editor"] == []  # editor は使わない
    assert len(r["calls"]["select"]) == 2 and r["result"]["ok"] is True and r["advanced"] is True
    (v,) = r["calls"]["viewer"]
    head = table["big_view_then_approve"]["calls"]["editor"][0]["text"].split("\n")[0]
    # 先頭: 見出し、本文の 1 行目から。末尾の注意書きはまだ見えない
    assert "全文" in v["first"][0] and v["first"][1].strip() == head
    assert not any("退避" in line for line in v["first"])
    assert (
        "↑↓ Space/b g/G" in v["first"][-1]
        and v["first"][-1].startswith("1-")
        and " / " in v["first"][-1]
    )
    # Space で 1 ページ進み、g で先頭へ戻り、G で末尾 (注意書き) へ進む。q で閉じる
    assert v["paged"][1] != v["first"][1] and v["home"] == v["first"]
    assert any("退避" in line for line in v["end"])
    assert v["closed"] is True
    assert all(_width(line) <= 46 for line in v["first"] + v["paged"] + v["end"])


def test_the_viewer_wraps_by_cell_width_keeping_blank_lines(table):
    # 全角は 2 桁。改行と空行は保ち、タブは空白 2 つにする。幅を超える行は折り返す (切り捨てない)
    assert table["wrap"] == ["日本語の", "テスト", "", "abcdefgh", "ij  x"]


def test_the_summary_prefers_the_given_main_repository_name(table):
    # worktree のディレクトリ名 (ブランチ名と重複する) ではなく、本体のリポジトリ名を出す。渡されなければ今までどおり
    assert table["summary_repo_label"].splitlines()[0] == "・リポジトリ: chezmoi"
    assert table["summary_dir"].splitlines()[0] == "・リポジトリ: x"
