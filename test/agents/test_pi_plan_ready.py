"""計画モード (plan 拡張) の確認画面「計画をどうしますか？」を、計画が詰まった応答にだけ出すことを固定する。

応答に番号付きの行があるだけでは出さない (相談の途中の応答で毎回聞かれるのを避ける)。
見出し「## 実行計画」と番号付きの手順の両方があるときだけ出す。判定は ``isPlanReady`` (index.ts の名前つき export)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "test" / "agents" / "pi" / "plan_ready_driver.mjs"
INDEX = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "plan" / "index.ts"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

READY = "調べた結果です。\n\n## 実行計画\n1. 拡張を直す。触るのは index.ts。確認は試験。\n2. 仕様書を直す。\n"
NUMBERED_ONLY = "次の手順です。\n1. 調べる。\n2. 直す。\n"
HEADING_ONLY = "## 実行計画\nまだ詰めている最中です。\n"
QUESTION = "どちらにしますか。A か B です。\n"


def _run(cases: list[str]) -> list[bool]:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    return json.loads(proc.stdout)


def test_confirmation_only_for_ready_plan() -> None:
    assert _run([READY, NUMBERED_ONLY, HEADING_ONLY, QUESTION]) == [True, False, False, False]


def test_heading_levels_and_spacing() -> None:
    # 見出しの級（# 〜 ###）と、# の後の空白の有無は許す。本文中の言及（行頭でない）は許さない
    body = "1. 手順\n"
    assert _run(
        [
            f"# 実行計画\n{body}",
            f"### 実行計画\n{body}",
            f"##実行計画\n{body}",
            f"本文で「## 実行計画」と書く。\n{body}",
        ]
    ) == [
        True,
        True,
        True,
        False,
    ]


def test_prompt_tells_model_when_to_show_the_heading() -> None:
    # 指示文が、見出しは「計画が詰まったと判断したときだけ」と伝えていること (毎回番号付きで終える指示に戻っていない)
    src = INDEX.read_text(encoding="utf-8")
    assert "最後の応答は、番号付きの手順で終える" not in src
    assert "## 実行計画" in src
    assert "それ以外の応答" in src
