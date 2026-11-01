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


def _sec(snap, key):
    return next(s for s in snap["sections"] if s["key"] == key)


def test_empty_input_renders_every_section(table):
    text = "\n".join(table["empty"]["lines"])
    for title in ("要対応", "子", "隔離 worker", "feature ⇄ worktree", "保留", "モード・bg"):
        assert title in text
    keys = [s["key"] for s in table["empty"]["snap"]["sections"]]
    assert keys == ["attention", "features", "pending", "children", "isolation", "modes"]


def test_children_isolation_pending_and_features_share_one_screen(table):
    text = "\n".join(table["full"])
    assert "c1 worker running 3m12s" in text
    assert "j1 running pi-agent-j1" in text
    assert "主 develop repo" in text
    assert "feature board-model feature/board-model board-model" in text
    assert "隔離 j1" in text
    assert "cdef git_push pending 1m30s" in text  # id は末尾 4 桁 (/pending と同じ)
    assert "01234567" not in text
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
    sec = _sec(table["many"]["snap"], "children")
    assert sec["count"] == 20 and len(sec["rows"]) == 12 and sec["omitted"] == 8
    assert "  … 8 件省略" in table["many"]["lines"]


def test_broken_isolation_record_is_shown_as_broken(table):
    sec = _sec(table["broken"]["snap"], "isolation")
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


def test_attention_section_is_first_and_lists_waiting_items(table):
    snap = table["attention"]["snap"]
    assert snap["sections"][0]["key"] == "attention"
    sec = snap["sections"][0]
    texts = [r["text"] for r in sec["rows"]]
    # 承認待ちは古い順 (2 時間前 → 1 分前)、そのあとに決着待ち (gone・unknown・実行者の記録なし)
    assert texts == [
        "承認待ち 2222 git_push feature/old 2h00m",
        "承認待ち 1111 git_integrate feature/new 1m00s",
        "決着待ち 3333 git_integrate 5s",
        "決着待ち 5555 git_unk 5s",
        "決着待ち 6666 git_noowner 5s",
        "→ /pending",
    ]
    assert sec["count"] == 5  # 「→ /pending」は数えない
    joined = "\n".join(texts)
    assert "4444" not in joined and "7777" not in joined  # alive の running と done は入らない
    # alive の running は保留の節には残る
    assert any("4444" in r["text"] for r in _sec(snap, "pending")["rows"])


def test_attention_is_none_when_nothing_waits(table):
    sec = table["attentionAlive"]
    assert sec["key"] == "attention" and sec["count"] == 0 and sec["rows"] == []
    assert not any("→ /pending" in r["text"] for r in sec["rows"])
    lines = table["empty"]["lines"]
    assert lines[1].startswith("■ 要対応 (0)") and lines[2] == "  なし"


def test_attention_lines_fit_44_cells(table):
    lines = table["attention"]["lines"]
    assert any("→ /pending" in ln for ln in lines)
    assert all(
        sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in ln) <= 44 for ln in lines
    )


def test_feature_rows_show_state(table):
    lines = table["featState"]["lines80"]
    assert "  feature p ↑2 ↓1 dirty 3h12m 保留あり" in lines
    assert "  feature clean ↑0 ↓0" in lines  # clean は dirty と書かない。経過・保留も無し
    # 状態が無い feature は従来の形
    assert "  feature nostate feature/nostate nostate" in lines
    assert "  主 develop repo" in lines


def test_feature_state_is_kept_when_the_name_is_long(table):
    f = table["featState"]
    assert max(f["widths44"]) <= 44
    long = next(ln for ln in f["lines44"] if "feature a-v" in ln)
    assert long.endswith("↑12 ↓3 dirty 3h12m 保留あり")  # 状態は欠けず、名前の方が切れる
    assert "…" in long
    zen = next(ln for ln in f["lines44"] if "全角" in ln)
    assert zen.endswith("↑1 ↓0 dirty 保留あり") and "…" in zen


def test_bg_row_only_when_bg_jobs_are_known(table):
    assert not any("bg ジョブ" in ln for ln in table["noBg"])
    assert any("bg ジョブ 実行中0 完了0" in ln for ln in table["withBg"])


def test_no_wide_char_helper_drift():
    # 試験側の幅の数え方 (driver) が全角を 2 とみなす前提の確認
    assert unicodedata.east_asian_width("全") == "W"
