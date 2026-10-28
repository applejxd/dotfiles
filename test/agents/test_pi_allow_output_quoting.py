"""allow の一覧に当たるコマンドでも、`--output` (出力先のファイルを上書きできる) は allow にしない。

生の文字列の `--output` 検査は、`--out"put"=x` のように引用で分割するとすり抜けた (2026-10-29 に `review` が指摘し、実測で確認)。
引用を外したトークンでも検査する。git は曖昧でない省略形 (`--out`) も受け付けるので、その形も止める。

see docs/spec/guard/pi-decide.md#評価の順番
"""

from __future__ import annotations

import pytest
from test_pi_confirm import _bash, _judge, needs_node

pytestmark = needs_node

SPLIT_OUTPUT = [
    'git log --out"put"=x.txt',
    "git log --out''put=x.txt",
    "git log --o\\utput=x.txt",
    'git log "--out"put=x.txt',
    "git log --ou=x.txt",
    "git log --out=x.txt",
    "git log --outp=x.txt",
    "git log --outpu=x.txt",
    "git log --output=x.txt",
    "git log --output x.txt",
    'git log "--output=x.txt"',
    "git log '--output=x.txt'",
    'git log --oneline && git log --out"put"=x.txt',
    "bash -c 'git log --out\"put\"=x.txt'",
]

STILL_ALLOWED = [
    "git log",
    "git log --oneline",
    "git log --oneline -3",
    "git log --format=%H -1",
    "git log --since=yesterday --author=me",
    "wc -l a.txt",
    "grep -n x a.txt",
]


@pytest.mark.parametrize("role", ["implementer", "worker"])
def test_a_split_or_abbreviated_output_option_is_not_allowed(role):
    out = _judge([_bash(c, role=role) for c in SPLIT_OUTPUT])
    for command, res in zip(SPLIT_OUTPUT, out, strict=True):
        assert res["decision"] != "allow", (role, command, res)


@pytest.mark.parametrize("role", ["implementer", "worker"])
def test_ordinary_allowed_commands_stay_allowed(role):
    out = _judge([_bash(c, role=role) for c in STILL_ALLOWED])
    for command, res in zip(STILL_ALLOWED, out, strict=True):
        assert res["decision"] == "allow", (role, command, res)
