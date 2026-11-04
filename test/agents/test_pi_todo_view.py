"""todo の表示部品 (view.ts)。pi に依存しないので node で直接動かす。see docs/spec/guard/pi-extensions.md#todo-の別表示"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from agents_common import ROOT

VIEW = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "todo" / "view.ts"

# 関数を順に呼ぶ。"@mark" の引数は、色の名前を [色:...] で包む Paint に置き換える
_RUNNER = """
const v = await import(process.argv[2]);
const mark = { fg: (c, s) => `<${c}>${s}</${c}>`, bold: (s) => `<b>${s}</b>`, strike: (s) => `<s>${s}</s>` };
const cases = JSON.parse(process.argv[3]);
const fix = (a) => (a === "@mark" ? mark : a);
console.log(JSON.stringify(cases.map(([fn, ...args]) => v[fn](...args.map(fix)))));
"""


def _run(tmp_path, cases):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node が無い")
    runner = tmp_path / "runner.mjs"
    runner.write_text(_RUNNER, encoding="utf-8")
    out = subprocess.run(
        [node, str(runner), VIEW.as_uri(), json.dumps(cases)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


def _todo(i, status, text=None, note=None):
    t = {"id": i, "text": text or f"項目{i}", "status": status}
    if note:
        t["note"] = note
    return t


MIXED = [
    _todo(1, "in_progress", "実装する"),
    _todo(2, "blocked", "承認待ち", "PR #5 の統合を待つ"),
    _todo(3, "pending"),
    _todo(4, "pending"),
    _todo(5, "done"),
    _todo(6, "cancelled"),
]


def _frame(tmp_path, todos, state, width, rows, mark=False):
    return _run(
        tmp_path, [["renderOverlay", todos, state, width, rows] + (["@mark"] if mark else [])]
    )[0]


def _w(tmp_path, strings):
    return _run(tmp_path, [["textWidth", s] for s in strings])


def test_headings_with_counts_and_closed_hidden_by_default(tmp_path):
    f = _frame(tmp_path, MIXED, {"top": 0, "showClosed": False}, 60, 40)
    text = "\n".join(f["lines"])
    assert "進行中 (1)" in text and "待ち (1)" in text and "未着手 (2)" in text
    assert "── 完了" not in text and "── 中止" not in text
    assert "完了 1 件・中止 1 件 (a で表示)" in text
    assert f["lines"][0].startswith("📌 todo 1/6 完了")


def test_toggle_shows_closed_sections(tmp_path):
    f = _frame(tmp_path, MIXED, {"top": 0, "showClosed": True}, 60, 40)
    text = "\n".join(f["lines"])
    assert "完了 (1)" in text and "中止 (1)" in text and "a で表示" not in text


def test_paint_differs_by_status(tmp_path):
    f = _frame(tmp_path, MIXED, {"top": 0, "showClosed": True}, 60, 40, mark=True)
    text = "\n".join(f["lines"])
    assert "<accent><b>▶ #1 実装する</b></accent>" in text
    assert "<warning>◇ #2 承認待ち</warning>" in text
    assert "○ #3 項目3" in text and "<accent>○ #3" not in text  # 未着手は通常色
    assert "<success>✓ #5 項目5</success>" in text
    assert "<dim><s>✗ #6 項目6</s></dim>" in text
    assert "<dim>    PR #5 の統合を待つ</dim>" in text


def test_note_folds_to_two_lines_with_ellipsis(tmp_path):
    todos = [_todo(1, "pending", note="あ" * 100)]
    f = _frame(tmp_path, todos, {"top": 0, "showClosed": False}, 30, 40)
    note_lines = [line for line in f["lines"] if line.startswith("    ")]
    assert len(note_lines) == 2 and note_lines[1].endswith("…")
    short = _run(tmp_path, [["foldNote", "短い note", 30]])[0]
    assert short == ["短い note"]


def test_scroll_stops_at_top_and_bottom(tmp_path):
    todos = [_todo(i, "pending") for i in range(1, 41)]
    f = _frame(tmp_path, todos, {"top": 0, "showClosed": False}, 60, 14)
    assert f["bodyHeight"] == 8 and f["maxTop"] == f["total"] - 8
    st = {"top": 0, "showClosed": False}
    up, down, end, home, end_down, pgdn = _run(
        tmp_path,
        [
            ["step", st, "up", f["total"], 8],
            ["step", st, "down", f["total"], 8],
            ["step", st, "end", f["total"], 8],
            ["step", st, "home", f["total"], 8],
            ["step", {"top": f["maxTop"], "showClosed": False}, "down", f["total"], 8],
            ["step", st, "pageDown", f["total"], 8],
        ],
    )
    assert up["top"] == 0 and down["top"] == 1 and home["top"] == 0
    assert end["top"] == f["maxTop"] and end_down["top"] == f["maxTop"]
    assert pgdn["top"] == 7  # 本文の高さ − 1
    # 範囲外の top で描いても末尾へ丸める
    g = _frame(tmp_path, todos, {"top": 9999, "showClosed": False}, 60, 14)
    assert g["top"] == g["maxTop"]


def test_height_never_exceeds_terminal(tmp_path):
    todos = [_todo(i, "pending", note="n" * 200) for i in range(1, 60)]
    for rows in (3, 5, 10, 24, 50):
        f = _frame(tmp_path, todos, {"top": 0, "showClosed": False}, 60, rows)
        assert len(f["lines"]) <= max(3, rows - 4)
    small = _frame(tmp_path, [_todo(1, "pending")], {"top": 0, "showClosed": False}, 60, 50)
    assert len(small["lines"]) < 10  # 内容が少ないときは内容の高さ


def test_wide_titles_stay_within_width(tmp_path):
    todos = [
        _todo(1, "in_progress", "全角の題名" * 20, "メモ" * 50),
        _todo(2, "pending", "abc" * 40),
    ]
    for width in (20, 33, 60):
        f = _frame(tmp_path, todos, {"top": 0, "showClosed": False}, width, 40)
        widths = _w(tmp_path, f["lines"])
        assert max(widths) <= width, (width, f["lines"])
    clipped = _run(tmp_path, [["clipWidth", "全角全角全角", 7]])[0]
    assert clipped == "全角全…" and _w(tmp_path, [clipped]) == [7]


def test_empty_and_single(tmp_path):
    empty = _frame(tmp_path, [], {"top": 0, "showClosed": False}, 40, 24)
    assert "(タスクなし)" in "\n".join(empty["lines"])
    closed_only = _frame(tmp_path, [_todo(1, "done")], {"top": 0, "showClosed": False}, 40, 24)
    text = "\n".join(closed_only["lines"])
    assert "(未完了なし)" in text and "完了 1 件" in text
    one = _frame(tmp_path, [_todo(1, "pending")], {"top": 0, "showClosed": False}, 40, 24)
    assert one["maxTop"] == 0 and "未着手 (1)" in "\n".join(one["lines"])


def test_keys_transitions(tmp_path):
    cases = [["keyFromChar", c] for c in ("j", "k", "g", "G", "a", "q", "x")]
    assert _run(tmp_path, cases) == ["down", "up", "home", "end", "toggleClosed", "close", None]
    st = {"top": 5, "showClosed": False}
    toggled, closed, pgup = _run(
        tmp_path,
        [
            ["step", st, "toggleClosed", 50, 8],
            ["step", st, "close", 50, 8],
            ["step", st, "pageUp", 50, 8],
        ],
    )
    assert toggled == {"top": 0, "showClosed": True, "closed": False}
    assert closed["closed"] is True
    assert pgup["top"] == 0 and pgup["closed"] is False


def test_tiny_terminal_does_not_throw(tmp_path):
    todos = [*MIXED, _todo(7, "pending", "x" * 80, "y" * 80)]
    for width, rows in ((20, 3), (1, 1), (0, 0), (5, 2)):
        for show in (False, True):
            f = _frame(tmp_path, todos, {"top": 3, "showClosed": show}, width, rows)
            assert len(f["lines"]) <= 3
            assert max(_w(tmp_path, f["lines"])) <= max(1, width)


def test_chat_labels_are_collapsed(tmp_path):
    update, batch, add, lst = _run(
        tmp_path,
        [
            ["callLabel", {"action": "update", "id": 101, "status": "blocked"}],
            ["callLabel", {"action": "batch", "ops": [{}, {}]}],
            ["callLabel", {"action": "add", "texts": ["a", "b"]}],
            ["callLabel", {"action": "list"}],
        ],
    )
    assert update == "📌 todo update #101 → blocked"
    assert batch == "📌 todo batch (2 件)" and add == "📌 todo add (2 件)" and lst == "📌 todo list"
    todos = [_todo(1, "pending")] * 18 + [_todo(2, "done")] * 83 + [_todo(3, "cancelled")]
    res, err, empty = _run(
        tmp_path,
        [
            ["resultLabel", {"todos": todos}],
            ["resultLabel", {"todos": [], "error": "#9 が無い"}],
            ["resultLabel", {"todos": []}],
        ],
    )
    assert res == "未完了 18 件・完了 83 件" and err == "エラー: #9 が無い" and empty == "(空)"


def test_expanded_body_is_painted_without_changing_text(tmp_path):
    lines = ["[>] #1: a", "[ ] #2: b", "[x] #3: c", "[-] #4: d", "追加: #5 e"]
    painted = _run(tmp_path, [["paintContentLine", line, "@mark"] for line in lines])
    assert painted[0] == "<accent><b>[>] #1: a</b></accent>"
    assert painted[1] == "[ ] #2: b" and painted[4] == "追加: #5 e"
    assert painted[2] == "<success>[x] #3: c</success>"
