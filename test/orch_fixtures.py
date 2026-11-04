"""orch.py profile の試験用の使い捨て git リポジトリ (形ごと)。

`$TMPDIR` がこのリポジトリの中にある環境でも、親の .git を拾わないように、全 git 呼び出しに
GIT_CEILING_DIRECTORIES・GIT_CONFIG_GLOBAL / GIT_CONFIG_SYSTEM (os.devnull)・固定の author を付ける。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "home" / "dot_claude" / "skills" / "feature-orchestration" / "scripts" / "orch.py"


def clean_env(parent: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_EXEC_PATH"}
    env.update(
        {
            "GIT_CEILING_DIRECTORIES": str(parent),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "LC_ALL": "C",
        }
    )
    return env


@dataclass
class Repo:
    path: Path
    env: dict[str, str]

    def git(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
            check=False,
        )
        if check:
            assert r.returncode == 0, (args, r.stderr)
        return r.stdout

    def commit_on(self, branch: str, name: str = "f.txt", text: str = "x\n") -> None:
        self.git("checkout", "-q", branch)
        (self.path / name).write_text(text, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-q", "-m", f"{branch}: {name}")

    def branch(self, name: str, start: str = "HEAD") -> None:
        self.git("branch", name, start)

    def orch(self, *args: str, global_cfg: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if global_cfg is not None:
            env["GIT_CONFIG_GLOBAL"] = str(global_cfg)
        return subprocess.run(
            [sys.executable, str(ORCH), *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )


def _init(base: Path, initial: str = "main") -> Repo:
    base.mkdir(parents=True, exist_ok=True)
    repo = Repo(base, clean_env(base.parent))
    repo.git("init", "-q", "-b", initial)
    (base / "README").write_text("r\n", encoding="utf-8")
    repo.git("add", "README")
    repo.git("commit", "-q", "-m", "init")
    return repo


def _set_next(
    repo: Repo,
    integ: str,
    trunk: str,
    prefix: str = "feature/",
    worktree_path: str | None = ".tmp/worktrees/{{ branchName }}",
) -> None:
    """git-flow-next の型設定を local の git config に書く (git flow init 後と同じキー)。"""
    c = repo.git
    c("config", "gitflow.version", "1.0")
    c("config", f"gitflow.branch.{trunk}.type", "base")
    c("config", f"gitflow.branch.{integ}.type", "base")
    c("config", f"gitflow.branch.{integ}.parent", trunk)
    c("config", "gitflow.branch.feature.type", "topic")
    c("config", "gitflow.branch.feature.parent", integ)
    c("config", "gitflow.branch.feature.startPoint", integ)
    c("config", "gitflow.branch.feature.prefix", prefix)
    c(
        "config", f"gitflow.branch.{prefix}x.base", integ
    )  # 枝ごとの記録 (型設定ではない。無視される)
    if worktree_path:
        c("config", "gitflow.worktreePath", worktree_path)


def _with_branches(repo: Repo, *names: str) -> Repo:
    for n in names:
        repo.branch(n)
    return repo


def shape_a(base: Path) -> Repo:
    r = _with_branches(_init(base), "develop", "feature/x")
    _set_next(r, "develop", "main")
    return r


def shape_a_prime(base: Path) -> Repo:
    """既存の test_bundle・test_wt_clean の fixture の形 (develop だけ・設定なし)。"""
    r = _init(base, "develop")
    r.branch("feature/x", "develop")
    return r


def shape_b(base: Path) -> Repo:
    r = _with_branches(_init(base), "dev", "feature/x")
    _set_next(r, "dev", "main")
    return r


def shape_c(base: Path) -> Repo:
    r = _with_branches(_init(base, "production/main"), "production/develop", "production/feature/x")
    _set_next(r, "production/develop", "production/main", prefix="production/feature/")
    return r


def shape_d(base: Path) -> Repo:
    return _with_branches(_init(base), "feature/x")


def shape_d_prime(base: Path) -> Repo:
    return _with_branches(_init(base), "alice/topic-a", "bob/topic-b")


def shape_e(base: Path) -> Repo:
    return _with_branches(_init(base), "develop", "feature/x")


def shape_f(base: Path) -> Repo:
    r = _with_branches(_init(base), "develop", "feature/x")
    r.git("config", "gitflow.branch.master", "main")
    r.git("config", "gitflow.branch.develop", "develop")
    r.git("config", "gitflow.prefix.feature", "feature/")
    return r


GITFLOW_FILE = """\
[gitflow]
\tversion = 1.0
\tinitialized = true
\tworktreePath = .tmp/worktrees/{{ branchName }}
[gitflow "branch.develop"]
\ttype = base
\tparent = main
[gitflow "branch.feature"]
\ttype = topic
\tparent = develop
\tstartPoint = develop
\tprefix = feature/
[gitflow "branch.main"]
\ttype = base
"""


def shape_g(base: Path) -> Repo:
    """`.gitflow` だけがあり、local の git config は未 sync の clone。"""
    r = _with_branches(_init(base), "develop", "feature/x")
    (base / ".gitflow").write_text(GITFLOW_FILE, encoding="utf-8")
    return r


def shape_h(base: Path) -> Repo:
    r = shape_a(base)
    r.git("config", "gitflow.branch.master", "main")
    r.git("config", "gitflow.branch.develop", "develop")
    return r


def shape_i(base: Path) -> Repo:
    """develop だけ。global の旧キーは、試験側で GIT_CONFIG_GLOBAL に渡す。"""
    return shape_a_prime(base)


def shape_j(base: Path) -> Repo:
    """設定なしなら曖昧 (develop + main) だが、明示設定が検出に勝つ。"""
    r = shape_e(base)
    r.git("config", "orchestration.integration", "develop")
    r.git("config", "--add", "orchestration.topicPrefix", "feat/")
    r.git("config", "--add", "orchestration.topicPrefix", "fix/")
    r.git("config", "orchestration.alsoList", "bugfix/")
    r.git("config", "orchestration.worktreeDir", ".wt")
    r.git("config", "orchestration.verifyCmd", "make check")
    return r


def shape_k(base: Path) -> Repo:
    """bare リポジトリ。"""
    base.mkdir(parents=True, exist_ok=True)
    r = Repo(base, clean_env(base.parent))
    r.git("init", "-q", "--bare", "-b", "main")
    return r


def shape_l(base: Path) -> Repo:
    """コミットが 1 つも無い。"""
    base.mkdir(parents=True, exist_ok=True)
    r = Repo(base, clean_env(base.parent))
    r.git("init", "-q", "-b", "main")
    return r


def shape_real(base: Path) -> Repo:
    """このリポジトリ自身の `.gitflow` をコピーした形 (a)。"""
    r = _with_branches(_init(base), "develop", "feature/x")
    (base / ".gitflow").write_text(
        (ROOT / ".gitflow").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return r


def shape_not_git(base: Path) -> Repo:
    base.mkdir(parents=True, exist_ok=True)
    return Repo(base, clean_env(base.parent))


SHAPES: dict[str, Callable[[Path], Repo]] = {
    "a": shape_a,
    "a'": shape_a_prime,
    "b": shape_b,
    "c": shape_c,
    "d": shape_d,
    "d'": shape_d_prime,
    "e": shape_e,
    "f": shape_f,
    "g": shape_g,
    "h": shape_h,
    "i": shape_i,
    "j": shape_j,
    "k": shape_k,
    "l": shape_l,
    "real": shape_real,
    "not-git": shape_not_git,
}


def make_repo(shape: str, base: Path) -> Repo:
    """形 (a, a', b, c, d, d', e, f, g, h, i, j, k, l, real, not-git) の使い捨てリポジトリを base に作る。"""
    return SHAPES[shape](base)
