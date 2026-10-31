"""オーケストレーターの盤面 (``home/dot_config/pi/harness/board.ts``) の純関数の試験。

``test/agents/pi/board_driver.mjs`` が固定の入力で ``buildBoard`` / ``renderBoard`` / ``parseWorktreePorcelain`` を動かし、
結果を JSON で出す (node の型除去を使うので、22.18 未満の node では飛ばす)。
"""

from __future__ import annotations

import json
import subprocess
import unicodedata

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "board_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def table():
    proc = subprocess.run(
        [_node(), str(RUNNER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_empty_input_renders_every_section(table):
    text = "\n".join(table["empty"]["lines"])
    for title in ("子", "隔離 worker", "feature ⇄ worktree", "保留", "モード・bg"):
        assert title in text
    assert len(table["empty"]["snap"]["sections"]) == 5


def test_children_isolation_pending_and_features_share_one_screen(table):
    text = "\n".join(table["full"])
    assert "c1 worker running 3m12s" in text
    assert "j1 running pi-agent-j1" in text
    assert "主 develop repo" in text
    assert "feature board-model feature/board-model board-model" in text
    assert "隔離 j1" in text
    assert "01234567 git_push pending 1m30s" in text
    assert "/pending list" in text and "旧形式の退避 2 件" in text
    assert "orchestrate on" in text and "sandbox fence" in text


@pytest.mark.parametrize("width", ["46", "80"])
def test_lines_fit_the_width_even_with_fullwidth_names(table, width):
    w = table["wide"][width]
    assert w["lines"] and max(w["widths"]) <= int(width)
    assert any("全角" in ln for ln in w["lines"])


def test_control_sequences_in_names_are_neutralised(table):
    text = "\n".join(table["hostile"])
    assert "\x1b" not in text and "\x07" not in text
    assert "\\x1b" in text


def test_row_limit_and_omitted_line(table):
    sec = table["many"]["snap"]["sections"][0]
    assert sec["count"] == 20 and len(sec["rows"]) == 12 and sec["omitted"] == 8
    assert "  … 8 件省略" in table["many"]["lines"]


def test_broken_isolation_record_is_shown_as_broken(table):
    sec = table["broken"]["snap"]["sections"][1]
    assert sec["count"] == 2 and any(r.get("broken") for r in sec["rows"])
    assert any("broken" in ln and "bad.json" in ln for ln in table["broken"]["lines"])


def test_parse_worktree_porcelain(table):
    main, feat, iso, bare, gone = table["porcelain"]
    assert main["branch"] == "main" and "featureName" not in main
    assert feat["featureName"] == "foo-bar" and feat["branch"] == "feature/foo-bar"
    assert iso["detached"] is True and iso["locked"] is True and iso["lockedReason"] == "in use"
    assert bare["bare"] is True and bare["path"] == "/bare.git"
    assert gone["prunable"] is True and gone["branch"] == "old"
    assert table["porcelainJunk"] == []


def test_output_has_no_approval_entrance(table):
    for ln in table["all"]:
        assert "/pending approve" not in ln and "resolve" not in ln


def test_snapshot_survives_json_roundtrip(table):
    assert table["roundtrip"] is True and table["v"] == 1


def test_owner_state_is_shown_as_is_and_unknown_is_not_called_dead(table):
    text = "\n".join(table["owners"])
    assert "実行者:alive" in text and "実行者:gone" in text
    assert text.count("実行者:unknown") == 2  # 明示の unknown と、未指定
    for ln in table["owners"]:
        if "実行者:unknown" in ln:
            assert "死" not in ln and "gone" not in ln


def test_no_wide_char_helper_drift():
    # 試験側の幅の数え方 (driver) が全角を 2 とみなす前提の確認
    assert unicodedata.east_asian_width("全") == "W"
