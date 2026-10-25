"""btw の表示部品 (view.ts)。pi に依存しないので node で直接動かす。see docs/spec/guard/pi-guard.md#自作の拡張-todo--plan--btw"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from agents_common import ROOT

VIEW = ROOT / "home" / "dot_pi" / "agent" / "extensions" / "btw" / "view.ts"

_RUNNER = """
const v = await import(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map(([fn, ...args]) => v[fn](...args))));
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


def test_clip_answer_keeps_short_text_and_marks_the_cut(tmp_path):
    short, cut = _run(tmp_path, [["clipAnswer", "abc", 10], ["clipAnswer", "x" * 30, 10]])
    assert short == "abc"
    assert cut.startswith("x" * 10 + "\n")
    assert "長いので省略" in cut and "全 30 文字" in cut and "x" * 11 not in cut


def test_viewport_height_leaves_room_for_the_frame_and_never_goes_below_three(tmp_path):
    big, small, tiny = _run(
        tmp_path, [["viewportHeight", 40], ["viewportHeight", 12], ["viewportHeight", 2]]
    )
    assert big == 32 and small == 4 and tiny == 3


@pytest.mark.parametrize(
    ("key", "top", "expected"),
    [
        ("down", 0, 1),
        ("up", 0, 0),  # 先頭より上へは出ない
        ("down", 90, 90),  # total 120・height 30 なので最大は 90
        ("pageDown", 0, 29),  # 1 行重ねて送る
        ("pageDown", 80, 90),
        ("pageUp", 10, 0),
        ("home", 50, 0),
        ("end", 0, 90),
    ],
)
def test_scrolled_stays_inside_the_content(tmp_path, key, top, expected):
    [got] = _run(tmp_path, [["scrolled", key, top, 120, 30]])
    assert got == expected


def test_scrolled_does_nothing_when_everything_fits(tmp_path):
    got = _run(tmp_path, [["scrolled", k, 0, 10, 30] for k in ("down", "pageDown", "end")])
    assert got == [0, 0, 0]


def test_vi_style_keys_map_to_scroll_keys(tmp_path):
    got = _run(tmp_path, [["keyFromChar", c] for c in ("j", "k", " ", "b", "g", "G", "x")])
    assert got == ["down", "up", "pageDown", "pageUp", "home", "end", None]


def test_position_label_is_one_based_and_clamped(tmp_path):
    [label] = _run(tmp_path, [["positionLabel", 90, 120, 30]])
    assert label == "91-120 / 120 行"
