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
        ["which", "git"], capture_output=True, text=True, encoding="utf-8", check=True
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


# --- `cd <リテラル> &&` が付いた head コマンド: cd 先が自由区なら許可 (feature への develop の取り込みなど) ------------


@pytest.mark.parametrize("from_", ["main", "develop", "feature"])
@pytest.mark.parametrize(
    "template",
    [
        "cd {feature} && git merge develop --no-edit",
        'cd "{feature}" && git merge develop -m "Merge develop"',
        "cd '{feature}' && git cherry-pick abc",
    ],
)
def test_cd_into_a_feature_worktree_is_free_for_head_commands(repos, from_, template):
    command = template.format(feature=repos["feature"])
    # 元の cwd が何であれ、実際に動く cd 先 (feature の linked worktree) で見る。判定器の結果のまま
    assert _one(command, repos[from_]) == ALLOW
    assert _one(command, repos[from_], ASK) == ASK


def test_a_relative_cd_confirms(repos, tmp_path):
    # 相対パスは CDPATH で別の場所になりうるので対象外
    assert _raised(_one("cd wt-feature && git merge develop", tmp_path), ALLOW)
    assert _raised(_one("cd ./wt-feature && git merge develop", tmp_path), ALLOW)


def test_a_symlink_is_judged_by_its_target(repos, tmp_path):
    to_feature = tmp_path / "link-feature"
    to_develop = tmp_path / "link-develop"
    to_feature.symlink_to(repos["feature"])
    to_develop.symlink_to(repos["develop"])
    assert _one(f"cd {to_feature} && git merge develop", repos["develop"]) == ALLOW
    assert _raised(_one(f"cd {to_develop} && git merge feature/x", repos["feature"]), ALLOW)


def test_a_dotdot_path_confirms(repos):
    assert _raised(
        _one(f"cd {repos['feature']}/../wt-develop && git merge x", repos["feature"]), ALLOW
    )
    assert _raised(
        _one(f"cd {repos['feature']}/../wt-feature && git merge develop", repos["feature"]), ALLOW
    )


@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"])
def test_an_inherited_repo_selecting_variable_confirms_the_cd_form(repos, monkeypatch, var):
    monkeypatch.setenv(var, str(repos["develop"] / ".git"))
    r = _one(f"cd {repos['feature']} && git reset --soft feature/x", repos["develop"])
    assert _raised(r, ALLOW), r


@pytest.mark.parametrize("target", ["main", "develop"])
def test_cd_into_main_or_a_protected_branch_still_confirms(repos, target):
    # develop (保護ブランチ) の worktree・本体の worktree への cd は、cd が付いても必須確認
    command = f"cd {repos[target]} && git merge feature/x"
    for d in (ALLOW, ASK):
        r = _one(command, repos["feature"], d)
        assert _raised(r, d), r
        assert "cd 先" in r["reason"] and "linked worktree の中ではない" in r["reason"]


def test_cd_into_a_missing_directory_confirms(repos, tmp_path):
    r = _one(f"cd {tmp_path}/no-such && git merge develop", repos["feature"])
    assert _raised(r, ALLOW) and "存在しない" in r["reason"], r


@pytest.mark.parametrize(
    "template",
    [
        "cd $WT && git merge develop",  # 変数
        "cd ~/x && git merge develop",  # ~
        "cd $(pwd) && git merge develop",  # コマンド置換
        "cd -- {feature} && git merge develop",  # オプションに見える
        "cd {feature}/* && git merge develop",  # グロブ
        "cd {feature} || git merge develop",  # || は、cd が失敗したときに元の cwd で動く
        "cd {feature}; git merge develop",  # 区切りは && だけ
        "cd {feature} && env -C {main} git merge feature/x",  # env -C は redirect でなく、残りが head になる
        "cd {feature} && env --chdir={main} git merge feature/x",
        "cd {feature} && eval 'cd {main} && git merge feature/x'",
        "cd {feature} && sh -c 'cd {main} && git merge feature/x'",
        "cd {feature} && command git merge develop",
        "cd {feature} && git status&git merge feature/x",  # 空白なしの & (左が非同期で動く)
        "cd {feature}\u00a0; git merge feature/x",  # NBSP は Bash では cd の引数の一部
        "cd {feature} && git merge develop | tail -3",
        "cd {feature} && git merge develop 2>&1",
        "cd {feature} && (git merge develop)",
        "cd {feature} && git merge develop; git -C {main} merge feature/x",
        'cd {feature} && git merge develop -m "$(id)"',
        "echo hi; cd {feature} && git merge develop",  # 先頭が cd でない
        "cd {feature} && cd {main} && git merge develop",  # 残りに別の cd
        "cd {feature} && git -C {main} merge develop",  # 残りに -C
        "cd {feature} && git merge develop && cd {main} && git merge feature/x",
        "cd {feature} && GIT_DIR={main}/.git git merge develop",
        "cd {feature} && git merge develop & git -C {main} merge feature/x",  # & で並べた別の宛先
        "cd {feature} && git merge develop\ngit -C {main} merge feature/x",  # 改行で並べた別の宛先
        "cd {feature} && git merge develop || git -C {main} merge feature/x",
        "cd {feature} && (cd {main} && git merge feature/x)",  # サブシェルの中の cd
        "(cd {feature} && git merge develop)",  # 先頭が括弧 (解釈しない)
    ],
)
def test_a_cd_that_is_not_a_plain_literal_prefix_still_confirms(repos, template):
    command = template.format(feature=repos["feature"], main=repos["main"])
    r = _one(command, repos["feature"])
    assert _raised(r, ALLOW), r


@pytest.mark.parametrize(
    "template",
    [
        "cd {feature} && git flow feature finish x --squash",  # 保護ブランチへ直接統合するものは、cd が付いても必須確認
        "cd {feature} && git branch -m develop old",
        "cd {feature} && git update-ref refs/heads/develop HEAD",
        "cd {feature} && git merge develop && git flow feature finish x",
    ],
)
def test_integration_commands_that_change_a_protected_ref_still_confirm_after_a_cd(repos, template):
    command = template.format(feature=repos["feature"])
    for d in (ALLOW, ASK):
        assert _raised(_one(command, repos["feature"], d), d)


# --- checkout / switch: 保護ブランチへ入る形は必須確認、start-point として読む形は確認なし ---------------------------


@pytest.mark.parametrize("from_", ["main", "feature"])
def test_checkout_of_a_protected_branch_from_a_feature_confirms(repos, from_):
    command = "git checkout develop && git merge feature/x"
    for d in (ALLOW, ASK):
        assert _raised(_one(command, repos[from_], d), d)


@pytest.mark.parametrize("from_", ["main", "feature"])
@pytest.mark.parametrize(
    "command", ["git switch -c feature/y develop", "git checkout -b feature/y develop"]
)
def test_creating_a_feature_from_a_protected_start_point_is_free(repos, from_, command):
    assert _one(command, repos[from_]) == ALLOW
