"""guarded_* の使用コスト削減 (``home/dot_config/pi/harness/tools-ext.ts``) の試験。

- 表試験: ``test/agents/pi/tools_ext_driver.mjs`` が tools-ext.ts を読んで結果を JSON で出す
  (node の型除去を使うので、22.18 未満の node では飛ばす)。
- 通し試験: 偽のモデル (faux) で pi のフルガードを回す (pi が無ければ飛ばす)。

see docs/spec/guard/pi-guard.md
"""

from __future__ import annotations

import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_harness import PI, bash_call, env, lines, run_pi  # noqa: F401
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "tools_ext_driver.mjs"

needs_node = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")
needs_pi = pytest.mark.skipif(PI is None, reason="pi is not installed")


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


# ─── 表試験 ─────────────────────────────────────────────────────────


@needs_node
@pytest.mark.parametrize(
    ("case", "passed"),
    [
        ("lf", {"path": "a.txt", "offset": 2, "limit": 2}),
        ("no_lf", {"path": "b.txt", "offset": 2, "limit": 2}),
        ("more_than_total", {"path": "a.txt", "offset": 1, "limit": 10}),
        ("empty", {"path": "empty.txt", "offset": 1, "limit": 3}),
        ("missing", {"path": "nope.txt"}),
        ("directory", {"path": "sub"}),
        ("plain", {"path": "a.txt", "offset": 2, "limit": 1}),
    ],
)
def test_tail_becomes_offset_and_limit(table, case, passed):
    got = table["tail"][case]
    assert "error" not in got, got
    assert got["passed"] == passed


@needs_node
def test_tail_on_an_absolute_path(table):
    got = table["tail"]["absolute"]
    assert got["passed"]["offset"] == 3 and got["passed"]["limit"] == 1, got


@needs_node
@pytest.mark.parametrize(
    ("case", "message", "reached_the_tool"),
    [
        ("with_offset", "cannot be used together", False),
        ("zero", "integer of 1 or more", False),
        ("fractional", "integer of 1 or more", False),
        ("too_big", "32 MiB", False),
        ("image", "image files", True),
    ],
)
def test_tail_errors(table, case, message, reached_the_tool):
    got = table["tail"][case]
    assert message in got.get("error", ""), got
    assert (got["passed"] is not None) == reached_the_tool, got


@needs_node
def test_offset_beyond_the_end_keeps_the_message_and_adds_the_range(table):
    err = table["hints"]["offset"]["error"]
    assert "Offset 99 is beyond end of file (4 lines total)" in err
    assert "有効な offset は 1〜4" in err and "tail" in err


@needs_node
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (
            "ws_only",
            "最も近い箇所: 行 1〜3。違い: 行 2 (期待: `beta()` / 実際: `  beta()`)\n空白・タブ・改行コードの違いの可能性",
        ),
        ("one_line", "最も近い箇所: 行 1〜3。違い: 行 2 (期待: `  beta(1)` / 実際: `  beta()`)"),
        ("none", "guarded_read で該当箇所を読み直してから、oldText をコピーし直す"),
        ("indexed", "最も近い箇所: 行 3〜4。違い: 行 4 (期待: `delta2` / 実際: `delta`)"),
        ("applied", "すでに適用済みの可能性: newText が行 3 にある。再編集は不要"),
        ("not_applied", "oldText と newText が同じ内容になっている。編集の意図を見直す"),
        (
            "multi",
            "一致: 行 2 (直前: `head`)、行 4 (直前: `mid`)、行 6 (直前: `x`)。直前の行を含めて oldText を一意にする",
        ),
        (
            "multi_first_line",
            "一致: 行 1 (直前: なし)、行 3 (直前: `x`)。直前の行を含めて oldText を一意にする",
        ),
        ("overlap", "近い編集を 1 つにまとめる"),
    ],
)
def test_edit_failure_hints(table, case, expected):
    assert table["editHints"][case] == expected


