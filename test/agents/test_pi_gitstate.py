"""harness/gitstate.ts (git の状態の収集) の試験 (CHG-0049)。

実 git の使い捨てリポジトリを ``tmp_path`` に作り、``test/agents/pi/gitstate_driver.mjs`` で
``createProbe`` を動かして、所属・ブランチ・運用モデル・安全なプローブを確かめる。

tmp_path は実リポジトリの ``.tmp/`` の下になりうるので、probe の ``ceiling`` に tmp_path の親を渡し、
実リポジトリを拾わないようにする。git の呼び出しはグローバル設定に依存させない。
node の型除去を使うので、22.18 未満の node では飛ばす。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
DRIVER = HERE / "pi" / "gitstate_driver.mjs"

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

# このリポジトリの .gitflow と同じ内容 (gitflow-lite)
GITFLOW_LITE = """[gitflow]
\tversion = 1.0
\tinitialized = true
\tworktreePath = .tmp/worktrees/{{ branchName }}
[gitflow "branch.develop"]
\ttype = base
\tparent = main
\tupstreamStrategy = merge
\tdownstreamStrategy = merge
\tautoUpdate = true
\ttag = false
[gitflow "branch.feature"]
\ttype = topic
\tparent = develop
\tstartPoint = develop
\tupstreamStrategy = squash
\tdownstreamStrategy = rebase
\tprefix = feature/
\tautoUpdate = false
\ttag = false
\tworktree = false
[gitflow "branch.main"]
\ttype = base
\tupstreamStrategy = none
\tdownstreamStrategy = none
\tautoUpdate = false
\ttag = false
"""


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    for k in [k for k in env if k.startswith("GIT_")]:
        del env[k]
    home = tmp_path / "_home"
    home.mkdir(exist_ok=True)
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
    )
    return env


def git(tmp_path: Path, cwd: Path, *args: str) -> str:
    """グローバル設定に依存しない git を動かす。"""
    proc = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout.strip()


def make_repo(
    tmp_path: Path, name: str = "repo", branch: str = "develop", gitflow: str | None = GITFLOW_LITE
) -> Path:
    """使い捨てリポジトリを作る。gitflow があれば .gitflow をコミットする。"""
    repo = tmp_path / name
    repo.mkdir(parents=True)
    git(tmp_path, repo, "init", "-q", "-b", branch)
    (repo / "a.txt").write_text("a\n")
    if gitflow is not None:
        (repo / ".gitflow").write_text(gitflow)
    git(tmp_path, repo, "add", "-A")
    git(tmp_path, repo, "commit", "-q", "-m", "init")
    return repo


def probe(
    tmp_path: Path,
    steps: list[dict],
    *,
    fake: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> list:
    """driver を動かして steps の結果を返す。ceiling は tmp_path の親。"""
    arg = {"ceiling": [str(tmp_path.parent)], "steps": steps}
    if fake:
        arg["fake"] = fake
    env = _env(tmp_path)
    env.update(env_extra or {})
    proc = subprocess.run(
        [_node(), str(DRIVER), json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def owner(tmp_path: Path, path: Path, **kw) -> dict:
    return probe(tmp_path, [{"fn": "owner", "path": str(path)}], **kw)[0]


def model(tmp_path: Path, path: Path) -> str:
    return probe(tmp_path, [{"fn": "model", "path": str(path)}])[0]


# --- 1. 所属 ---------------------------------------------------------------


def test_owner_of_a_file_in_a_normal_repo_is_the_primary_worktree(tmp_path) -> None:
    """通常のリポジトリの下のファイルは primary の worktree で、HEAD は develop。"""
    repo = make_repo(tmp_path)
    o = owner(tmp_path, repo / "a.txt")
    assert o["kind"] == "worktree"
    assert o["primary"] is True
    assert o["head"] == {"kind": "branch", "ref": "refs/heads/develop"}
    assert o["top"] == str(repo.resolve())
    assert o["commonDir"] == str((repo / ".git").resolve())


def test_owner_of_a_linked_worktree_is_not_primary(tmp_path) -> None:
    """git worktree add で作った作業ツリーは primary でなく、commonDir は本体の .git。"""
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    git(tmp_path, repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
    o = owner(tmp_path, wt / "a.txt")
    assert o["kind"] == "worktree"
    assert o["primary"] is False
    assert o["head"] == {"kind": "branch", "ref": "refs/heads/feature/x"}
    assert o["top"] == str(wt.resolve())
    assert o["commonDir"] == str((repo / ".git").resolve())


def test_owner_of_a_detached_head_worktree_is_detached(tmp_path) -> None:
    """detached HEAD の作業ツリーは head=detached。"""
    repo = make_repo(tmp_path)
    git(tmp_path, repo, "checkout", "-q", "--detach")
    o = owner(tmp_path, repo / "a.txt")
    assert o["kind"] == "worktree"
    assert o["head"] == {"kind": "detached"}


def test_a_path_inside_the_git_dir_is_a_git_dir(tmp_path) -> None:
    """.git の中のパスは作業ツリーではなく git-dir。"""
    repo = make_repo(tmp_path)
    o = owner(tmp_path, repo / ".git" / "HEAD")
    assert o["kind"] == "git-dir"
    assert o["commonDir"] == str((repo / ".git").resolve())


def test_a_path_outside_any_repo_is_no_repo_without_running_git(tmp_path) -> None:
    """リポジトリの外は no-repo。親に .git が無いので git を起動しない (差し替えた git が呼ばれたら unknown になる)。"""
    outside = tmp_path / "plain"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    assert owner(tmp_path, outside / "f.txt") == {"kind": "no-repo"}
    assert owner(tmp_path, outside / "f.txt", fake="failed") == {"kind": "no-repo"}


# --- 2. 新規ファイル --------------------------------------------------------


def test_a_new_file_with_missing_parents_belongs_to_the_nearest_existing_parent(tmp_path) -> None:
    """存在しない深い親の下の新規ファイルは、存在する最寄りの親で所属が決まる。"""
    repo = make_repo(tmp_path)
    o = owner(tmp_path, repo / "no" / "such" / "dir" / "new.txt")
    assert o["kind"] == "worktree" and o["primary"] is True
    assert o["top"] == str(repo.resolve())
    # リポジトリの外の新規ファイルは no-repo
    (tmp_path / "plain").mkdir()
    assert owner(tmp_path, tmp_path / "plain" / "x" / "y" / "new.txt") == {"kind": "no-repo"}


# --- 3. 入れ子 --------------------------------------------------------------


def test_a_nested_independent_repo_is_owned_by_the_inner_repo(tmp_path) -> None:
    """入れ子の独立リポジトリの下は、内側が所有者 (top が内側)。"""
    outer = make_repo(tmp_path, "outer")
    inner = outer / "vendor" / "inner"
    inner.mkdir(parents=True)
    git(tmp_path, inner, "init", "-q", "-b", "main")
    (inner / "f.txt").write_text("f")
    o = owner(tmp_path, inner / "f.txt")
    assert o["kind"] == "worktree"
    assert o["top"] == str(inner.resolve())
    assert o["commonDir"] == str((inner / ".git").resolve())
    assert o["head"] == {"kind": "branch", "ref": "refs/heads/main"}


# --- 4. シンボリックリンク ---------------------------------------------------


def test_a_symlink_inside_the_repo_pointing_outside_is_no_repo(tmp_path) -> None:
    """リポジトリ内のリンク先がリポジトリ外なら、実体で判定して no-repo。"""
    repo = make_repo(tmp_path)
    outside = tmp_path / "plain"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    (repo / "link").symlink_to(outside)
    assert owner(tmp_path, repo / "link" / "f.txt") == {"kind": "no-repo"}


def test_a_symlink_outside_pointing_into_the_repo_is_a_worktree(tmp_path) -> None:
    """リポジトリ外のリンクが中を指すなら、実体で判定して worktree。"""
    repo = make_repo(tmp_path)
    outside = tmp_path / "plain"
    outside.mkdir()
    (outside / "link").symlink_to(repo)
    o = owner(tmp_path, outside / "link" / "a.txt")
    assert o["kind"] == "worktree"
    assert o["top"] == str(repo.resolve())


# --- 5. 運用モデル -----------------------------------------------------------


def test_model_is_gitflow_lite_when_develop_has_the_committed_gitflow(tmp_path) -> None:
    """develop にコミットされた .gitflow が gitflow-lite なら gitflow-lite。"""
    repo = make_repo(tmp_path)
    assert model(tmp_path, repo / "a.txt") == "gitflow-lite"


def test_model_ignores_edits_and_deletion_of_the_working_copy_gitflow(tmp_path) -> None:
    """作業コピーの .gitflow を改変・削除しても (コミットしなければ) model は変わらない。"""
    repo = make_repo(tmp_path)
    (repo / ".gitflow").write_text("[gitflow]\n\tinitialized = false\n")
    assert model(tmp_path, repo / "a.txt") == "gitflow-lite"
    (repo / ".gitflow").unlink()
    assert model(tmp_path, repo / "a.txt") == "gitflow-lite"


def test_model_falls_back_to_main_when_there_is_no_develop(tmp_path) -> None:
    """develop が無く main に .gitflow があれば、main の内容で判定する。"""
    repo = make_repo(tmp_path, branch="main")
    assert model(tmp_path, repo / "a.txt") == "gitflow-lite"


def test_model_is_none_when_gitflow_is_not_committed(tmp_path) -> None:
    """.gitflow がコミットされていなければ none (作業コピーにあっても)。"""
    repo = make_repo(tmp_path, gitflow=None)
    assert model(tmp_path, repo / "a.txt") == "none"
    (repo / ".gitflow").write_text(GITFLOW_LITE)
    assert model(tmp_path, repo / "a.txt") == "none"


def test_model_is_other_when_feature_strategy_is_merge(tmp_path) -> None:
    """feature の upstreamStrategy を merge にしてコミットすると other。"""
    merged = GITFLOW_LITE.replace("upstreamStrategy = squash", "upstreamStrategy = merge")
    repo = make_repo(tmp_path, gitflow=merged)
    assert model(tmp_path, repo / "a.txt") == "other"


def test_model_with_a_custom_develop_name_is_none(tmp_path) -> None:
    """ブランチ名のカスタム (develop が dev) は、develop も main も無いので none。固定した挙動: カスタム名は強制の対象外。"""
    custom = GITFLOW_LITE.replace("develop", "dev")
    repo = make_repo(tmp_path, branch="dev", gitflow=custom)
    assert model(tmp_path, repo / "a.txt") == "none"


def test_model_with_a_custom_name_on_the_main_branch_is_other(tmp_path) -> None:
    """main に .gitflow があり、中身が develop を dev に変えたものなら other (ブランチ名のカスタムは未対応)。"""
    custom = GITFLOW_LITE.replace("develop", "dev")
    repo = make_repo(tmp_path, branch="main", gitflow=custom)
    assert model(tmp_path, repo / "a.txt") == "other"


def test_model_of_an_outside_path_has_no_common_dir(tmp_path) -> None:
    """リポジトリの外は commonDir が無く、model を引かない (driver が noCommonDir を返す)。"""
    (tmp_path / "plain").mkdir()
    assert model(tmp_path, tmp_path / "plain") == {"noCommonDir": "no-repo"}


# --- 6. actionReady ----------------------------------------------------------

SAFE_CONFIG = [
    ("gitflow.initialized", "true"),
    ("gitflow.worktreePath", ".tmp/worktrees/{{ branchName }}"),
    ("gitflow.branch.feature.type", "topic"),
    ("gitflow.branch.feature.parent", "develop"),
    ("gitflow.branch.feature.startPoint", "develop"),
    ("gitflow.branch.feature.prefix", "feature/"),
    ("gitflow.branch.feature.upstreamStrategy", "squash"),
    ("gitflow.branch.develop.type", "base"),
    ("gitflow.branch.develop.parent", "main"),
]


def test_action_ready_depends_on_the_effective_config_not_on_the_model(tmp_path) -> None:
    """actionReady は .git/config の実効設定だけを見る。model が gitflow-lite でも、設定が無ければ false。"""
    repo = make_repo(tmp_path)
    step = {"fn": "ready", "path": str(repo)}
    assert probe(tmp_path, [step]) == [False]
    git(tmp_path, repo, "config", "gitflow.initialized", "true")
    assert probe(tmp_path, [step]) == [False]  # 足りない
    for k, v in SAFE_CONFIG:
        git(tmp_path, repo, "config", k, v)
    assert probe(tmp_path, [step]) == [True]
    # 危険な設定が混ざれば false に戻る
    git(tmp_path, repo, "config", "gitflow.feature.finish.push", "true")
    assert probe(tmp_path, [step]) == [False]


def test_action_ready_is_independent_of_the_model(tmp_path) -> None:
    """コミットされた .gitflow が無い (model=none) でも、実効設定が揃えば actionReady は true。"""
    repo = make_repo(tmp_path, gitflow=None)
    for k, v in SAFE_CONFIG:
        git(tmp_path, repo, "config", k, v)
    r = probe(tmp_path, [{"fn": "model", "path": str(repo)}, {"fn": "ready", "path": str(repo)}])
    assert r == ["none", True]


# --- 7. 安全なプローブ -------------------------------------------------------


def test_probing_does_not_run_the_fsmonitor_hook(tmp_path) -> None:
    """core.fsmonitor に実行するとマーカーを作るスクリプトを設定しても、probe はそれを起動しない。"""
    repo = make_repo(tmp_path)
    marker = tmp_path / "fsmonitor-ran"
    script = tmp_path / "fsm.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    git(tmp_path, repo, "config", "core.fsmonitor", str(script))
    r = probe(
        tmp_path,
        [
            {"fn": "owner", "path": str(repo / "a.txt")},
            {"fn": "model", "path": str(repo / "a.txt")},
            {"fn": "ready", "path": str(repo)},
        ],
    )
    assert r[0]["kind"] == "worktree" and r[1] == "gitflow-lite"
    assert not marker.exists()


def test_inherited_git_environment_is_ignored(tmp_path) -> None:
    """継承された GIT_DIR / GIT_WORK_TREE が別の場所を指していても無視され、パスの実際の所属で判定する。"""
    repo = make_repo(tmp_path)
    other = make_repo(tmp_path, "other", branch="topic", gitflow=None)
    plain = tmp_path / "plain"
    plain.mkdir()
    env = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    o = probe(tmp_path, [{"fn": "owner", "path": str(repo / "a.txt")}], env_extra=env)[0]
    assert o["top"] == str(repo.resolve())
    assert o["head"] == {"kind": "branch", "ref": "refs/heads/develop"}
    m = probe(tmp_path, [{"fn": "model", "path": str(repo / "a.txt")}], env_extra=env)[0]
    assert m == "gitflow-lite"
    # リポジトリの外は GIT_DIR があっても no-repo
    assert probe(tmp_path, [{"fn": "owner", "path": str(plain / "f")}], env_extra=env)[0] == {
        "kind": "no-repo"
    }


def test_a_failed_git_makes_the_owner_unknown(tmp_path) -> None:
    """git が時間切れ相当 (failed=true) を返したら unknown。許可にも no-repo にも倒れない。"""
    repo = make_repo(tmp_path)
    o = owner(tmp_path, repo / "a.txt", fake="failed")
    assert o["kind"] == "unknown"


def test_unexpected_git_output_makes_the_owner_unknown(tmp_path) -> None:
    """rev-parse の出力が想定外の行数なら unknown。"""
    repo = make_repo(tmp_path)
    o = owner(tmp_path, repo / "a.txt", fake="lines")
    assert o["kind"] == "unknown"
    assert "想定外" in o["why"]


def test_a_broken_dot_git_is_unknown_not_no_repo(tmp_path) -> None:
    """.git があるのに git が失敗する (空のファイルを .git として置く) と unknown。no-repo にも許可にも倒れない。"""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("")
    (broken / "f.txt").write_text("x")
    assert owner(tmp_path, broken / "f.txt")["kind"] == "unknown"


def test_a_corrupted_head_is_never_read_as_a_safe_branch(tmp_path) -> None:
    """HEAD を壊したリポジトリは、unknown か head=unreadable。develop などのブランチとして読まない。"""
    repo = make_repo(tmp_path)
    (repo / ".git" / "HEAD").write_text("garbage\n")
    o = owner(tmp_path, repo / "a.txt")
    assert o["kind"] == "unknown" or (o["kind"] == "worktree" and o["head"]["kind"] == "unreadable")


def test_model_is_unknown_when_the_git_dir_is_broken(tmp_path) -> None:
    """壊れた .git ディレクトリでは owner が unknown になり、commonDir が無いので model を引かない。"""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("")
    assert probe(tmp_path, [{"fn": "model", "path": str(broken)}])[0] == {"noCommonDir": "unknown"}


# --- 8. 判定ごとの作り直し ---------------------------------------------------


def test_a_probe_remembers_the_branch_but_a_new_probe_reads_the_new_state(tmp_path) -> None:
    """同じ probe の中ではブランチの変化を記憶し、新しい probe は新しい状態を読む。"""
    repo = make_repo(tmp_path)
    path = str(repo / "a.txt")
    r = probe(
        tmp_path,
        [
            {"fn": "owner", "path": path},
            {"fn": "git", "cwd": str(repo), "args": ["checkout", "-q", "-b", "x"]},
            {"fn": "owner", "path": path},
            {"fn": "newProbe"},
            {"fn": "owner", "path": path},
        ],
    )
    assert r[0]["head"] == {"kind": "branch", "ref": "refs/heads/develop"}
    assert r[1]["status"] == 0
    assert r[2]["head"] == {"kind": "branch", "ref": "refs/heads/develop"}  # 記憶
    assert r[4]["head"] == {"kind": "branch", "ref": "refs/heads/x"}  # 作り直した
