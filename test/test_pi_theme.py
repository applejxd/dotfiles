"""pi の stock 配布テーマ iceberg (home/dot_pi/agent/themes/iceberg.json) を検証する。

- JSON として読め、name / appearance が決まった値であること
- colors の値が 16 進の色か vars の名前で、循環・未定義が無いこと
- 背景 #161821 に対する WCAG のコントラスト比 (text は 7 以上、主要な前景色は 4.5 以上)
- pi 本体の組み込み dark.json があるときだけ、colors のキーの集合が一致すること
実機の pi は起動しない。
see docs/spec/agent-config-generation.md#テーマicebergstock
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
