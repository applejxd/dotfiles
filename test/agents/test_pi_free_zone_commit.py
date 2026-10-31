"""git_commit の確認の省略 (自由区) の試験。使い捨ての実 git で、executeAction を偽の ctx から直接動かす。

設定 (`[pi.integrate] skip_confirm_in_free_zone`) が偽の間は何も省略せず、判定を結果に添える (観測)。
真のときだけ、feature の linked worktree の git_commit が確認なしで実行される。
実行直前に判定し直し、結果は「承認した内容のとおり」と書かない。
see docs/change/0053-worktree-integration-gate.md
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "free_zone_commit_driver.mjs"
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
APPROVE = "承認して実行"
ON = {"judge": {"common": {"pi": {"integrate": {"skip_confirm_in_free_zone": True}}}}}
OFF = {"judge": {"common": {"pi": {"integrate": {"skip_confirm_in_free_zone": False}}}}}


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *IDENT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, Path]:
    """主 worktree (main) と、その中にある linked の feature/x・develop・detached。"""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "commit", "-q", "--allow-empty", "-m", "init")
    out = {"main": main}
    for name, branch in (("feature", "feature/x"), ("develop", "develop")):
        path = main / f"wt-{name}"
        _git(main, "worktree", "add", "-q", "-b", branch, str(path))
        out[name] = path
    detached = main / "wt-detached"
    _git(main, "worktree", "add", "-q", "--detach", str(detached))
    out["detached"] = detached
    return out


def _stage(repo: Path, name: str = "f.txt") -> None:
    (repo / name).write_text("x\n", encoding="utf-8")
    _git(repo, "add", name)


def _run(**req) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(req),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return json.loads(out.stdout)


def _commit(repos, where: str, rules, hasUI=True, answers=(APPROVE,), **extra) -> dict:
    target = repos[where]
    _stage(target)
    return _run(
        cwd=str(extra.pop("cwd", target)),
        target=str(target),
        message="feat: x\n\nbody",
        hasUI=hasUI,
        rules=rules,
        answers=list(answers),
        **extra,
    )


# --- 設定が真: 自由区だけ確認を省略する ------------------------------------------------------------


@pytest.mark.parametrize("has_ui", [True, False])
def test_a_feature_worktree_commit_runs_without_a_confirmation(repos, has_ui):
    r = _commit(repos, "feature", ON, hasUI=has_ui)
    assert r["calls"]["select"] == [], r  # 確認を出さない (UI が無くても進む)
    assert r["result"]["ok"] is True and r["advanced"] is True and r["subject"] == "feat: x"
    text = r["result"]["text"]
    assert "確認なしで実行した (自由区: refs/heads/feature/x" in text, text
    assert "実行後の HEAD:" in text and "承認した内容のとおり" not in text
    assert r["result"]["details"]["freeZone"] == {
        "free": True,
        "reason": "feature の linked worktree",
        "branch": "refs/heads/feature/x",
        "skipped": True,
    }


def test_the_dir_argument_into_a_feature_worktree_is_also_free(repos):
    # 主 worktree から、その中の feature の worktree へ dir で指す。判定は解決済みの対象 (feature) に対して行う
    target = repos["feature"]
    _stage(target)
    r = _run(
        cwd=str(repos["main"]),
        target=str(target),
        dir="wt-feature",
        message="feat: via dir",
        hasUI=True,
        rules=ON,
        answers=[],
    )
    assert r["calls"]["select"] == [] and r["advanced"] is True, r
    assert r["result"]["details"]["freeZone"]["skipped"] is True


@pytest.mark.parametrize("where", ["main", "develop", "detached"])
def test_outside_the_free_zone_the_confirmation_is_unchanged(repos, where):
    r = _commit(repos, where, ON)
    assert len(r["calls"]["select"]) == 1, r  # 従来どおり確認する
    assert r["advanced"] is True and "承認した内容のとおり" in r["result"]["text"]
    assert r["result"]["details"]["freeZone"]["free"] is False
    assert r["result"]["details"]["freeZone"]["skipped"] is False


@pytest.mark.parametrize("where", ["main", "develop"])
def test_outside_the_free_zone_without_a_ui_is_still_deferred(repos, where):
    r = _commit(repos, where, ON, hasUI=False)
    assert r["result"]["ok"] is False and r["result"]["text"].startswith("not approved:")
    assert r["advanced"] is False


def test_a_rejection_outside_the_free_zone_does_not_commit(repos):
    r = _commit(repos, "main", ON, answers=["拒否"])
    assert r["result"]["ok"] is False and r["advanced"] is False


# --- 実行直前の再判定 -------------------------------------------------------------------------------


def test_the_zone_is_checked_again_just_before_running(repos):
    r = _commit(repos, "feature", ON, flip=True)
    assert r["zoneCalls"] == 2
    assert r["result"]["ok"] is False and "自由区ではなくなった" in r["result"]["text"]
    assert r["advanced"] is False and r["calls"]["select"] == []


# --- 子・設定が偽・不正な設定 ----------------------------------------------------------------------------


def test_a_child_is_still_refused(repos):
    r = _commit(repos, "feature", ON, child=True)
    assert r["result"]["ok"] is False and r["advanced"] is False


def test_while_the_setting_is_off_nothing_is_skipped_and_the_zone_is_reported(repos):
    r = _commit(repos, "feature", OFF)
    assert len(r["calls"]["select"]) == 1 and r["advanced"] is True  # 確認は従来どおり
    text = r["result"]["text"]
    assert "承認した内容のとおり" in text
    assert "自由区の判定 (観測中。確認は省略していない): free" in text, text
    assert r["result"]["details"]["freeZone"]["skipped"] is False
    # 自由区の外でも、判定は観測として添える
    r = _commit(repos, "main", OFF)
    assert "自由区の判定 (観測中。確認は省略していない): not free" in r["result"]["text"]


@pytest.mark.parametrize(
    "rules",
    [
        {},
        {"judge": {}},
        {"judge": {"common": {"pi": {"integrate": {"skip_confirm_in_free_zone": "yes"}}}}},
    ],
)
def test_a_missing_or_malformed_setting_never_skips(repos, rules):
    r = _commit(repos, "feature", rules)
    assert len(r["calls"]["select"]) == 1, r


def test_the_protected_list_is_read_from_the_settings(repos):
    # feature/x を保護にすると (実運用では下限に加える設定)、自由区ではなくなる
    rules = {
        "judge": {
            "common": {
                "pi": {
                    "integrate": {
                        "skip_confirm_in_free_zone": True,
                        "protected_refs": [
                            "main",
                            "master",
                            "develop",
                            "release/*",
                            "hotfix/*",
                            "feature/x",
                        ],
                    }
                }
            }
        }
    }
    r = _commit(repos, "feature", rules)
    assert len(r["calls"]["select"]) == 1 and r["result"]["details"]["freeZone"]["free"] is False
