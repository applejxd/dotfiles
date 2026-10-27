"""harness/pending-store.ts の試験 (CHG-0046 の試作)。

``test/agents/pi/pending_store_driver.mjs`` が使い捨てのリポジトリで場面を動かし、結果を JSON で出す。
node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "pending_store_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def t() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_saved_content_is_what_was_shown_even_if_the_index_changed_while_waiting(t) -> None:
    s = t["shown"]
    assert s["snapOk"] and s["savedOk"]
    # 待つ間にステージした y.txt と、x.txt の書き換えは入らない
    assert s["files"] == ["a.txt", "x.txt"]
    assert s["xContent"] == "shown"


def test_saving_touches_nothing_the_user_has(t) -> None:
    s = t["shown"]
    assert s["parentIsBase"]
    assert s["headUnchanged"] and s["branchUnchanged"]
    assert s["indexUnchanged"] and s["statusUnchanged"]


def test_the_message_keeps_the_text_and_records_the_origin(t) -> None:
    m = t["shown"]["message"]
    assert m.startswith("feat: shown\n")
    assert "Pi-Pending-Request: req1" in m
    assert "Pi-Pending-Branch: refs/heads/main" in m


def test_saved_items_are_independent_snapshots(t) -> None:
    s = t["independent"]
    assert s["bothOk"] and s["distinctRefs"]
    # 2 つ目の親は、1 つ目ではなく表示時点の HEAD
    assert s["parent2IsBase"]
    # 同じ tree でもメッセージが違えば保存できる
    assert s["sameTree"]


def test_list_show_and_drop_only_touch_pending_refs(t) -> None:
    s = t["manage"]
    assert s["order"] == ["newer", "older"]
    assert s["branch"] == "refs/heads/main"
    assert s["shownHasFile"]
    assert s["refusedForeign"] is False and s["mainStillThere"]
    assert s["dropped"] is True
    assert s["remaining"] == ["newer"]


def test_nothing_staged_is_not_saved_and_an_unborn_repo_saves_without_a_parent(t) -> None:
    e = t["edge"]
    assert e["emptyIsNull"]
    assert e["unbornOk"] and e["unbornNoParent"] and e["unbornHeadMissing"]


def test_a_missing_tree_fails_instead_of_reporting_success(t) -> None:
    m = t["missing"]
    assert m["ok"] is False and m["hasReason"]
    assert m["refs"] == 0


def test_saving_runs_no_git_hook_and_leaves_the_real_index_bytes_alone(t) -> None:
    h = t["hooks"]
    assert h["savedOk"] and h["dropped"]
    assert h["ran"] == []
    assert h["indexBytesSame"]


def test_drop_cannot_reach_outside_the_pending_namespace(t) -> None:
    d = t["drop"]
    assert d["viaSymref"] is False
    assert d["mainSame"] and d["mainBranchSurvives"]
    assert d["wrongOid"] is False and d["stillThere"]
    assert d["odd"] is False
    assert d["listIgnoresSymref"]


def test_show_includes_the_patch_body(t) -> None:
    assert t["manage"]["shownHasPatch"]
