"""読み上げ前処理: 表示用の書き方を、ENGINE に渡す前に整える唯一の入口。

字幕は台本の本文のまま(読みやすさ優先)にし、**ENGINE に渡す文だけ**をここで整える。
整形の規則は名前つきの表(RULES)で、理由と例を持つ。規則を足すときは、先に実エンジンで
影響を確かめ、`references/yomi.md` の「読み上げ前の整形」に書き、試験(`tests/test_speech.py`)
の例が通ることを確かめる。ENGINE に文を渡す経路(`tts_generate.py`・`readings.py` など)は、
必ず `prepare()` を通す。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yomi  # noqa: E402

# 日本語(ASCII 以外の文字)に隣り合う空白。英数字同士の空白は含めない
_JA_SPACE = re.compile(
    r"(?<=[^\x00-\x7f])[ \t\u3000]+(?=\S)|(?<=\S)[ \t\u3000]+(?=[^\x00-\x7f])"
)


class Rule(NamedTuple):
    id: str
    reason: str
    example: tuple[str, str]  # (表示用の書き方, ENGINE に渡す文)
    apply: Callable[[str, dict], str]


def _ja_space(text: str, entries: dict) -> str:
    return _JA_SPACE.sub("", text)


def _compound_hyphen(text: str, entries: dict) -> str:
    for s in yomi.present_compounds(text, entries):
        text = yomi._compound_re(s).sub(yomi.engine_surface(s), text)
    return text


RULES: list[Rule] = [
    Rule(
        "ja-space",
        "日本語と英数字の間の空白は、読み上げで息継ぎ(間)になる。字幕では読みやすいので残す",
        ("精度が 3 倍", "精度が3倍"),
        _ja_space,
    ),
    Rule(
        "compound-hyphen",
        "辞書の複合語(SLAM-MER)のハイフンは ENGINE の辞書に一致しないので、除いた形で渡す",
        ("SLAM-MER", "SLAMMER"),
        _compound_hyphen,
    ),
]


def prepare(text: str, entries: dict) -> str:
    """ENGINE に渡す文。規則を順に適用する(字幕は元のまま)。"""
    for r in RULES:
        text = r.apply(text, entries)
    return text


def explain(text: str, entries: dict) -> list[dict]:
    """文を変えた規則と、その適用後の文(規則の順)。変わらなければ空。"""
    out = []
    for r in RULES:
        after = r.apply(text, entries)
        if after != text:
            out.append({"rule": r.id, "before": text, "after": after})
        text = after
    return out


def applied(text: str, entries: dict) -> list[str]:
    """文を変えた規則の ID。"""
    return [x["rule"] for x in explain(text, entries)]
