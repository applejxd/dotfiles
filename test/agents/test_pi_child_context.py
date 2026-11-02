"""`harness/child-context.ts` (契約表の `resolveContext` と `lint`) の表試験。

``test/agents/pi/child_context_driver.mjs`` が純粋な関数を動かし、結果を JSON で出す。
node の型除去を使うので、22.18 未満の node では飛ばす。契約は docs/change/0059-child-context.md §4.1。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DRIVER = HERE / "pi" / "child_context_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def t() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def _ex(text: str, blocks: int) -> dict:
    return {"kind": "extract", "text": text, "blocks": blocks}


def _full(why: str, text: str) -> dict:
    return {"kind": "full", "why": why, "text": text}


def _assert_error(r: dict, *words: str) -> None:
    assert r["kind"] == "error", r
    assert "text" not in r
    for w in words:
        assert w in r["reason"], r["reason"]


# --- 導入前 / 導入済み ---


@pytest.mark.parametrize("key", ["legacy", "legacy_empty", "legacy_heading_only"])
def test_before_adoption_returns_full_text_as_legacy(t, key) -> None:
    r = t["resolves"][key]
    assert r["kind"] == "full" and r["why"] == "legacy"


def test_legacy_text_is_verbatim(t) -> None:
    assert t["resolves"]["legacy"] == _full("legacy", "ただの文\n- 箇条書き\n")


def test_adopted_file_extracts_only_child_blocks(t) -> None:
    r = t["resolves"]["basic"]
    assert r == _ex("子の規則", 1)
    assert "親" not in r["text"]


def test_identifier_may_follow_blank_lines(t) -> None:
    assert t["resolves"]["id_blank_first"] == _ex("X", 1)


def test_headings_outside_blocks_are_allowed(t) -> None:
    assert t["resolves"]["headings_allowed"] == _ex("X", 1)


def test_roles_get_different_extracts(t) -> None:
    r = t["resolves"]
    assert r["role_differs_explore"] == _ex("E", 1)
    assert r["role_differs_review"] == _ex("R", 1)


def test_multiple_blocks_join_with_one_blank_line_in_order(t) -> None:
    r = t["resolves"]
    assert r["multi_review"] == _ex("X\n\nY", 2)
    assert r["multi_worker"] == _ex("X", 1)


def test_role_with_no_blocks_gets_empty_extract_when_others_have(t) -> None:
    assert t["resolves"]["other_role_empty"] == _ex("", 0)


def test_all_mark_reaches_every_role(t) -> None:
    assert t["resolves"]["all_mark"] == _ex("X", 1)


def test_all_is_not_a_valid_role(t) -> None:
    _assert_error(t["resolves"]["all_role"], "all")


def test_marks_inside_code_fence_are_ignored(t) -> None:
    r = t["resolves"]
    assert r["in_fence"] == _ex("本物", 1)
    assert r["look_in_fence_ignored"] == _ex("X", 1)
    # 子ブロックの中のコードブロックにある閉じ印は、閉じではない
    fb = r["fence_inside_block"]
    assert fb["kind"] == "extract" and fb["text"].endswith("後") and "<!-- /child -->" in fb["text"]
    # ``` で開いたコードブロックは ~~~ では閉じない (閉じると、中の閉じ印が効いてしまう)
    mf = r["mixed_fence_not_closed"]
    assert mf["kind"] == "extract" and mf["text"].endswith("後") and "~~~" in mf["text"]


def test_fence_content_is_not_a_heading(t) -> None:
    assert t["resolves"]["heading_in_fence_not_heading"] == _ex("X", 1)


def test_crlf_is_accepted(t) -> None:
    r = t["resolves"]
    assert r["crlf"] == _ex("X", 1)
    _assert_error(r["crlf_unclassified"], "5 行目")


def test_mark_must_be_the_whole_line(t) -> None:
    # 文中のコメントは印ではない → ブロックの外の文 = 未分類
    _assert_error(t["resolves"]["whole_line_only"], "2 行目")


# --- 識別子 ---


@pytest.mark.parametrize("key", ["id_not_first", "id_after_text"])
def test_identifier_must_be_first_nonblank_line(t, key) -> None:
    _assert_error(t["resolves"][key], "識別子")


def test_identifier_without_marks_is_an_error(t) -> None:
    _assert_error(t["resolves"]["id_only"], "子向け")
    _assert_error(t["resolves"]["id_and_headings_only"], "子向け")
    _assert_error(t["resolves"]["zero_blocks"], "子向け")


@pytest.mark.parametrize("key", ["marks_no_id", "parent_no_id", "valid_mark_plus_lookalike_no_id"])
def test_marks_without_identifier_are_an_error(t, key) -> None:
    _assert_error(t["resolves"][key], "識別子")


@pytest.mark.parametrize(
    "key",
    [
        "legacy_generated_parent",
        "legacy_children_section",
        "legacy_parent_directory",
        "legacy_markdownlint",
        "look_no_id",
        "legacy_lookalike_tag",
        "legacy_lookalike_close",
    ],
)
def test_before_adoption_plain_and_lookalike_comments_stay_full(t, key) -> None:
    # 導入前 (有効な識別子も印も無い) では、印に似た行・child / parent を含むだけのコメントを無視して全文
    r = t["resolves"][key]
    assert r["kind"] == "full" and r["why"] == "legacy", r


@pytest.mark.parametrize(
    "key", ["legacy_ident_no_version", "legacy_ident_spaced", "legacy_ident_upper"]
)
def test_misspelled_identifier_is_broken_even_before_adoption(t, key) -> None:
    _assert_error(t["resolves"][key])


@pytest.mark.parametrize("key", ["adopted_plain_comment_outside"])
def test_adopted_file_with_a_plain_comment_outside_blocks_is_broken(t, key) -> None:
    _assert_error(t["resolves"][key], "5 行目")


def test_plain_comment_inside_a_block_is_content(t) -> None:
    assert t["resolves"]["adopted_plain_comment_inside"] == _ex(
        "<!-- generated from parent guide -->\nX", 1
    )


def test_fence_close_needs_same_char_and_at_least_the_open_length(t) -> None:
    r = t["resolves"]
    for key in (
        "fence4_not_closed_by_3",
        "tilde4_not_closed_by_3",
        "fence_close_with_text_is_not_close",
    ):
        assert r[key]["kind"] == "extract", (key, r[key])
        assert r[key]["text"].endswith("後") and "<!-- /child -->" in r[key]["text"], key
    assert r["fence_closed_by_longer"] == _ex("```\nx\n`````\n後", 1)
    # バッククォートの開き行の info にバッククォートがある行は、コードブロックの開きではない (CommonMark)。
    # 開いたことにすると、この後の閉じ印が無視されて破損になる
    assert r["backtick_info_not_fence"] == _ex("``` `x`\n後", 1)


# --- 破損 ---


@pytest.mark.parametrize(
    ("key", "word"),
    [
        ("unclosed", "閉じ"),
        ("unclosed_parent", "閉じ"),
        ("nested", "入れ子"),
        ("nested_child", "入れ子"),
        ("close_only", "開き"),
        ("close_parent_only", "開き"),
        ("mismatched_close", "対応"),
        ("unknown_role", "boss"),
        ("empty_role", "役割"),
        ("unknown_version", "v2"),
    ],
)
def test_broken_marks_fail_with_a_reason(t, key, word) -> None:
    _assert_error(t["resolves"][key], word)


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("unclosed", 2),
        ("nested", 3),
        ("nested_child", 3),
        ("close_only", 5),
        ("unknown_role", 2),
    ],
)
def test_error_reason_has_line_number(t, key, line) -> None:
    _assert_error(t["resolves"][key], f"{line} 行目")


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("look_unclosed_tag", 2),
        ("look_nospace", 2),
        ("look_ctx_spaced", 1),
        ("look_parent_typo", 2),
    ],
)
def test_lookalike_marks_are_broken_not_silently_full(t, key, line) -> None:
    _assert_error(t["resolves"][key], f"{line} 行目")


# --- 未分類 ---


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("unclassified_text", 5),
        ("unclassified_bullet", 5),
        ("unclassified_table", 5),
        ("unclassified_fence", 5),
        ("unclassified_new_section", 6),
    ],
)
def test_unclassified_additions_are_errors(t, key, line) -> None:
    _assert_error(t["resolves"][key], f"{line} 行目", "未分類")


# --- mode / role ---


def test_inherit_returns_full_even_when_broken(t) -> None:
    r = t["resolves"]
    assert r["inherit_legacy"] == _full("inherit", "そのまま\n- 全部")
    assert r["inherit_broken"]["kind"] == "full" and r["inherit_broken"]["why"] == "inherit"
    assert r["inherit_broken"]["text"].endswith("X")
    assert r["inherit_ok"]["kind"] == "full" and r["inherit_ok"]["why"] == "inherit"
    assert "親の規則" in r["inherit_ok"]["text"]
    assert r["inherit_unclassified"]["kind"] == "full"


def test_unknown_mode_is_an_error(t) -> None:
    _assert_error(t["resolves"]["unknown_mode"], "mode")


@pytest.mark.parametrize("key", ["unknown_role_arg", "unknown_role_inherit", "empty_role_arg"])
def test_unknown_role_is_an_error_even_for_inherit(t, key) -> None:
    _assert_error(t["resolves"][key], "役割")


def test_unmarked_text_never_appears_in_extract(t) -> None:
    for key in ("basic", "multi_review", "multi_worker", "in_fence", "crlf"):
        r = t["resolves"][key]
        assert "親" not in r["text"] and "秘密" not in r["text"]


# --- lint ---


def test_lint_clean(t) -> None:
    assert t["lints"]["clean"] == {"ok": True, "problems": []}


def test_lint_legacy_file_is_not_ok(t) -> None:
    r = t["lints"]["legacy"]
    assert r["ok"] is False and any("識別子" in p for p in r["problems"])


def test_lint_reports_missing_identifier_and_zero_blocks(t) -> None:
    assert any("識別子" in p for p in t["lints"]["no_id_marks"]["problems"])
    assert any("識別子" in p and "2" in p for p in t["lints"]["id_not_first"]["problems"])
    r = t["lints"]["zero_blocks"]
    assert r["ok"] is False and any("子向け" in p for p in r["problems"])


@pytest.mark.parametrize(
    ("key", "line", "word"),
    [
        ("unclosed", 3, "閉じ"),
        ("nested", 3, "入れ子"),
        ("close_only", 5, "開き"),
        ("unknown_role", 2, "boss"),
        ("unknown_version", 1, "v9"),
        ("lookalike", 2, "印"),
        ("unclassified", 6, "未分類"),
    ],
)
def test_lint_reports_with_line_numbers(t, key, line, word) -> None:
    r = t["lints"][key]
    assert r["ok"] is False
    assert any(f"{line} 行目" in p and word in p for p in r["problems"]), r["problems"]


def test_lint_lists_every_problem(t) -> None:
    r = t["lints"]["many"]
    joined = "\n".join(r["problems"])
    assert (
        "2 行目" in joined
        and "3 行目" in joined
        and "未分類" in joined
        and "boss" in joined
        and "6 行目" in joined
    )


def test_lint_ignores_marks_in_code_fence(t) -> None:
    assert t["lints"]["in_fence_ignored"] == {"ok": True, "problems": []}
