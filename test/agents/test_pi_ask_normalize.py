"""ask の引数の正規化 (``home/dot_pi/agent/extensions/ask/normalize.ts``) の表試験。

``test/agents/pi/ask_normalize_driver.mjs`` が normalize.ts を読んで結果を JSON で出す
(node の型除去を使うので、22.18 未満の node では飛ばす)。

see docs/spec/guard/pi-guard.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "ask_normalize_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

OPTS = [
    {"label": "A (推奨)", "description": "da"},
    {"label": "B", "description": "db"},
]


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


def test_a_correct_input_is_returned_untouched(table):
    assert table["good"]["same"] is True
    assert table["good"]["output"] == table["good"]["input"]


def test_top_level_question_and_options_are_wrapped(table):
    out = table["top_level"]["output"]
    assert out == {"questions": [{"question": "Q?", "header": "H", "options": OPTS, "multi": True}]}


def test_top_level_question_moves_into_the_first_element_without_one(table):
    assert table["top_question"]["output"] == {"questions": [{"question": "Q?", "options": OPTS}]}
    two = table["top_question_two"]["output"]["questions"]
    assert [q["question"] for q in two] == ["Keep", "Q?"]
    assert "question" not in table["top_question_two"]["output"]


def test_header_becomes_the_question_when_it_is_missing(table):
    assert table["header_only"]["output"]["questions"][0] == {
        "header": "H",
        "question": "H",
        "options": OPTS,
    }


def test_string_options_become_label_and_description(table):
    options = table["string_options"]["output"]["questions"][0]["options"]
    assert options == [
        {"label": "A (推奨)", "description": "A (推奨)"},
        {"label": "B", "description": "B"},
    ]


def test_questions_given_as_a_json_string_are_parsed(table):
    assert table["json_string"]["output"] == {"questions": [{"question": "Q?", "options": OPTS}]}


def test_an_unparsable_json_string_is_left_alone(table):
    assert table["bad_json_string"]["same"] is True


def test_multi_strings_become_booleans(table):
    qs = table["multi_string"]["output"]["questions"]
    assert [q["multi"] for q in qs] == [True, False]


def test_a_missing_description_is_filled_with_the_label(table):
    options = table["no_description"]["output"]["questions"][0]["options"]
    assert options[0] == {"label": "A (推奨)", "description": "A (推奨)"}
    assert options[1] == {"label": "B", "description": "db"}


def test_meaning_changing_completions_are_not_made(table):
    # 推奨の印は付けず、選択肢も足さない。変更が無いので同一の参照を返す
    assert table["no_recommended"]["same"] is True
    assert table["no_recommended"]["output"] == table["no_recommended"]["input"]


def test_unknown_keys_are_kept_and_unfixable_input_is_unchanged(table):
    assert table["unknown_key"]["same"] is True
    for key in ("not_object", "null_input", "nothing", "top_without_options"):
        assert table[key]["same"] is True, key
