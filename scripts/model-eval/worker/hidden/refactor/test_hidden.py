import inspect
import random

import pytest

import tk.report as report
from orig_report import render_markdown as o_md
from orig_report import render_table as o_table
from orig_report import render_totals as o_totals


def _cases():
    rng = random.Random(7)
    words = ["a", "bb", "ccc", "", "longer-name", "x y", "Ünï"]
    cases = [
        (["name", "n"], [["a", 1], ["bbb", 22]]),
        (["k", "v"], [["x", 1]]),
        (["h"], []),
        (["a", "b", "c"], [["", 0, 1.5], ["zz", -3, 2.25]]),
        (["item", "qty", "note"], [["apple", 3, "fresh"], ["kiwi", 10, ""]]),
    ]
    for _ in range(40):
        ncol = rng.randint(1, 4)
        headers = [rng.choice(words) or "h" for _ in range(ncol)]
        rows = []
        for _ in range(rng.randint(0, 5)):
            row = []
            for c in range(ncol):
                if c and rng.random() < 0.6:
                    row.append(rng.choice([0, 1, 42, 1000, -5, 2.5]))
                else:
                    row.append(rng.choice(words))
            rows.append(row)
        cases.append((headers, rows))
    return cases


@pytest.mark.parametrize(("headers", "rows"), _cases())
def test_same_output(headers, rows):
    assert report.render_table(headers, rows) == o_table(headers, rows)
    assert report.render_markdown(headers, rows) == o_md(headers, rows)
    assert report.render_totals(headers, rows) == o_totals(headers, rows)
    assert report.render_totals(headers, rows, label="Sum") == o_totals(headers, rows, label="Sum")


def test_helpers_contract():
    assert report._format_row(["a", 1], [3, 2]) == "a   | 1 "
    assert report._format_row([], []) == ""
    assert report._column_widths(["name", "n"], [["a", 1], ["bbb", 22]]) == [4, 2]
    assert report._column_widths(["h"], []) == [1]


@pytest.mark.parametrize("fn", ["render_table", "render_totals", "render_markdown"])
def test_public_functions_use_helpers(monkeypatch, fn):
    calls = {"w": 0, "r": 0}
    orig_w, orig_r = report._column_widths, report._format_row

    def w(*a, **k):
        calls["w"] += 1
        return orig_w(*a, **k)

    def r(*a, **k):
        calls["r"] += 1
        return orig_r(*a, **k)

    monkeypatch.setattr(report, "_column_widths", w)
    monkeypatch.setattr(report, "_format_row", r)
    headers, rows = ["name", "n"], [["a", 1], ["bbb", 22], ["c", 3]]
    getattr(report, fn)(headers, rows)
    assert calls["w"] >= 1
    # 見出し行 + データ行 3 (+ 合計行) をすべて helper で整形する
    assert calls["r"] >= 4 + (fn == "render_totals")


@pytest.mark.parametrize("fn", ["render_table", "render_totals", "render_markdown"])
def test_no_duplicated_logic(fn):
    src = inspect.getsource(getattr(report, fn))
    assert "ljust" not in src
    assert "max(" not in src or fn == "render_markdown" and src.count("max(") == 1
