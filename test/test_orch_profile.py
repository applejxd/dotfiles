"""orch.py profile (orchlib.detect_profile) の試験。形ごとに使い捨ての git リポジトリを作って検査する。

形の一覧と期待は docs/spec/orchestration.md の「リポジトリのプロファイルの検出」。
a' は既存の test_bundle.py・test_wt_clean.py の fixture の形で、既存のスクリプトの挙動を固定する点。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[1]
        / "home"
        / "dot_agents"
        / "skills"
        / "feature-orchestration"
        / "scripts"
    ),
)

import orchlib
from orch_fixtures import ORCH, make_repo

DEFAULT_TPL = ".tmp/worktrees/{name}"

# 形 -> (終了コード, flow, integration, prefixes, worktree の template)
TABLE = {
    "a": (0, "git-flow-next", "develop", ["feature/"], DEFAULT_TPL),
    "a'": (0, "none", "develop", ["feature/"], DEFAULT_TPL),
    "b": (0, "git-flow-next", "dev", ["feature/"], DEFAULT_TPL),
    "c": (0, "git-flow-next", "production/develop", ["production/feature/"], DEFAULT_TPL),
    "d": (0, "none", "main", ["feature/"], DEFAULT_TPL),
    "d'": (0, "none", "main", [], DEFAULT_TPL),
    "f": (0, "git-flow-avh", "develop", ["feature/"], DEFAULT_TPL),
    "g": (0, "git-flow-next", "develop", ["feature/"], DEFAULT_TPL),
    "i": (0, "none", "develop", ["feature/"], DEFAULT_TPL),
    "j": (0, "none", "develop", ["feat/", "fix/"], ".wt/{name}"),
    "real": (0, "git-flow-next", "develop", ["feature/"], DEFAULT_TPL),
}


def _profile(repo, *args, **kw):
    r = repo.orch("profile", "--json", *args, **kw)
    return r, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else None)


@pytest.mark.parametrize("shape", list(TABLE))
def test_shape_detected(shape: str, tmp_path: Path) -> None:
    code, flow, integ, prefixes, template = TABLE[shape]
    repo = make_repo(shape, tmp_path / "repo")
    gcfg = None
    if shape == "i":
        gcfg = tmp_path / "global.gitconfig"
        gcfg.write_text(
            '[gitflow "branch"]\n\tdevelop = old-develop\n[gitflow "prefix"]\n\tfeature = old/\n',
            encoding="utf-8",
        )
    r, p = _profile(repo, global_cfg=gcfg)
    assert r.returncode == code, r.stderr + r.stdout
    assert p["v"] == 1
    assert p["flow"] == flow
    assert p["integration"]["branch"] == integ
    assert p["integration"]["ref"] == f"refs/heads/{integ}"
    assert p["topic"]["prefixes"] == prefixes
    assert p["worktrees"]["template"] == template
    assert p["worktrees"]["inside_repo"] is True
    assert p["ambiguous"] == []
    assert p["repo"]["main_worktree"] is not None
    if shape == "i":
        assert any("global" in w and "gitflow.branch.develop" in w for w in p["warnings"])
    else:
        assert p["warnings"] == []


def test_shape_details(tmp_path: Path) -> None:
    """形ごとの細かい値 (trunk・起票元・新しい枝の接頭辞・明示設定)。"""
    _, p = _profile(make_repo("a", tmp_path / "a"))
    assert (p["trunk"], p["topic"]["start_point"], p["topic"]["new_prefix"]) == (
        "main",
        "develop",
        "feature/",
    )
    _, p = _profile(make_repo("f", tmp_path / "f"))
    assert p["trunk"] == "main"
    _, p = _profile(make_repo("c", tmp_path / "c"))
    assert p["trunk"] == "production/main"
    _, p = _profile(make_repo("d'", tmp_path / "dp"))
    assert p["topic"]["new_prefix"] is None  # start は --prefix か設定が要る
    _, p = _profile(make_repo("j", tmp_path / "j"))
    assert p["verify"] == {"cmd": "make check"}
    assert p["topic"]["also_list"] == ["bugfix/"]
    assert p["sources"]["integration"] == "git config --local"


@pytest.mark.parametrize(("shape", "item"), [("e", "integration"), ("h", "flow")])
def test_ambiguous_exits_4(shape: str, item: str, tmp_path: Path) -> None:
    repo = make_repo(shape, tmp_path / "repo")
    r, p = _profile(repo)
    assert r.returncode == 4, r.stderr + r.stdout
    assert p["ambiguous"][0]["item"] == item
    if shape == "e":
        assert p["ambiguous"][0]["candidates"] == ["develop", "main"]
        assert p["integration"]["branch"] is None
    human = repo.orch("profile")
    assert human.returncode == 4
    assert "設定例" in human.stdout
    assert "推測しない" in human.stdout
    if shape == "e":
        assert "orchestration.integration" in human.stdout


@pytest.mark.parametrize("shape", ["k", "l", "not-git"])
def test_precondition_violations_exit_2(shape: str, tmp_path: Path) -> None:
    repo = make_repo(shape, tmp_path / "repo")
    r = repo.orch("profile", "--json")
    assert r.returncode == 2, r.stderr + r.stdout
    assert r.stderr.startswith("orch:")


def test_cli_override_beats_everything(tmp_path: Path) -> None:
    repo = make_repo("e", tmp_path / "repo")
    r, p = _profile(
        repo, "--integration", "main", "--prefix", "topic/", "--worktrees-dir", "/tmp/wts"
    )
    assert r.returncode == 0, r.stderr
    assert p["integration"]["branch"] == "main"
    assert p["topic"]["prefixes"] == ["topic/"]
    assert p["worktrees"]["template"] == "/tmp/wts/{name}"
    assert p["worktrees"]["inside_repo"] is False
    assert p["sources"]["integration"] == "cli"


def test_blocking_ambiguities_only_for_required_items(tmp_path: Path) -> None:
    """必須項目が曖昧なコマンドだけが止まる (owner は止まらない)。"""
    repo = make_repo("e", tmp_path / "repo")
    p = orchlib.detect_profile(repo.path)
    assert orchlib.blocking_ambiguities(p, "owner") == []
    for cmd in ("clean", "list", "start", "bundle"):
        assert [a["item"] for a in orchlib.blocking_ambiguities(p, cmd)] == ["integration"]


def test_shared_gitflow_orchestration_section(tmp_path: Path) -> None:
    """.gitflow の [orchestration] 節は next の parent より勝ち、local の設定はそれに勝つ。"""
    repo = make_repo("g", tmp_path / "repo")
    repo.git("config", "-f", ".gitflow", "orchestration.integration", "main")
    repo.git("config", "-f", ".gitflow", "orchestration.alsoList", "bugfix/")
    _, p = _profile(repo)
    assert p["integration"]["branch"] == "main"
    assert p["sources"]["integration"].startswith(".gitflow")
    assert p["topic"]["also_list"] == ["bugfix/"]
    repo.git("config", "orchestration.integration", "develop")
    _, p = _profile(repo)
    assert p["integration"]["branch"] == "develop"
    assert p["sources"]["integration"] == "git config --local"


def test_standalone_config_file_and_conflict(tmp_path: Path) -> None:
    repo = make_repo("e", tmp_path / "repo")
    cfg = repo.path / ".agents" / "config" / "orchestration.gitconfig"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "[orchestration]\n\tintegration = develop\n\toverlay = .agents/orchestration/overlay.md\n",
        encoding="utf-8",
    )
    r, p = _profile(repo)
    assert r.returncode == 0, r.stdout
    assert p["integration"]["branch"] == "develop"
    assert p["overlay"] == [".agents/orchestration/overlay.md"]
    # 同じ優先の 2 か所が食い違うと曖昧
    repo.git("config", "-f", ".gitflow", "orchestration.integration", "main")
    r, p = _profile(repo)
    assert r.returncode == 4
    assert p["ambiguous"][0]["item"] == "integration"


def test_multiple_feature_namespaces_are_ambiguous(tmp_path: Path) -> None:
    repo = make_repo("d", tmp_path / "repo")
    repo.branch("production/feature/y")
    r, p = _profile(repo)
    assert r.returncode == 4
    assert p["ambiguous"][0]["item"] == "topic.prefixes"
    assert p["ambiguous"][0]["candidates"] == ["feature/", "production/feature/"]


def test_linked_worktree_resolves_relative_template_from_main(tmp_path: Path) -> None:
    repo = make_repo("a", tmp_path / "repo")
    (repo.path / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
    wt = repo.path / ".tmp" / "worktrees" / "x"
    repo.git("worktree", "add", "-q", str(wt), "feature/x")
    r = subprocess.run(
        [sys.executable, str(ORCH), "profile", "--json"],
        cwd=wt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=repo.env,
        check=False,
    )
    p = json.loads(r.stdout)
    assert Path(p["repo"]["main_worktree"]) == repo.path
    assert Path(p["worktrees"]["base_abs"]) == repo.path / ".tmp" / "worktrees"
    assert p["integration"]["branch"] == "develop"
    assert p["worktrees"]["ignored"] is True  # 本体側の .gitignore で判定する


def test_human_output_is_one_screen(tmp_path: Path) -> None:
    r = make_repo("a", tmp_path / "repo").orch("profile")
    assert r.returncode == 0
    assert len(r.stdout.splitlines()) <= 20
    assert "develop" in r.stdout


@pytest.mark.skipif(shutil.which("git-flow") is None, reason="git flow (git-flow-next) が無い")
def test_orchestration_section_survives_git_flow_config_edit_shared(tmp_path: Path) -> None:
    """`git flow config edit … --shared` を経ても .gitflow の [orchestration] 節が残る (git-flow-next 2.1.0 で確認済み)。

    git flow の統合コマンド (finish・merge) は実行しない。config の読み書きだけを使う。
    """
    repo = make_repo("g", tmp_path / "repo")
    repo.git("config", "-f", ".gitflow", "orchestration.integration", "develop")
    repo.git("config", "-f", ".gitflow", "orchestration.topicPrefix", "feature/")
    repo.git("flow", "config", "edit", "base", "develop", "--auto-update=false", "--shared")
    assert repo.git("config", "-f", ".gitflow", "orchestration.integration").strip() == "develop"
    assert repo.git("config", "-f", ".gitflow", "orchestration.topicPrefix").strip() == "feature/"
    _, p = _profile(repo)
    assert p["integration"]["branch"] == "develop"


def test_this_repos_gitflow_is_shape_a(tmp_path: Path) -> None:
    """このリポジトリ自身の .gitflow (コピー) が (a) になる。local の git config は空 (未 sync)。"""
    repo = make_repo("real", tmp_path / "repo")
    _, p = _profile(repo)
    assert p["flow"] == "git-flow-next"
    assert p["integration"]["branch"] == "develop"
    assert p["trunk"] == "main"
    assert p["topic"]["prefixes"] == ["feature/"]
    assert p["worktrees"]["template"] == DEFAULT_TPL
    assert p["worktrees"]["inside_repo"] is True
