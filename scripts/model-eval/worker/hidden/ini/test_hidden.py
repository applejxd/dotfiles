import re

import pytest

from tk.ini import parse_ini


def test_basic():
    text = """
# top comment
; another
[server]
Host = example.com
port=8080
  [ db ]
name = app
"""
    assert parse_ini(text) == {"server": {"host": "example.com", "port": "8080"}, "db": {"name": "app"}}


def test_empty_section_and_values():
    assert parse_ini("[a]\n[b]\nk =\n") == {"a": {}, "b": {"k": ""}}


def test_value_keeps_inner_equals_and_case():
    assert parse_ini("[s]\nurl = http://x/?a=1&b=2\nName = MiXed\n") == {
        "s": {"url": "http://x/?a=1&b=2", "name": "MiXed"}
    }


def test_section_names_case_sensitive():
    assert parse_ini("[S]\na=1\n[s]\na=2\n") == {"S": {"a": "1"}, "s": {"a": "2"}}


def test_inline_comments():
    text = "[s]\na = x #c\nb = x#c\nc = #c\nd = x ;c\ne = x\t# tab\nf = a # b # c\n"
    assert parse_ini(text) == {"s": {"a": "x", "b": "x#c", "c": "", "d": "x", "e": "x", "f": "a"}}


def test_continuation():
    text = "[s]\nmsg = first\n  second\n\tthird # c\n# comment inside\n  fourth\nnext = 1\n"
    assert parse_ini(text)["s"] == {"msg": "first\nsecond\nthird\nfourth", "next": "1"}


def test_continuation_after_empty_value():
    assert parse_ini("[s]\nk =\n  a\n")["s"]["k"] == "\na"


def test_indented_equals_is_continuation():
    assert parse_ini("[s]\nk = a\n  x = y\n")["s"] == {"k": "a\nx = y"}


def test_merge_and_override():
    text = "[a]\nx = 1\ny = 2\n[b]\nz = 3\n[a]\nx = 10\nX = 11\n"
    assert parse_ini(text) == {"a": {"x": "11", "y": "2"}, "b": {"z": "3"}}


def test_interpolation():
    text = """[paths]
root = /srv
Data = ${root}/data
logs = ${DATA}/logs
[app]
home = ${paths:data}/app
price = $$5
mixed = ${paths:root}$${x}
"""
    assert parse_ini(text) == {
        "paths": {"root": "/srv", "data": "/srv/data", "logs": "/srv/data/logs"},
        "app": {"home": "/srv/data/app", "price": "$5", "mixed": "/srv${x}"},
    }


def test_interpolation_forward_reference_and_no_double_unescape():
    text = "[s]\na = ${b}!\nb = x$$y\nc = ${a}\n"
    assert parse_ini(text)["s"] == {"a": "x$y!", "b": "x$y", "c": "x$y!"}


def test_interpolation_uses_final_value():
    text = "[s]\nb = 1\na = ${b}\n[s]\nb = 2\n"
    assert parse_ini(text)["s"]["a"] == "2"


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("[s]\njunk\n", 2),
        ("k = v\n[s]\n", 1),
        ("[s]\n = v\n", 2),
        ("[ ]\n", 1),
        ("  cont\n[s]\n", 1),
        ("[s]\n  cont\n", 2),
        ("[s]\na = 1\n[t]\n  cont\n", 4),
    ],
)
def test_errors_with_line(text, line):
    with pytest.raises(ValueError) as ei:
        parse_ini(text)
    assert re.search(rf"line {line}\b", str(ei.value))


@pytest.mark.parametrize(
    "text",
    [
        "[s]\na = ${missing}\n",
        "[s]\na = ${t:x}\n",
        "[s]\na = ${b}\nb = ${a}\n",
        "[s]\na = ${a}\n",
        "[s]\na = ${b\nb = 1\n",
        "[s]\na = $x\n",
        "[s]\na = cost $\n",
    ],
)
def test_interpolation_errors(text):
    with pytest.raises(ValueError):
        parse_ini(text)
