"""bash 検査 hook の共通の解析関数 (``bashrules.shellparse``)。

see docs/change/0012-bash-hook-shared-parser.md

Run with: ``uv run --with pytest --with pyyaml --no-project pytest test/agents/ -q``
"""

from __future__ import annotations

import importlib

import pytest
from check_bash_hook import HOOK_PATH

# hook の lib は check_bash_hook の読み込みで sys.path に載る (import 文の並べ替えに依存させない)
assert HOOK_PATH.exists()
shellparse = importlib.import_module("bashrules.shellparse")


def argvs(text: str) -> list[tuple[str, ...]]:
    return [c.argv for c in shellparse.parse(text)]


def writes(text: str) -> list[str]:
    return [
        r.target.value
        for c in shellparse.parse(text)
        for r in c.redirects
        if r.writes and r.target is not None
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ls -la", [("ls", "-la")]),
        ("a && b || c; d | e & f\ng", [("a",), ("b",), ("c",), ("d",), ("e",), ("f",), ("g",)]),
        ("echo 'a; b' \"c && d\"", [("echo", "a; b", "c && d")]),
        ('echo "Don\'t" x', [("echo", "Don't", "x")]),
        ("echo 'say \"hi\"'", [("echo", 'say "hi"')]),
        ("\\rm -rf ~", [("rm", "-rf", "~")]),
        ('"r"m x', [("rm", "x")]),
        ("echo a\\ b", [("echo", "a b")]),
        ('echo "a\\"b"', [("echo", 'a"b')]),
        ("echo x # ; rm -rf ~", [("echo", "x")]),
        ("echo a#b", [("echo", "a#b")]),
        ("echo $(a; b) `c; d`", [("echo", "$(a; b)", "`c; d`")]),
        ('echo "$(a "b; c")"', [("echo", '$(a "b; c")')]),
        ("diff <(a; b) f", [("diff", "<(a; b)", "f")]),
        ("{ a; }", [("a",)]),
        ("(a; b)", [("a",), ("b",)]),
        ("! a", [("a",)]),
        ("echo $'a\\'b' c", [("echo", "a\\'b", "c")]),
        ("a \\\n b", [("a", "b")]),
        ("", []),
    ],
)
def test_words_and_separators(text, expected):
    assert argvs(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("echo x > f", ["f"]),
        ("echo x >f", ["f"]),
        ("echo x >> f", ["f"]),
        ("echo x >| f", ["f"]),
        ("echo x &> f", ["f"]),
        ("echo x &>> f", ["f"]),
        ("echo x >& f", ["f"]),
        ("echo x 2> f", ["f"]),
        ('echo x > "$HOME/.bashrc"', ["$HOME/.bashrc"]),
        ("echo x <> f", ["f"]),
        ("a>f", ["f"]),
        # 書き込みではない
        ("echo x 2>&1", []),
        ("echo x >&2", []),
        ("echo x >& 2", []),
        ("echo x 2>&-", []),
        ("cat < f", []),
        ("cat <<< f", []),
        ("echo 'a > b'", []),
        ('echo "a > b"', []),
        ("echo 2 > f", ["f"]),
    ],
)
def test_redirect_targets(text, expected):
    assert writes(text) == expected


def test_redirects_are_not_arguments():
    (cmd,) = shellparse.parse("cp a ~/.bashrc 2>&1 >/dev/null")
    assert cmd.argv == ("cp", "a", "~/.bashrc")
    assert [(r.fd, r.op) for r in cmd.redirects] == [("2", ">&"), ("", ">")]
    assert cmd.redirects[0].target is None


def test_fd_digits_need_an_operator():
    (cmd,) = shellparse.parse("echo 123abc 2x")
    assert cmd.argv == ("echo", "123abc", "2x")
    assert cmd.redirects == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$TOKEN", "$TOKEN"),
        ("'$TOKEN'", ""),
        ('"$TOKEN"', '"$TOKEN"'),
        ('"Don\'t"', '"Don\'t"'),
        ("'a'$TOKEN'b'", "$TOKEN"),
        ("\\$TOKEN", "\\$TOKEN"),
        ("$'x$TOKEN'", "$"),
    ],
)
def test_expandable_drops_only_single_quoted_spans(raw, expected):
    (cmd,) = shellparse.parse(f"echo {raw}")
    assert cmd.words[1].expandable == expected


def test_heredoc_body_is_not_skipped():
    """実行されない本文は split_heredoc_body が先に取り除く。ここで読み飛ばすと
    ``bash <<EOF`` の本文 (実行される) の検査が漏れる。"""
    assert argvs("bash <<EOF\nrm -rf ~\nEOF") == [("bash",), ("rm", "-rf", "~"), ("EOF",)]


@pytest.mark.parametrize(
    "text",
    [
        "echo 'unterminated",
        'echo "unterminated',
        "echo $(unterminated",
        "echo `x",
        "a \\",
        "&",
        ">",
    ],
)
def test_malformed_input_does_not_hang_or_raise(text):
    shellparse.parse(text)
