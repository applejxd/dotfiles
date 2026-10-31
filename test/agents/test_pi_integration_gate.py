"""保護ブランチへの統合の確認 (harness/integration-gate.ts) の試験。使い捨ての実 git で、自由区の動的な検査まで確かめる。

判定器の結果を、必要なら必須確認に引き上げるだけで、緩める方向には働かない。git を起動するのは head のときだけ。
see docs/change/0053-worktree-integration-gate.md
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

DRIVER = ROOT / "test" / "agents" / "pi" / "integration_gate_driver.mjs"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="シェルスクリプトの偽 git を使う")
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
PREFIX = "確認が必要な保護ブランチへの統合 (bypass でも確認する): "

ALLOW = {"decision": "allow", "reason": "bypass", "source": "rule"}
ASK = {"decision": "ask", "reason": "ask", "source": "rule"}
DENY = {"decision": "deny", "reason": "deny", "source": "rule"}
MUST = {"decision": "ask", "reason": "既存の必須確認", "source": "rule", "mustConfirm": True}


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
    """主 worktree (main) と、linked の feature/x と develop。"""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "commit", "-q", "--allow-empty", "-m", "init")
    out = {"main": main}
    for name, branch in (("feature", "feature/x"), ("develop", "develop")):
        path = tmp_path / f"wt-{name}"
        _git(main, "worktree", "add", "-q", "-b", branch, str(path))
        out[name] = path
    return out


def _run(cases: list[dict], env: dict | None = None) -> list[dict]:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    payload: dict = {"cases": cases}
    if env is not None:
        payload["env"] = env
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _one(command: str, cwd: Path | str, d: dict = ALLOW, **extra) -> dict:
    return _run([{"d": d, "input": {"command": command}, "cwd": str(cwd), **extra}])[0]


def _raised(r: dict, d: dict) -> bool:
    """必須確認に引き上げられたか。"""
    return (
        r["decision"] == "ask"
        and r.get("mustConfirm") is True
        and r["reason"].startswith(PREFIX)
        and r != d
    )


# --- always / unknown は、どこからでも必須確認 -----------------------------------------


@pytest.mark.parametrize("from_", ["main", "feature", "develop"])
@pytest.mark.parametrize(
    "command",
    [
        "git flow feature finish x --squash",
        "git flow feature delete x",
        "git branch -m develop old",
        "git update-ref refs/heads/develop HEAD",
        "git symbolic-ref HEAD refs/heads/develop",
        "git fetch . feature/x:develop",
        "cd /somewhere && git flow feature finish x",
    ],
)
def test_always_and_unknown_are_must_confirm_from_any_worktree(repos, from_, command):
    r = _one(command, repos[from_])
    assert _raised(r, ALLOW), r
    assert f"実行しようとしているコマンド: {command}" in r["reason"]


# --- head は、自由区の外だけ必須確認 -----------------------------------------------------


@pytest.mark.parametrize(
    "command", ["git merge develop", "git cherry-pick abc", "git pull", "git reset --soft HEAD~1"]
)
def test_head_commands_are_free_inside_a_feature_worktree(repos, command):
    # 自由区: 判定器の結果のまま (bypass の allow も ask もそのまま)
    assert _one(command, repos["feature"]) == ALLOW
    assert _one(command, repos["feature"], ASK) == ASK


@pytest.mark.parametrize("from_", ["main", "develop"])
@pytest.mark.parametrize(
    "command", ["git merge feature/x", "git cherry-pick abc", "git pull", "git reset --soft HEAD~1"]
)
def test_head_commands_are_must_confirm_outside_the_free_zone(repos, from_, command):
    for d in (ALLOW, ASK):
        r = _one(command, repos[from_], d)
        assert _raised(r, d), r
        assert "linked worktree の中ではない" in r["reason"]


def test_head_in_an_undeterminable_directory_confirms_instead_of_denying(tmp_path):
    # 判定できない (リポジトリでない・存在しない) ときは、deny にせず確認に倒す
    for cwd in (tmp_path, tmp_path / "no-such-dir"):
        r = _one("git merge x", cwd)
        assert r["decision"] == "ask" and r["mustConfirm"] is True, r


# --- 何もしないもの ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git status --short",
        "git log --oneline -3",
        "git add -A && git status --short",
        "git worktree list",
        "git branch --list 'feature/*'",
        "git branch -D feature/x",  # local_git の領分
        "git flow feature start y --worktree",
        "git commit -m 'git merge x'",
        'echo "git flow feature finish x"',
        "ls -la",
    ],
)
def test_other_commands_are_left_alone(repos, command):
    for d in (ALLOW, ASK):
        assert _one(command, repos["main"], d) == d


def test_deny_and_existing_must_confirm_are_kept_as_they_are(repos):
    assert _one("git flow feature finish x", repos["main"], DENY) == DENY
    assert _one("git flow feature finish x", repos["main"], MUST) == MUST
    assert _one("git merge x", repos["main"], MUST) == MUST


def test_only_shell_tools_are_judged(repos):
    for tool in ("read", "write", "edit", "task", "guarded_action"):
        r = _run(
            [
                {
                    "d": ALLOW,
                    "tool": tool,
                    "input": {"command": "git flow feature finish x"},
                    "cwd": str(repos["main"]),
                }
            ]
        )[0]
        assert r == ALLOW, tool
    # bg_run は bash と同じ
    r = _run(
        [
            {
                "d": ALLOW,
                "tool": "bg_run",
                "input": {"command": "git flow feature finish x"},
                "cwd": str(repos["main"]),
            }
        ]
    )[0]
    assert _raised(r, ALLOW)


def test_disabled_changes_nothing(repos):
    r = _run(
        [
            {
                "d": ALLOW,
                "input": {"command": "git flow feature finish x"},
                "cwd": str(repos["main"]),
                "enabled": False,
            }
        ]
    )[0]
    assert r == ALLOW


def test_the_protected_list_is_a_parameter(repos):
    c = "git branch -m release/9 old"
    assert _raised(_one(c, repos["main"]), ALLOW)  # 下限に release/* がある
    assert _one(c, repos["main"], protected=["main", "develop"]) == ALLOW


def test_the_command_in_the_reason_is_clipped_and_one_line_per_field(repos):
    long = "git flow feature finish " + "x" * 500
    r = _one(long, repos["main"])
    assert _raised(r, ALLOW) and len(r["reason"]) < 600


# --- 設定 ----------------------------------------------------------------------------------


def _config(common: dict) -> dict:
    node = _node()
    if node is None:
        pytest.skip("node が無い (または古い)")
    out = subprocess.run(
        [node, str(DRIVER)],
        input=json.dumps({"config": common}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def test_config_is_enabled_only_by_the_confirm_flag():
    floor = ["main", "master", "develop", "release/*", "hotfix/*"]
    assert _config({}) == {"enabled": False, "protectedRefs": floor}
    assert _config({"pi": {"confirm": {"integration": False}}})["enabled"] is False
    assert _config({"pi": {"confirm": {"integration": "yes"}}})["enabled"] is False
    c = _config(
        {"pi": {"confirm": {"integration": True}, "integrate": {"protected_refs": ["main", "x/*"]}}}
    )
    assert c == {"enabled": True, "protectedRefs": ["main", "x/*"]}
    # 不正な保護 ref の一覧は、下限に戻す (生成器が先に拒否するので、ここは念のため)
    assert _config({"pi": {"integrate": {"protected_refs": [1]}}})["protectedRefs"] == floor
    assert _config({"pi": {"integrate": {"protected_refs": []}}})["protectedRefs"] == floor


# --- git の起動回数 (毎回の判定で git を起動しない) --------------------------------------------


def _fake_git(tmp_path: Path) -> dict:
    real = subprocess.run(
        ["which", "git"], capture_output=True, text=True, check=True
    ).stdout.strip()
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(f'#!/bin/sh\necho x >> "$COUNT"\nexec "{real}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "COUNT": str(tmp_path / "count"),
    }


def _count(tmp_path: Path) -> int:
    p = tmp_path / "count"
    return len(p.read_text().split()) if p.exists() else 0


@POSIX_ONLY
@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "git status",
        "git log --oneline",
        "git flow feature finish x",
        "git branch -m develop y",
        "cd x && git merge y",
        "echo git merge x",
    ],
)
def test_git_is_not_started_unless_the_command_is_a_head_command(repos, tmp_path, command):
    env = _fake_git(tmp_path)
    _run([{"d": ALLOW, "input": {"command": command}, "cwd": str(repos["main"])}], env=env)
    assert _count(tmp_path) == 0


@POSIX_ONLY
def test_git_is_started_at_most_twice_for_a_head_command(repos, tmp_path):
    env = _fake_git(tmp_path)
    _run(
        [{"d": ALLOW, "input": {"command": "git merge develop"}, "cwd": str(repos["feature"])}],
        env=env,
    )
    assert _count(tmp_path) == 2
    (tmp_path / "count").unlink()
    _run(
        [{"d": ALLOW, "input": {"command": "git merge develop"}, "cwd": str(repos["main"])}],
        env=env,
    )
    assert 1 <= _count(tmp_path) <= 2
