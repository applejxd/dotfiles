from tk.report import render_markdown, render_table, render_totals


def test_render_table():
    assert render_table(["name", "n"], [["a", 1], ["bbb", 22]]) == (
        "name | n\n"
        "-----+---\n"
        "a    | 1\n"
        "bbb  | 22"
    )


def test_render_totals_has_total_row():
    out = render_totals(["name", "n"], [["a", 1], ["b", 2]])
    assert out.splitlines()[-1] == "Total | 3"


def test_render_markdown():
    assert render_markdown(["k", "v"], [["x", 1]]).splitlines()[0] == "| k   | v   |"
