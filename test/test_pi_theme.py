"""pi の stock 配布テーマ iceberg (home/dot_pi/agent/themes/iceberg.json) を検証する。

- JSON として読め、name / appearance が決まった値であること
- colors の値が 16 進の色か vars の名前で、循環・未定義が無いこと
- 背景 #161821 に対する WCAG のコントラスト比 (text は 7 以上、主要な前景色は 4.5 以上)
- 入力欄の枠 (思考レベルの色) が 7 段階で互いに違い、xhigh までは error の赤を使わないこと
- pi 本体の組み込み dark.json があるときだけ、colors のキーの集合が一致すること
実機の pi は起動しない。
see docs/spec/agent-config-generation.md#テーマiceberg
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
THEME_PATH = ROOT / "home/dot_pi/agent/themes/iceberg.json"
BACKGROUND = "#161821"
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
BUILTIN_DARK = (
    "node_modules/@earendil-works/pi-coding-agent/dist/modes/interactive/theme/dark.json"
)
# トークン名 -> 背景 #161821 に対して要る最小のコントラスト比
MIN_CONTRAST = {
    "text": 7.0,
    "muted": 4.5,
    "accent": 4.5,
    "warning": 4.5,
    "error": 4.5,
    "success": 4.5,
    "mdLink": 4.5,
}


def load_theme() -> dict:
    return json.loads(THEME_PATH.read_text(encoding="utf-8"))


def resolve(theme: dict, token: str) -> str:
    """colors[token] を vars の参照をたどって 16 進の色にする。循環・未定義は失敗させる。"""
    variables = theme["vars"]
    value = theme["colors"][token]
    seen: list[str] = []
    while not HEX_COLOR.match(value):
        assert value in variables, f"{token}: 未定義の名前 {value!r}"
        assert value not in seen, f"{token}: 循環参照 {[*seen, value]}"
        seen.append(value)
        value = variables[value]
    return value.lower()


def relative_luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def find_builtin_dark() -> Path | None:
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
    base = Path(agent_dir) if agent_dir else Path.home() / ".pi" / "agent"
    candidates = sorted((base / "install" / "releases").glob(f"*/{BUILTIN_DARK}"))
    return candidates[-1] if candidates else None


def test_theme_identity():
    theme = load_theme()
    assert theme["name"] == "iceberg"
    assert theme["appearance"] == "dark"


def test_colors_are_hex_or_defined_vars():
    theme = load_theme()
    for name, value in theme["vars"].items():
        assert HEX_COLOR.match(value), f"vars.{name} は 16 進の色であること: {value!r}"
    for token in theme["colors"]:
        assert HEX_COLOR.match(resolve(theme, token))
    for token, value in theme["export"].items():
        assert HEX_COLOR.match(value), f"export.{token}: {value!r}"


@pytest.mark.parametrize("token,minimum", MIN_CONTRAST.items())
def test_contrast_on_background(token: str, minimum: float):
    color = resolve(load_theme(), token)
    ratio = contrast_ratio(color, BACKGROUND)
    assert ratio >= minimum, f"{token} {color} の比 {ratio:.2f} < {minimum}"


def test_color_keys_match_builtin_dark():
    """組み込み dark.json が見つからないときは skip する (skip は通過ではない。未検査)。"""
    builtin = find_builtin_dark()
    if builtin is None:
        pytest.skip("pi 本体の組み込み dark.json が見つからない (キー集合は未検査)")
    expected = set(json.loads(builtin.read_text(encoding="utf-8"))["colors"])
    assert set(load_theme()["colors"]) == expected


THINKING_LEVELS = ("Off", "Minimal", "Low", "Medium", "High", "Xhigh", "Max")


def test_thinking_levels_are_distinct():
    """入力欄の枠は思考レベルで色が変わる。7 段階が互いに違う色であること。"""
    theme = load_theme()
    colors = [resolve(theme, f"thinking{level}") for level in THINKING_LEVELS]
    assert len(set(colors)) == len(colors), colors


def test_thinking_levels_up_to_xhigh_avoid_the_error_color():
    """xhigh を常用する人の入力欄が、エラーの赤に見えないこと (赤系は使わない。max だけは暖色でよい)。"""
    theme = load_theme()
    error = {resolve(theme, "error"), resolve(theme, "toolDiffRemoved"), theme["vars"]["redLight"].lower()}
    for level in THINKING_LEVELS[:-1]:
        assert resolve(theme, f"thinking{level}") not in error, level


@pytest.mark.parametrize("level", THINKING_LEVELS)
def test_thinking_colors_are_visible_as_a_border(level: str):
    """枠として見えるコントラスト (背景に対して 3 以上)。"""
    ratio = contrast_ratio(resolve(load_theme(), f"thinking{level}"), BACKGROUND)
    assert ratio >= 3.0, f"thinking{level} の比 {ratio:.2f}"


# 会話・ツールのブロック (ユーザーの入力・実行中・成功・失敗・拡張のメッセージ) は、端末の背景より明るい背景と色相の違いで区別する。
# 枠線は theme では引けない (pi の設定にも無い) ので、背景の明るさの差で境界を出す。
# 端末の背景は theme が決めない: iceberg の #161821 と、実測した Orca の端末 (iPhone) の #282c34 の両方に対して、比 1.3 以上にする
# (2026-11-10: 最初の調整は #161821 だけを基準にして、実際の #282c34 では 1.05〜1.17 しか無く、境界が見えなかった)。
TERMINAL_BACKGROUNDS = (BACKGROUND, "#282c34")
BLOCK_BACKGROUNDS = (
    "userMessageBg",
    "toolPendingBg",
    "toolSuccessBg",
    "toolErrorBg",
    "customMessageBg",
)
MIN_BLOCK_EDGE = 1.3


@pytest.mark.parametrize("terminal", TERMINAL_BACKGROUNDS)
@pytest.mark.parametrize("token", BLOCK_BACKGROUNDS)
def test_block_backgrounds_stand_out_from_the_terminal_background(token: str, terminal: str):
    ratio = contrast_ratio(resolve(load_theme(), token), terminal)
    assert ratio >= MIN_BLOCK_EDGE, f"{token} の端末の背景 {terminal} との比 {ratio:.2f} < {MIN_BLOCK_EDGE}"


def test_block_backgrounds_are_distinct_colors():
    theme = load_theme()
    colors = [resolve(theme, token) for token in BLOCK_BACKGROUNDS]
    assert len(set(colors)) == len(colors), colors


@pytest.mark.parametrize("token", BLOCK_BACKGROUNDS)
@pytest.mark.parametrize(
    ("foreground", "minimum"),
    [("text", 5.5), ("toolOutput", 4.5), ("toolTitle", 4.5)],
)
def test_text_is_readable_on_each_block_background(token: str, foreground: str, minimum: float):
    theme = load_theme()
    ratio = contrast_ratio(resolve(theme, foreground), resolve(theme, token))
    assert ratio >= minimum, f"{foreground} on {token}: {ratio:.2f} < {minimum}"