@needs_node
def test_edit_hint_variants(table):
    h = table["editHints"]
    assert "空白・タブ・改行コードの違いの可能性" in h["tab_crlf"] and "`→beta()`" in h["tab_crlf"]
    assert "可能性" not in h["one_line"]
    assert "q" * 80 + "…" in h["long_line"] and "q" * 81 not in h["long_line"]
    assert "be\\x01ta" in h["control"]
    assert "行 2 (直前: `row 0`)" in h["multi_many"] and "ほか 4 件" in h["multi_many"]
    assert h["multi_many"].count("直前:") == 5
    assert "guarded_write" in h["invalid"] and "edits を小さく分ける" in h["invalid"]
    assert len(h["ws_only"].splitlines()) <= 3


@needs_node
@pytest.mark.parametrize("case", ["no_text", "nochange_no_text", "guard_deny", "erofs", "enoent"])
def test_edit_hint_is_omitted_without_text_or_for_other_errors(table, case):
    assert table["editHints"][case] is None


@needs_node
def test_nearest_match(table):
    n = table["nearest"]
    assert n["ws"] == {
        "start": 1,
        "end": 2,
        "exact": True,
        "diffLine": 2,
        "expected": "beta()",
        "actual": "  beta()",
    }
    assert n["none"] is None and n["blank"] is None


@needs_node
def test_edit_result_keeps_the_message_and_appends_the_hint(table):
    nf = "Could not find the exact text in e.txt. The old text must match exactly including all whitespace and newlines."
    hint = "最も近い箇所: 行 1〜2。違い: 行 2 (期待: `beta(1)` / 実際: `  beta()`)"
    for case in ("ok", "absolute"):
        assert table["deco"][case] == {"content": [{"type": "text", "text": f"{nf}\n{hint}"}]}
    inv = table["deco"]["invalid_without_file"]["content"][0]["text"]
    assert (
        inv.startswith('Invalid arguments for tool "guarded_edit": bad\n')
        and "guarded_write" in inv
    )


@needs_node
@pytest.mark.parametrize(
    "case",
    [
        "success",
        "success_text_looks_like_error",
        "missing",
        "binary",
        "huge",
        "unreadable",
        "deny",
        "no_content",
    ],
)
def test_edit_result_is_left_alone(table, case):
    assert table["deco"][case] is None


@needs_node
def test_other_read_errors_are_left_alone(table):
    assert table["hints"]["other_error"]["error"] == "boom"


@needs_node
def test_missing_file_suggests_similar_names_but_not_unreadable_ones(table):
    hints = table["hints"]
    assert "ENOENT" in hints["similar_case"]["error"]
    assert "似たファイル: Readme.md" in hints["similar_case"]["error"]
    # 判定器が読めないとする名前は、提案に出さない (提案の行ごと出ない)
    assert "secret.env" not in hints["similar_denied"]["error"]
    assert "似たファイル" not in hints["similar_denied"]["error"]
    assert "似たファイル" not in hints["no_similar"]["error"]
    # 近い順で、最大 3 件
    assert hints["names"] == ["README.md", "READ", "REDME.md"]


@needs_node
def test_tool_texts_point_to_the_replacements(table):
    texts = table["texts"]
    assert texts["nothing"] is None
    blob = {t: json.dumps(texts[t], ensure_ascii=False) for t in ("bash", "read", "write", "edit")}
    for word in (
        "guarded_read",
        "guarded_write",
        "guarded_edit",
        "tail",
        "append: true",
        "parallel",
        "bg_run",
    ):
        assert word in blob["bash"], word
    assert "BUILTIN" in texts["bash"]["description"], "組み込みの説明は残して足す"
    assert "builtin guideline" in texts["bash"]["promptGuidelines"]
    for word in ("tail", "offset", "parallel"):
        assert word in blob["read"], word
    for word in ("append: true", "guarded_edit"):
        assert word in blob["write"], word
    assert "edits[]" in blob["edit"] and "sed/awk" in blob["edit"]
    snippet = texts["bash"]["promptSnippet"]
    assert "ls, grep, find" not in snippet and "Not for reading or writing file contents" in snippet
    # 名前は接頭辞付きで書く (素の read / write ではない)
    assert "Use read " not in blob["read"]


