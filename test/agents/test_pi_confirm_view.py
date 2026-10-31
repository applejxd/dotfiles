"""bypass でも出す確認 (``home/dot_config/pi/harness/confirm-view.ts``) の表試験。

``test/agents/pi/confirm_view_driver.mjs`` が confirm-view.ts を読んで結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/guard/pi-guard.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "confirm_view_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_control_characters_are_made_visible_but_newline_and_tab_stay(table):
    s = table["sanitize"]
    assert s["ansi"] == "a\\x1b[31mred\\x1b[0m"
    assert s["keep"] == "a\tb\nc"
    assert s["ctl"] == "a\\x00b\\x07c\\x0dd\\x7fe\\u{202e}f\\u{200b}"


def test_shell_words_handle_quotes_and_refuse_expansions(table):
    w = table["words"]
    assert w["plain"] == ["gh", "pr", "create", "--title", "a b", "-b", "c d"]
    assert w["escape"] == ["a b", 'x"y']
    assert w["continuation"] == ["a", "b"]
    for key in ("subst", "dquote_dollar", "pipe", "open"):
        assert w[key] is None, key


def _gh(table, key):
    got = table["gh"][key]
    assert got is not None, key
    return got


def test_gh_long_short_and_equals_forms(table):
    got = _gh(table, "create")
    assert (got["title"], got["body"], got["repo"]) == ("T", "B", "o/r")
    got = _gh(table, "short_attached")
    assert (got["title"], got["body"], got["base"], got["head"]) == ("T", "B", "main", "feat")
    got = _gh(table, "eq")
    assert (got["kind"], got["title"], got["body"]) == ("issue", "T", "B")
    assert got["others"] == ["--label bug"]


def test_gh_multiline_body_positional_and_bundled_flags(table):
    assert _gh(table, "multiline")["body"] == "line1\nline2"
    assert _gh(table, "multiline")["positional"] == ["12"]
    assert _gh(table, "bundle")["title"] == "T"
    assert _gh(table, "review")["body"] == "ok"
    assert _gh(table, "close_comment")["others"] == ["--comment bye"]
    assert _gh(table, "close_comment")["positional"] == ["7"]
    assert _gh(table, "merge")["positional"] == ["3"]
    assert _gh(table, "positional_dashdash")["positional"] == ["9"]
    assert _gh(table, "body_file")["bodyFile"] == "body.md"


@pytest.mark.parametrize(
    "key",
    [
        "unknown_flag",
        "missing_value",
        "chained",
        "subst",
        "not_gh",
        "other_action",
        "bool_with_value",
    ],
)
def test_gh_forms_that_cannot_be_read_are_not_parsed(table, key):
    assert table["gh"][key] is None


def test_view_shows_the_full_command_and_a_labelled_reference(table):
    v = table["view"]["basic"]
    assert v["kind"] == "confirm"
    assert "bypass でも確認が要る" in v["title"]
    assert "gh pr create --title T --body B -R o/r" in v["body"]
    assert "解析結果 (参考。実際に実行されるのは上のコマンド)" in v["body"]
    for line in ("title: T", "body: B", "repo: o/r"):
        assert line in v["body"], v["body"]
    assert "理由: 確認が必要な外部への送信・公開" in v["body"]


def test_the_command_is_never_truncated_and_unparsed_forms_have_no_reference(table):
    v = table["view"]["full_command"]
    assert "z" * 20000 in v["body"]
    assert "解析結果" not in v["body"]
    assert "解析結果" not in table["view"]["unparsed"]["body"]


def test_ansi_in_the_command_and_body_is_made_visible(table):
    body = table["view"]["ansi"]["body"]
    assert "\x1b" not in body and "\\x1b[31mred" in body


def test_body_file_is_read_and_shown(table):
    v = table["view"]["body_file"]
    assert v["kind"] == "confirm"
    assert "本文の 1 行目\n2 行目" in v["body"]
    assert v["bodyFile"] == {"path": "body.md", "text": "本文の 1 行目\n2 行目"}


@pytest.mark.parametrize("key", ["body_file_missing", "body_file_stdin"])
def test_unreadable_body_file_blocks_without_a_confirmation(table, key):
    v = table["view"][key]
    assert v["kind"] == "block"
    assert "本文のファイルを読めないので確認できない" in v["reason"]


def test_too_long_text_blocks_but_the_limit_itself_is_allowed(table):
    for key in ("body_file_big", "long_over"):
        v = table["view"][key]
        assert v["kind"] == "block" and "本文が長すぎて確認できない" in v["reason"], key
    assert table["view"]["long_inline"]["kind"] == "confirm"


def test_confirm_results_are_told_apart_by_elapsed_time(table):
    assert table["classify"] == {
        "approved": "approved",
        "denied": "denied",
        "timeout": "timeout",
        "aborted": "aborted",
        "error": "error",
    }


def test_outcome_reasons_tell_the_model_what_to_do(table):
    r = table["reasons"]
    assert "再試行せず" in r["timeout"] and "新しい指示を待つ" in r["timeout"]
    assert "同じ操作をくり返さない" in r["denied"]
    assert "再試行せず" in r["error"]
    assert r["approved"] == ""


def test_timeout_seconds_come_from_the_rules_with_a_safe_default(table):
    t = table["timeout"]
    assert t["set"] == 7
    for key in ("default", "zero", "float", "string", "missing"):
        assert t[key] == 300, key


def test_the_integration_confirmation_has_its_own_title_and_lead(table):
    v = table["integration_view"]
    assert v["kind"] == "confirm"
    assert "保護ブランチへの統合" in v["title"] and "外部への送信" not in v["title"]
    assert (
        "保護ブランチ (develop など) への統合" in v["body"]
        and "内容を確認してから承認" in v["body"]
    )
    assert "git flow feature finish x" in v["body"] and "理由:" in v["body"]
    # 見出しと同じ接頭辞と、コマンドの再掲を理由に繰り返さない
    assert (
        "確認が必要な保護ブランチへの統合" not in v["body"]
        and "実行しようとしているコマンド" not in v["body"]
    )
    assert v["body"].count("git flow feature finish x") == 1
    assert (
        v["body"].rstrip().endswith("理由: git flow feature finish (保護ブランチへ統合・削除する)")
    )
    # 外部送信の確認の見出しと導入は、そのまま
    basic = table["view"]["basic"]
    assert "外部への送信・公開" in basic["title"] and "保護ブランチ" not in basic["body"]


# --- git flow finish の確認 (統合の内容と squash メッセージ) ---


def test_finish_target_is_read_only_from_a_plain_leading_command(table):
    f = table["finish"]
    assert f["target_plain"] == {"topic": "feature", "name": "x", "branch": "feature/x"}
    assert f["target_prefixed"] == {"topic": "bugfix", "name": "bugfix/y", "branch": "bugfix/y"}
    # release・hotfix、cd や && が付く形、名前より先のオプションは、解釈しない
    for key in ("target_other", "target_chained", "target_flag_first"):
        assert f[key] is None, key


def test_squash_message_forms(table):
    f = table["finish"]
    assert f["msg_none"] is None
    assert f["msg_eq_dq"] == {"kind": "literal", "text": "a b\nc"}
    assert f["msg_space_sq"] == {"kind": "literal", "text": "a $b"}
    assert f["msg_bare"] == {"kind": "literal", "text": "docs:one"}
    # `"$(cat <path>)"` だけをファイルとして読む。オプションに見える引数・ほかの展開は、解かない
    assert f["msg_file"] == {"kind": "file", "path": "msg.txt"}
    assert f["msg_file_unquoted"] == {"kind": "file", "path": "dir/msg.txt"}
    for key in ("msg_file_option_like", "msg_other_subst", "msg_var"):
        assert f[key]["kind"] == "unresolved", key


def test_numstat_keeps_binary_as_null(table):
    assert table["finish"]["numstat"] == [
        {"path": "a.md", "add": 3, "del": 1},
        {"path": "b.png", "add": None, "del": None},
    ]


def test_finish_view_shows_the_integration_summary_and_the_literal_message(table):
    v = table["finish"]["view_literal"]
    assert v["kind"] == "confirm" and "bodyFile" not in v
    body = v["body"]
    assert "統合の内容: feature/x → develop (squash)" in body
    assert "コミット: 7 件" in body and "eee5555 件名 5" in body and "fff6666" not in body
    assert "… ほか 2 件" in body
    assert "変更: 11 ファイル (+55 −5)" in body
    # 変更の大きいファイルから 8 件、残りは件数
    assert (
        body.index("docs/f9.md (+9 −1)")
        < body.index("docs/f10.md (+10 −0)")
        < body.index("docs/f4.md")
    )
    assert "docs/f1.md" not in body and "… ほか 3 ファイル" in body
    assert "squash メッセージ:\n  docs: 件名\n\n  本文" in body
    # 理由は最後のまま
    assert body.rstrip().endswith("理由: git flow feature finish (保護ブランチへ統合・削除する)")


def test_finish_view_reads_the_message_file_and_pins_it(table):
    v = table["finish"]["view_file"]
    assert v["kind"] == "confirm"
    assert "squash メッセージ (ファイル msg.txt の内容。ハーネスが読んだもの):" in v["body"]
    assert (
        "  docs: 件名\n\n  本文の 1 行目\n\n理由:" in v["body"]
    )  # 末尾の改行は落とす ($(cat) と同じ)
    # 承認の後に変わったら実行を止めるための印 (index.ts の execute() が読み直して比べる)
    assert v["bodyFile"] == {"path": "msg.txt", "text": "docs: 件名\n\n本文の 1 行目\n\n"}


def test_finish_view_does_not_block_when_the_message_cannot_be_shown(table):
    f = table["finish"]
    missing = f["view_file_missing"]
    assert missing["kind"] == "confirm" and "bodyFile" not in missing
    assert (
        "squash メッセージ: nope.txt を読めない。確認画面では見せられない (実行時に読まれる)"
        in missing["body"]
    )
    assert "統合の内容: feature/x → develop (squash)" in missing["body"]
    unresolved = f["view_unresolved"]
    assert unresolved["kind"] == "confirm" and "bodyFile" not in unresolved
    assert (
        "squash メッセージ: コマンド置換や変数を含むので、確認画面では展開できない"
        in unresolved["body"]
    )


def test_a_long_message_is_clipped(table):
    body = table["finish"]["view_file_long"]["body"]
    assert "y" * 3000 in body and "y" * 3001 not in body
    assert "以降は省略" in body


def test_the_summary_follows_the_flags_and_the_git_result(table):
    f = table["finish"]
    assert "統合の内容: feature/x → develop (squash)\n" in f["view_no_message"]["body"]
    assert "squash メッセージ" not in f["view_no_message"]["body"]
    assert "統合の内容: feature/x → develop\n" in f["view_no_squash"]["body"]
    failed = f["view_facts_failed"]["body"]
    assert "(取得できなかった: git が失敗した (終了コード 128))" in failed
    # git の結果が無くても、メッセージは見せる
    no_facts = f["view_no_facts"]["body"]
    assert "統合の内容" not in no_facts and "squash メッセージ:\n  abc" in no_facts


@pytest.mark.parametrize("key", ["view_not_finish", "view_other_reason"])
def test_other_confirmations_are_unchanged(table, key):
    body = table["finish"][key]["body"]
    assert "統合の内容" not in body and "squash メッセージ" not in body


def test_control_characters_in_the_message_are_made_visible(table):
    body = table["finish"]["view_ansi"]["body"]
    assert "\x1b" not in body and "a\\x1b[31mred" in body
