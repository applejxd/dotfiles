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