@needs_node
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("sed_range", 'guarded_read {path: "src/a.py", offset: 10, limit: 11}'),
        ("sed_one", 'guarded_read {path: "a.py", offset: 7, limit: 1}'),
        ("head_n", 'guarded_read {path: "f.txt", limit: 5}'),
        ("head_dash", 'guarded_read {path: "f.txt", limit: 3}'),
        ("head_default", 'guarded_read {path: "f.txt", limit: 10}'),
        ("tail_n", 'guarded_read {path: "log.txt", tail: 20}'),
        ("tail_dash", 'guarded_read {path: "log.txt", tail: 5}'),
        ("tail_plus", 'guarded_read {path: "log.txt", offset: 30}'),
        ("cat", 'guarded_read {path: "FILE.md"}'),
        ("cat_two", 'guarded_read {path: "b.txt"}'),
        ("cat_heredoc", 'guarded_write {path: "out.txt", content: "..."}'),
        ("cat_append", 'guarded_write {path: "out.txt", content: "...", append: true}'),
        ("tee", 'guarded_write {path: "o.txt", content: "..."}'),
        ("tee_append", 'guarded_write {path: "o.txt", content: "...", append: true}'),
        ("python", "guarded_write でスクリプトのファイル"),
        ("compound", 'guarded_read {path: "/repo/a.py", limit: 3}'),
        ("after_heredoc", 'guarded_write {path: "f", content: "..."}'),
        ("two_reads", 'guarded_read {path: "a.py", tail: 3}'),
    ],
)
def test_guide_hint_rewrites(table, case, expected):
    assert expected in table["hint"][case], table["hint"][case]


@needs_node
def test_guide_hint_names_the_fragment_and_the_rest(table):
    hint = table["hint"]
    assert "`cat > out.txt <<...`" in hint["cat_heredoc"]
    assert "`head -n 3 a.py`" in hint["compound"]
    # 置き換える断片以外が残るときだけ、残りを bash で実行し直す案内が付く
    assert "残りの断片" in hint["compound"] and "guarded_bash" in hint["compound"]
    assert "残りの断片" in hint["after_heredoc"]
    assert "残りの断片" not in hint["two_reads"] and "残りの断片" not in hint["sed_range"]
    # 複数ファイルの cat は、ファイルごとの並列の呼び出しにする
    assert 'guarded_read {path: "a.txt"}' in hint["cat_two"] and "parallel" in hint["cat_two"]


@needs_node
@pytest.mark.parametrize(
    "case",
    [
        "pipe",
        "redirect",
        "variable",
        "glob",
        "plain",
        "bare_cat",
        "head_c",
        "unknown_heredoc",
        "unbalanced",
    ],
)
def test_guide_hint_is_not_added_to_unparsable_forms(table, case):
    assert table["hint"][case] is None


# ─── 通し試験 (faux) ────────────────────────────────────────────────


def _call(name, **args):
    return [{"name": name, "args": args}]


@needs_pi
def test_read_tail_returns_the_last_lines(env):  # noqa: F811
    (env["proj"] / "t.txt").write_text("l1\nl2\nl3\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_read", path="t.txt", tail=2))
    assert "guarded_read: isError=false" in proc.stdout, proc.stdout + proc.stderr
    assert "l2" in proc.stdout and "l3" in proc.stdout and "l1" not in proc.stdout, proc.stdout


@needs_pi
def test_read_tail_with_offset_is_an_error(env):  # noqa: F811
    (env["proj"] / "t.txt").write_text("l1\nl2\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_read", path="t.txt", tail=1, offset=1))
    assert "isError=true" in proc.stdout and "cannot be used together" in proc.stdout, proc.stdout


@needs_pi
def test_read_tail_is_still_judged_by_the_path(env):  # noqa: F811
    proc = run_pi(env, _call("guarded_read", path=".netrc", tail=1))
    assert "isError=true" in proc.stdout and "read_deny_globs" in proc.stdout, proc.stdout


@needs_pi
def test_read_failure_hints_reach_the_model(env):  # noqa: F811
    (env["proj"] / "t.txt").write_text("l1\nl2\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_read", path="t.txt", offset=50))
    assert "beyond end of file" in proc.stdout and "有効な offset は 1〜" in proc.stdout, (
        proc.stdout
    )
    (env["proj"] / "notes.txt").write_text("x\n", encoding="utf-8")
    (env["proj"] / ".netrc").write_text("x\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_read", path="Notes.txt"))
    assert "似たファイル: notes.txt" in proc.stdout, proc.stdout
    # 読み取り拒否の名前は提案しない
    proc = run_pi(env, _call("guarded_read", path=".netrd"))
    assert "isError=true" in proc.stdout and ".netrc" not in proc.stdout, proc.stdout


