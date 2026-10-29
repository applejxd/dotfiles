"""harness/gitflow.ts の表試験 (CHG-0047)。

``test/agents/pi/gitflow_driver.mjs`` が純粋な関数を動かし、結果を JSON で出す。
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
DRIVER = HERE / "pi" / "gitflow_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")


@pytest.fixture(scope="module")
def t() -> dict:
    proc = subprocess.run(
        [_node(), str(DRIVER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_feature_names_are_restricted_to_safe_ref_names(t) -> None:
    n = t["names"]
    assert n["ok"] and n["dots"] and n["max"]
    for bad in (
        "empty",
        "dash_first",
        "help",
        "upper",
        "dotdot",
        "trailing_dot",
        "lock",
        "slash",
        "long",
        "space",
        "notString",
    ):
        assert n[bad] is False, bad


def test_the_trimmed_gitflow_lite_config_is_safe(t) -> None:
    assert t["good"] == {"ok": True, "problems": []}
    # start が書き、finish が消す実行時のキーは許す
    assert t["runtimeKeys"]["ok"], t["runtimeKeys"]
    assert t["pushFalse"]["ok"] and t["originOk"]["ok"] and t["wtAbsInside"]["ok"]
    # 後から書かれた値が勝つ (git の動き)
    assert t["laterWins"]["ok"]


def test_a_config_that_pushes_or_runs_outside_code_is_refused(t) -> None:
    for key in ("pushTrue", "pushtagTrue", "hooks", "filter", "origin"):
        assert t[key]["ok"] is False, key
    assert any("push" in p for p in t["pushTrue"]["problems"])
    assert any("外のコード" in p for p in t["hooks"]["problems"])


def test_a_config_that_changes_what_the_fixed_arguments_mean_is_refused(t) -> None:
    for key in (
        "badParent",
        "badPrefix",
        "badStrategy",
        "notInit",
        "tagTrue",
        "wtOutside",
        "wtDotdot",
        "wtSibling",
        "wtMissing",
        "unknown",
        "classicLeftovers",
    ):
        assert t[key]["ok"] is False, key


def test_the_fixed_arguments_never_reach_the_network_or_push(t) -> None:
    assert t["start"] == ["git", "flow", "feature", "start", "alpha", "--worktree", "--no-fetch"]
    finish = t["finish"]
    assert finish[:5] == ["git", "flow", "feature", "finish", "alpha"]
    for flag in ("--squash", "--keepremote", "--no-fetch", "--no-push", "--no-pushtag", "--notag"):
        assert flag in finish
    # メッセージは 1 つの要素で、`-` で始まっても引数として読まれない
    assert finish[finish.index("--squash") + 1] == "--squash-message=-weird: msg\n\n- bullet"
    assert not any(a in finish for a in ("--push", "--fetch", "--force", "--no-keepremote"))


def test_identify_model_table(t) -> None:
    """identifyModel: 最小の gitflow-lite だけが gitflow-lite。1 点でも崩す・足すと other。"""
    m = t["model"]
    assert m["lite"] == "gitflow-lite" and m["liteGood"] == "gitflow-lite"
    for key in (
        "empty",
        "notInit",
        "initFalse",
        "mergeStrategy",
        "badPrefix",
        "developParent",
        "noMain",
        "noDevelop",
        "noFeature",
        "fourth",
    ):
        assert m[key] == "other", key
