"""judge/plan.ts の literal の定義表 (表 L) と、mvdan-sh の構文木の型番号の固定の試験。

- 表 L: 引用・エスケープ・``$'…'``・glob・brace・``~``・展開を、lit / tilde / pat / unk に分ける。期待値はこのファイルが持つ
  独立の仕様データ (plan.ts の実装を写さない)。
- fixture: ``golden/plan_ast_fixtures.json`` は mvdan-sh の実際の構文木の要約。再生成は ``UPDATE_PLAN_FIXTURES=1`` を付けて
  この試験を回したときだけ書き込む (既定は照合のみ)。
- 演算子の番号: ``BinaryCmd.Op`` と Redirect の Op は mvdan-sh の版に固有の整数。版が変わったら plan.ts の定数も直す。

see docs/spec/guard/pi-decide.md#解析結果-plan-g1a
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from agents_common import ROOT
from plan_helper import needs_node, run_cases

pytestmark = needs_node

FIXTURES = ROOT / "test" / "agents" / "golden" / "plan_ast_fixtures.json"

# (``echo`` の後ろに置く語, 種別, 値)。値は lit・tilde では v、unk では why、pat では None
LIT, TILDE, PAT, UNK = "lit", "tilde", "pat", "unk"
TABLE: list[tuple[str, str, str | None]] = [
    # --- 素の語
    ("abc", LIT, "abc"),
    ("a/b-c.d", LIT, "a/b-c.d"),
    ("a,b", LIT, "a,b"),
    ("a=b", LIT, "a=b"),
    ("--long=v", LIT, "--long=v"),
    ("1..3", LIT, "1..3"),
    ("-x", LIT, "-x"),
    ("=~", LIT, "=~"),
    ("a:~", LIT, "a:~"),
    # --- 引用
    ("'x y'", LIT, "x y"),
    ('"x y"', LIT, "x y"),
    ("''", LIT, ""),
    ('""', LIT, ""),
    ("'$x'", LIT, "$x"),
    ("'*'", LIT, "*"),
    ('"*"', LIT, "*"),
    ('"{a}"', LIT, "{a}"),
    ("'~'", LIT, "~"),
    ('"~"', LIT, "~"),
    ("'a\\b'", LIT, "a\\b"),
    ('"a\\\\b"', LIT, "a\\b"),
    ('"a\\$b"', LIT, "a$b"),
    ('"a\\"b"', LIT, 'a"b'),
    ('"a\\nb"', LIT, "a\\nb"),
    ('"a\nb"', LIT, "a\nb"),
    ('"a\'b"', LIT, "a'b"),
    ("'a\"b'", LIT, 'a"b'),
    # --- エスケープ・連結
    ("a\\ b", LIT, "a b"),
    ("\\*", LIT, "*"),
    ("\\?", LIT, "?"),
    ("\\{a,b\\}", LIT, "{a,b}"),
    ("a\\$b", LIT, "a$b"),
    ("\"a\"b'c'", LIT, "abc"),
    ("a\\\nb", LIT, "ab"),
    # --- 非 ASCII は通常の語の文字 (正規化しない)
    ('"é"', LIT, "é"),
    ("全角\u3000空白", LIT, "全角\u3000空白"),
    ("\u00a0x", LIT, "\u00a0x"),
    ("ａｂｃ", LIT, "ａｂｃ"),
    # --- glob・brace (引用外)
    ("*.c", PAT, None),
    ("?x", PAT, None),
    ("[ab]", PAT, None),
    ("[", PAT, None),
    ("{a,b}", PAT, None),
    ("{}", PAT, None),
    ("{1..3}", PAT, None),
    ("a{b}c", PAT, None),
    ("x=*", PAT, None),
    ('"a"*', PAT, None),
    ("'a'?", PAT, None),
    ('*"a"', PAT, None),
    # --- チルダ
    ("~", TILDE, ""),
    ("~/", TILDE, ""),
    ("~/x", TILDE, "x"),
    ("~/a/b.c", TILDE, "a/b.c"),
    ("~root", PAT, None),
    ("~+", PAT, None),
    ("~-", PAT, None),
    ("~user/x", PAT, None),
    ("y=~", PAT, None),
    ("a=~/x", PAT, None),
    ("a=b:~", PAT, None),
    # --- 値が決まらないもの (why)
    ("$x", UNK, "param"),
    ("$1", UNK, "param"),
    ("$@", UNK, "param"),
    ("$?", UNK, "param"),
    ("${x}", UNK, "param"),
    ("${x:-y}", UNK, "param"),
    ('"$x"', UNK, "param"),
    ('"${x}"', UNK, "param"),
    ('"a$x"', UNK, "param"),
    ('a"$x"b', UNK, "param"),
    ("$(a)", UNK, "cmdsubst"),
    ('"$(a)"', UNK, "cmdsubst"),
    ("`a`", UNK, "cmdsubst"),
    ("$((1))", UNK, "arith"),
    ("$(( 1 ))", UNK, "arith"),
    ('"$((1+2))"', UNK, "arith"),
    ("$[1]", UNK, "arith"),
    ("<(a)", UNK, "procsubst"),
    ("@(a|b)", UNK, "extglob"),
    ("+(a)", UNK, "extglob"),
    ("$'a'", UNK, "ansi-c"),
    ("$'\\x67it'", UNK, "ansi-c"),
    ("a$'b'", UNK, "ansi-c"),
    ('$"b"', UNK, "locale"),
    ("*$x", UNK, "param"),
]


@pytest.fixture(scope="module")
def table_results() -> list[dict]:
    return run_cases([{"cmd": f"echo {word}"} for word, _, _ in TABLE])


def test_table_has_at_least_60_rows():
    assert len(TABLE) >= 60


@pytest.mark.parametrize("idx", range(len(TABLE)), ids=[repr(t[0]) for t in TABLE])
def test_literal_table(table_results, idx):
    word, kind, val = TABLE[idx]
    r = table_results[idx]
    assert r["ok"] is True, r
    # 置換の中身は入れ子の site (parent=0) になる。トップレベルは 1 つだけ
    assert [s for s in r["sites"] if s["parent"] is None] == r["sites"][:1], r["sites"]
    argv = r["sites"][0]["argv"]
    assert len(argv) == 2, argv
    w = argv[1]
    assert w["k"] == kind, (word, w)
    if kind in (LIT, TILDE):
        assert w["v"] == val, (word, w)
    elif kind == UNK:
        assert w["why"] == val, (word, w)
    else:
        assert "v" not in w


def test_unk_word_records_referenced_variable_names():
    r = run_cases([{"cmd": 'echo "$x" "a${y}b" $((z+1))'}])[0]
    words = r["sites"][0]["argv"][1:]
    assert [w.get("refs") for w in words] == [["x"], ["y"], ["z"]]


def test_raw_keeps_original_text_and_span_is_utf8_bytes():
    r = run_cases([{"cmd": 'echo "確認" a\\ b'}])[0]
    words = r["sites"][0]["argv"]
    assert [w["raw"] for w in words] == ["echo", '"確認"', "a\\ b"]
    # echo=0..4、"確認" は 5 から 8 バイト (引用符込み。文字数ではない)
    assert words[1]["span"] == [5, 13]


# --- 構文木の型番号の固定 (mvdan-sh の版に固有。ずれたら plan.ts の定数を見直す)

BINARY_OPS = {"a && b": 10, "a || b": 11, "a | b": 12, "a |& b": 13}
REDIR_OPS = {
    "x > f": 54,
    "x >> f": 55,
    "x < f": 56,
    "x >| f": 60,
    "x >& 2": 59,
    "x <& 0": 58,
    "x <> f": 57,
    "x <<< s": 63,
    "x &> f": 64,
    "x &>> f": 65,
}


def _find(tree, type_name):
    """構文木の要約から、型名が ``type_name`` の最初のノードを探す。"""
    if isinstance(tree, dict):
        if tree.get("_t") == type_name:
            return tree
        for v in tree.values():
            hit = _find(v, type_name)
            if hit is not None:
                return hit
    elif isinstance(tree, list):
        for v in tree:
            hit = _find(v, type_name)
            if hit is not None:
                return hit
    return None


def test_binary_cmd_and_redirect_op_numbers_are_pinned():
    cmds = list(BINARY_OPS) + list(REDIR_OPS)
    out = run_cases([{"cmd": c, "ast": True} for c in cmds])
    for c, r in zip(cmds, out, strict=True):
        assert "tree" in r, (c, r)
        if c in BINARY_OPS:
            assert _find(r["tree"], "BinaryCmd")["Op"] == BINARY_OPS[c], c
        else:
            assert _find(r["tree"], "Redirect")["Op"] == REDIR_OPS[c], c


def test_heredoc_redirect_op_numbers_are_pinned():
    cmds = ["x <<E\nb\nE", "x <<-E\nb\nE"]
    out = run_cases([{"cmd": c, "ast": True} for c in cmds])
    assert [_find(r["tree"], "Redirect")["Op"] for r in out] == [61, 62]


# --- fixture (mvdan-sh の実型の要約) の照合

FIXTURE_CMDS = [
    "git log",
    "a && b || c | d",
    "x > f 2>&1",
    "echo ${x:-y} $((1+2)) $(a) <(b)",
    "echo $'a' $\"b\"",
    "echo \"a$x\" 'b' c\\ d",
    "echo *.c {a,b} ~/x @(a|b)",
    "cat <<E\nbody\nE",
    "cat <<< s",
    "x=1 y= env z",
    "time git log",
    "declare x=1",
    "f() { a; }",
    "if a; then b; fi",
]


def test_ast_fixtures_match_golden():
    out = run_cases([{"cmd": c, "ast": True} for c in FIXTURE_CMDS])
    current = dict(zip(FIXTURE_CMDS, out, strict=True))
    assert all("tree" in r for r in out), out
    if os.environ.get("UPDATE_PLAN_FIXTURES") == "1":
        FIXTURES.write_text(
            json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    golden = json.loads(Path(FIXTURES).read_text(encoding="utf-8"))
    assert golden == current, (
        "構文木の要約が golden と違う。意図した更新なら UPDATE_PLAN_FIXTURES=1 で再生成する"
    )


def test_ast_summary_exposes_the_dollar_flag_for_ansi_c_and_locale():
    out = run_cases([{"cmd": "echo $'a' $\"b\"", "ast": True}])[0]
    sg = _find(out["tree"], "SglQuoted")
    dq = _find(out["tree"], "DblQuoted")
    assert sg["Dollar"] is True and dq["Dollar"] is True