@needs_pi
def test_write_append_concatenates_without_adding_a_newline(env):  # noqa: F811
    target = env["proj"] / "w.txt"
    target.write_text("a\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_write", path="w.txt", content="b", append=True))
    assert "isError=false" in proc.stdout and "appended" in proc.stdout, proc.stdout
    assert target.read_text(encoding="utf-8") == "a\nb"


@needs_pi
def test_write_append_creates_the_file_and_the_parent_directory(env):  # noqa: F811
    run_pi(env, _call("guarded_write", path="new/dir/w.txt", content="x\n", append=True))
    assert (env["proj"] / "new" / "dir" / "w.txt").read_text(encoding="utf-8") == "x\n"


@needs_pi
def test_write_without_append_still_overwrites(env):  # noqa: F811
    target = env["proj"] / "w.txt"
    target.write_text("old\n", encoding="utf-8")
    run_pi(env, _call("guarded_write", path="w.txt", content="new\n"))
    run_pi(env, _call("guarded_write", path="w.txt", content="new2\n", append=False))
    assert target.read_text(encoding="utf-8") == "new2\n"


@needs_pi
def test_write_append_is_denied_for_a_denied_path(env):  # noqa: F811
    target = env["proj"] / "key.pem"
    target.write_text("keep\n", encoding="utf-8")
    proc = run_pi(env, _call("guarded_write", path="key.pem", content="more\n", append=True))
    assert "isError=true" in proc.stdout and "write_deny_globs" in proc.stdout, proc.stdout
    assert target.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.skipif(PI is None, reason="pi is not installed")
def test_tool_texts_reach_the_system_prompt(env):  # noqa: F811
    proc = run_pi(env, [], FAUX_DUMP_PROMPT="1")
    assert proc.returncode == 0, proc.stderr
    prompt = proc.stdout
    assert "tail for the last N lines" in prompt and "append: true" in prompt, prompt
    assert "bg_run" in prompt
    assert "search with grep/find/ls). Not for reading or writing file contents" in prompt
    assert "Execute bash commands (ls, grep, find, etc.)" not in prompt


@needs_pi
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("sed -n '1,5p' a.txt", 'guarded_read {path: "a.txt", offset: 1, limit: 5}'),
        ("head -n 3 a.txt", 'guarded_read {path: "a.txt", limit: 3}'),
        ("tail -n 3 a.txt", 'guarded_read {path: "a.txt", tail: 3}'),
        ("cat a.txt", 'guarded_read {path: "a.txt"}'),
        ("cat > x.txt <<EOF\nhi\nEOF", 'guarded_write {path: "x.txt", content: "..."}'),
        ("cd sub && head -n 2 a.txt && git status", 'guarded_read {path: "sub/a.txt", limit: 2}'),
    ],
)
def test_guide_deny_carries_the_rewrite(env, command, expected):  # noqa: F811
    proc = run_pi(env, bash_call(command))
    assert "isError=true" in proc.stdout and expected in proc.stdout, proc.stdout
    assert not (env["proj"] / "x.txt").exists()


@needs_pi
def test_guide_deny_without_a_rewrite_is_unchanged(env):  # noqa: F811
    proc = run_pi(env, bash_call("cat -n a.txt"))
    assert "isError=true" in proc.stdout and "cat / head / tail" in proc.stdout, proc.stdout
    assert "具体的な言い換え" not in proc.stdout, proc.stdout
    # 誘導の対象でない deny には何も足さない
    proc = run_pi(env, bash_call("git push"))
    assert "`git push` は deny" in proc.stdout and "具体的な言い換え" not in proc.stdout


@needs_pi
def test_guide_deny_is_not_loosened_by_bypass(env):  # noqa: F811
    proc = run_pi(env, bash_call("cat a.txt"), PI_HARNESS_BYPASS="1")
    assert "isError=true" in proc.stdout and "guarded_read" in proc.stdout, proc.stdout
