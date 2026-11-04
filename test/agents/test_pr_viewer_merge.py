"""PR ビューアの統合器（merge.ts・merge-git.ts・merge-cli.ts）の試験。

実 git の使い捨てリポジトリで、安全の条件 S1〜S10（CHG-0062 の段 A1）を固定する。反例（拒否・競合・中断）を先に置く。
名前・メールは架空（Example Dev <you@example.com>）。node の型除去で動かす（Windows は未検証）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_server import APP, _commit, _git, _init

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

CLI = APP / "merge-cli.ts"
MERGE_TS = APP / "merge.ts"
NULL_OID = "0" * 40


class World:
    """基準のリポジトリ（develop）と、CLI・node の呼び出し口。"""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.repo = _init(tmp / "repo")
        _git(self.repo, "config", "user.name", "Example Dev")
        _git(self.repo, "config", "user.email", "you@example.com")
        # 大きいコミットを繰り返すと、通常の git (試験の準備) が背景で gc --auto を起動し、締める場面の fsck と競合する
        # (loose object が消える)
        _git(self.repo, "config", "gc.auto", "0")
        _git(self.repo, "config", "maintenance.auto", "false")
        _commit(
            self.repo,
            {"README.md": "base\n", "other.txt": "other\n", ".gitignore": "*.ign\n"},
            "base",
        )

    def env(self) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def feature(
        self, name: str, files: dict[str, str], base: str = "develop", force: bool = False
    ) -> str:
        _git(self.repo, "checkout", "-q", "-b", name, base)
        for rel, body in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8", newline="\n")
        _git(self.repo, "add", "-f" if force else "-A", "--", *files)
        _git(self.repo, "commit", "-q", "-m", f"feat: {name}")
        oid = self.rev(name)
        _git(self.repo, "checkout", "-q", "develop")
        return oid

    def rev(self, ref: str = "develop") -> str:
        return _git(self.repo, "rev-parse", ref).strip()

    def cli(self, cmd: str, *args: str, stdin: str | None = None, repo: Path | None = None):
        proc = subprocess.run(
            [_node(), str(CLI), cmd, str(repo or self.repo), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
            cwd=self.tmp,
            check=False,
        )
        out = proc.stdout.strip()
        obj = json.loads(out.splitlines()[-1]) if out else None
        return proc.returncode, obj, proc

    def merge(self, source: str, message: str = "feat: merge\n\n本文\n", *extra: str, **kw):
        return self.cli(
            "merge", "--source", source, "--message-file", "-", *extra, stdin=message, **kw
        )

    def plan(self, source: str, *extra: str):
        return self.cli("plan", "--source", source, "--message-file", "-", *extra, stdin="plan\n")

    def api(self, body: str, arg: dict) -> dict:
        """merge.ts を直接 import する node スクリプト（deps の差し込みが要る試験用）。"""
        script = self.tmp / "api.mjs"
        script.write_text(
            f"""import {{ execFileSync }} from "node:child_process";
const M = await import({json.dumps(MERGE_TS.as_uri())});
const arg = JSON.parse(process.argv[2]);
const g = (...a) => execFileSync("git", a, {{ cwd: arg.repo, stdio: "ignore" }});
{body}
""",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [_node(), str(script), json.dumps(arg)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def status(self) -> str:
        return _git(self.repo, "status", "--porcelain", "--untracked-files=all")

    def git_dir(self) -> Path:
        return (self.repo / ".git").resolve()


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def _parents(w: World, ref: str = "develop") -> list[str]:
    return _git(w.repo, "rev-list", "--parents", "-n", "1", ref).split()[1:]


def _first_parent_count(w: World) -> int:
    return int(_git(w.repo, "rev-list", "--first-parent", "--count", "develop"))


def _no_leftovers(w: World) -> None:
    gd = w.git_dir()
    assert not (gd / "index.lock").exists()
    assert not (gd / "pr-viewer-merge.lock").exists()
    assert not (gd / "pr-viewer-merge.state").exists()


# ---------------------------------------------------------------- 1〜4 成功・積み重ね・衝突・stale


def test_merge_creates_merge_commit_with_squash_message(w):
    a = w.feature("feature/a", {"a.txt": "a\n"})
    old = w.rev()
    before = _first_parent_count(w)
    rc, out, _ = w.merge("feature/a", "feat: a を統合\n\n本文の 1 行\n")
    assert rc == 0 and out["ok"], out
    res = out["result"]
    assert res["targetOld"] == old and res["targetNew"] == res["commit"] == w.rev()
    assert _parents(w) == [old, a]  # 旧 develop と source の 2 親
    assert (
        _git(w.repo, "log", "-1", "--format=%B", "develop").strip()
        == "feat: a を統合\n\n本文の 1 行"
    )
    assert _first_parent_count(w) == before + 1
    assert (w.repo / "a.txt").read_text() == "a\n"  # 作業ツリーも更新される
    assert w.status() == ""
    _no_leftovers(w)


def test_stacked_features_merge_in_order(w):
    w.feature("feature/a", {"f.txt": "1\n"})
    w.feature("feature/b", {"f.txt": "2\n", "g.txt": "g\n"}, base="feature/a")
    assert w.merge("feature/a")[0] == 0
    rc, out, _ = w.plan("feature/b")
    assert rc == 0 and out["plan"]["conflicts"] == []
    assert w.merge("feature/b")[0] == 0
    assert (w.repo / "f.txt").read_text() == "2\n"
    assert (w.repo / "g.txt").exists()


def test_stacked_features_reverse_order_makes_lower_already_merged(w):
    w.feature("feature/a", {"f.txt": "1\n"})
    w.feature("feature/b", {"f.txt": "2\n"}, base="feature/a")
    assert w.merge("feature/b")[0] == 0
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "already_merged"
    assert w.rev() == before  # 空の merge commit を作らない


def test_conflict_is_refused_and_develop_does_not_move(w):
    w.feature("feature/a", {"README.md": "a側\n"})
    w.feature("feature/b", {"README.md": "b側\n"})
    assert w.merge("feature/a")[0] == 0
    before = w.rev()
    rc, out, _ = w.merge("feature/b")
    assert rc == 2 and out["code"] == "conflict" and "README.md" in out["conflicts"]
    assert w.rev() == before and w.status() == ""
    _no_leftovers(w)


@pytest.mark.parametrize("which", ["--expect-source", "--expect-target"])
def test_expect_mismatch_is_stale_and_changes_nothing(w, which):
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    rc, out, _ = w.merge("feature/a", "feat: a\n", which, NULL_OID)
    assert rc == 2 and out["code"] == "stale"
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_expect_match_succeeds(w):
    a = w.feature("feature/a", {"a.txt": "a\n"})
    rc, out, _ = w.merge("feature/a", "feat: a\n", "--expect-source", a, "--expect-target", w.rev())
    assert rc == 0 and out["ok"]


# ---------------------------------------------------------------- 5 dirty・untracked・ignored


def test_dirty_tracked_file_touched_by_merge(w):
    w.feature("feature/a", {"README.md": "a側\n"})
    (w.repo / "README.md").write_text("手元の変更\n")
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty"
    assert w.rev() == before and (w.repo / "README.md").read_text() == "手元の変更\n"


def test_untracked_with_same_name_as_new_file(w):
    w.feature("feature/a", {"new.txt": "a\n"})
    (w.repo / "new.txt").write_text("手元\n")
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty"
    assert (w.repo / "new.txt").read_text() == "手元\n"


def test_untracked_file_where_merge_needs_a_directory(w):
    w.feature("feature/a", {"dir/x.txt": "a\n"})
    (w.repo / "dir").write_text("手元のファイル\n")
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty"
    assert (w.repo / "dir").read_text() == "手元のファイル\n"


def test_ignored_file_with_same_name_is_not_overwritten(w):
    w.feature("feature/a", {"secret.ign": "a\n"}, force=True)
    (w.repo / "secret.ign").write_text("手元の秘密\n")
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "ignored"
    assert w.rev() == before and (w.repo / "secret.ign").read_text() == "手元の秘密\n"


def test_unrelated_dirty_untracked_and_staged_pass_and_are_kept(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    (w.repo / "other.txt").write_text("手元の変更\n")
    (w.repo / "u.txt").write_text("untracked\n")
    (w.repo / "s.txt").write_text("staged\n")
    _git(w.repo, "add", "s.txt")
    (w.repo / "keep.ign").write_text("ignored\n")
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert (w.repo / "a.txt").exists()
    assert (w.repo / "other.txt").read_text() == "手元の変更\n"
    assert (w.repo / "u.txt").read_text() == "untracked\n"
    assert _git(w.repo, "diff", "--cached", "--name-only").strip() == "s.txt"
    assert (w.repo / "keep.ign").read_text() == "ignored\n"


# ---------------------------------------------------------------- 6 head_mismatch・進行中・index.lock・競合


def test_head_mismatch_when_branch_changes_after_plan(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { afterPlan: () => g("checkout", "-q", "-b", "other") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "head_mismatch"
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_target_moved_after_plan_is_not_ff(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { afterPlan: () => g("commit", "--allow-empty", "-q", "-m", "x") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "not_ff"
    assert not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_source_moved_after_plan_is_stale(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { afterPlan: () => {
    const o = (...a) => execFileSync("git", a, { cwd: arg.repo, encoding: "utf8" }).trim();
    const c = o("commit-tree", o("rev-parse", "feature/a^{tree}"), "-p", "feature/a", "-m", "x");
    g("update-ref", "refs/heads/feature/a", c);
  } });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "stale"
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_target_moved_after_the_state_is_written_never_becomes_a_normal_merge(w):
    """ff-only の CAS。target が先に進んだら、通常の merge で 2 つを混ぜず、断る。作業ツリーが無傷なので状態も消える。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => g("commit", "--allow-empty", "-q", "-m", "someone else") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "not_ff"
    assert not (w.repo / "a.txt").exists()
    assert _git(w.repo, "log", "-1", "--format=%s", "develop").strip() == "someone else"
    assert len(_parents(w)) == 1  # 統合のコミットは作られていない
    _no_leftovers(w)


def test_lost_lock_before_ff_is_busy_and_nothing_is_written(w):
    """古いロックを別の実行者が奪った (ff の前に自分のロックが無い) ときは、進めない。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    out = w.api(
        """import { unlinkSync } from "node:fs";
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => unlinkSync(arg.repo + "/.git/pr-viewer-merge.lock") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "busy", out
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    assert not (w.git_dir() / "pr-viewer-merge.state").exists()


def test_head_switched_before_ff_does_not_move_another_branch(w):
    """merge --ff-only は実行時の現在の枝を進める。ff の直前に HEAD が別の枝になっていたら、進めない。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => g("checkout", "-q", "-b", "other") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "head_mismatch", out
    assert w.rev() == before and w.rev("other") == before  # どちらの枝も進めていない
    assert not (w.repo / "a.txt").exists()
    assert not (w.git_dir() / "pr-viewer-merge.state").exists()


def test_state_is_kept_when_ff_fails_and_the_worktree_is_not_restored(w):
    """ff が、統合が作るパスと同名の untracked（計画の後に現れた）で断られたら、手で確認できるよう状態を残す。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """import { writeFileSync } from "node:fs";
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => writeFileSync(arg.repo + "/a.txt", "手元のファイル\\n") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "failed"
    assert (w.repo / "a.txt").read_text(encoding="utf-8") == "手元のファイル\n"  # 上書きされない
    gd = w.git_dir()
    assert (gd / "pr-viewer-merge.state").exists()  # 状態は残る
    assert not (gd / "pr-viewer-merge.lock").exists() and not (gd / "index.lock").exists()


@pytest.mark.parametrize(
    "name",
    [
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_LOG",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    ],
)
def test_operation_in_progress_is_refused_with_its_own_code(w, name):
    w.feature("feature/a", {"a.txt": "a\n"})
    target = w.git_dir() / name
    if name.startswith("rebase") or name == "sequencer":
        target.mkdir()
    else:
        target.write_text(w.rev() + "\n")
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "operation_in_progress", out
    assert out["details"] == {"op": name}
    assert not (w.repo / "a.txt").exists()


def test_existing_index_lock_is_index_locked(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    (w.git_dir() / "index.lock").write_text("")
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "index_locked", out
    assert "index.lock" in out["reason"] and "実行されていません" in out["reason"]
    assert (w.git_dir() / "index.lock").exists()  # 他人のロックは消さない


def test_dirty_refusal_carries_the_paths_capped_at_20(w):
    files = {f"d/f{i:02d}.txt": "x\n" for i in range(25)}
    w.feature("feature/a", files)
    (w.repo / "d").mkdir()
    for rel in files:
        (w.repo / rel).write_text("手元\n", encoding="utf-8")  # 統合が作るパスと同名の untracked
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty", out
    assert out["details"]["pathCount"] == 25
    assert len(out["details"]["paths"]) == 20
    assert set(out["details"]["paths"]) <= set(files)


def test_head_mismatch_reason_names_the_current_branch(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { afterPlan: () => g("checkout", "-q", "-b", "other") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["code"] == "head_mismatch" and "other" in out["reason"], out


# ---------------------------------------------------------------- 7 target が checkout されていない


def test_merge_by_update_ref_when_target_not_checked_out(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "checkout", "-q", "-b", "scratch")
    scratch = w.rev("scratch")
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert w.rev("develop") == out["result"]["commit"]
    assert len(_parents(w)) == 2
    assert w.rev("scratch") == scratch and w.status() == ""  # 別の枝の作業ツリーは触らない
    _no_leftovers(w)


def test_merge_into_target_checked_out_in_linked_worktree(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "checkout", "-q", "-b", "scratch")
    linked = w.tmp / "linked"
    _git(w.repo, "worktree", "add", "-q", str(linked), "develop")
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert (linked / "a.txt").read_text() == "a\n" and not (w.repo / "a.txt").exists()


# ---------------------------------------------------------------- 8 policy・入力の検査


@pytest.mark.parametrize("source", ["main", "release/x", "develop", "bugfix"])
def test_source_outside_policy(w, source):
    rc, out, _ = w.plan(source)
    assert rc == 2 and out["code"] == "policy_source"


def test_target_outside_policy(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    rc, out, _ = w.plan("feature/a", "--target", "main")
    assert rc == 2 and out["code"] == "policy_target"


@pytest.mark.parametrize(
    "source",
    [
        "feature/../x",
        "feature/a b",
        "-x",
        "--feature/x",
        "refs/tags/feature/v1",
        "feature/a.lock",
        "feature//a",
        "feature/a/",
        "feature/a\u3042",
        "feature/@{u}",
    ],
)
def test_bad_ref_names_are_bad_input(w, source):
    rc, out, _ = w.plan(source)
    assert rc == 2 and out["code"] == "bad_input"
    assert "feature" not in out["reason"] and str(w.tmp) not in out["reason"]


def test_full_ref_name_is_accepted_and_bugfix_prefix_too(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    w.feature("bugfix/b", {"b.txt": "b\n"})
    assert w.plan("refs/heads/feature/a")[0] == 0
    assert w.plan("bugfix/b")[0] == 0


def test_missing_source_and_target(w):
    rc, out, _ = w.plan("feature/none")
    assert rc == 2 and out["code"] == "no_source"
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "checkout", "-q", "-b", "scratch")
    _git(w.repo, "branch", "-q", "-D", "develop")
    rc, out, _ = w.plan("feature/a")
    assert rc == 2 and out["code"] == "no_target"


@pytest.mark.parametrize(
    "message",
    ["", "\n\n本文だけ\n", "   \nbody", "x" * 5000, "a\x01b", "a\rb", "a\x7fb", "a\x1bb"],
)
def test_bad_messages_are_refused(w, message):
    w.feature("feature/a", {"a.txt": "a\n"})
    before = w.rev()
    rc, out, _ = w.merge("feature/a", message)
    assert rc == 2 and out["code"] == "bad_input"
    assert w.rev() == before


def test_message_with_tab_and_newlines_is_accepted(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    msg = "feat: a\n\n\t- 項目\n" + "あ" * 3000
    rc, out, _ = w.merge("feature/a", msg)
    assert rc == 0, out
    assert _git(w.repo, "log", "-1", "--format=%B", "develop").rstrip("\n") == msg.rstrip("\n")


def test_bad_cleanup_and_oid(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    assert w.merge("feature/a", "m\n", "--cleanup", "all")[1]["code"] == "bad_input"
    assert w.merge("feature/a", "m\n", "--expect-source", "HEAD")[1]["code"] == "bad_input"
    assert w.merge("feature/a", "m\n", "--expect-target", "-p")[1]["code"] == "bad_input"


# ---------------------------------------------------------------- 9 外部コード・hook


@pytest.mark.parametrize(
    "key,value",
    [
        ("merge.x.driver", "touch {mark} %A"),
        ("filter.x.clean", "touch {mark}"),
        ("filter.x.smudge", "touch {mark}"),
        ("filter.x.process", "touch {mark}"),
        ("core.hooksPath", "{tmp}/hooks"),
        ("include.path", "{tmp}/extra.cfg"),
        ("includeIf.gitdir:/.path", "{tmp}/extra.cfg"),
        ("core.fsmonitor", "touch {mark}"),
    ],
)
def test_external_code_config_is_refused_before_anything_runs(w, key, value):
    w.feature("feature/a", {"a.txt": "a\n"})
    (w.repo / ".gitattributes").write_text(
        "*.txt merge=x filter=x\n"
    )  # 未コミット。設定が無ければ動かない
    mark = w.tmp / "MARK"
    (w.tmp / "extra.cfg").write_text("[core]\n\tabbrev = 9\n")
    _git(w.repo, "config", key, value.format(mark=mark, tmp=w.tmp))
    before = w.rev()
    for rc, out, _ in (w.plan("feature/a"), w.merge("feature/a")):
        assert rc == 2 and out["code"] == "external_code"
    assert not mark.exists()
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    assert not (w.git_dir() / "pr-viewer-merge.lock").exists()
    assert not (w.git_dir() / "pr-viewer-merge.state").exists()


def test_recover_also_refuses_external_code_config(w):
    _git(w.repo, "config", "merge.x.driver", "touch MARK")
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "external_code"


def test_harmless_config_values_are_allowed(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "core.fsmonitor", "false")
    _git(w.repo, "config", "core.hooksPath", "/dev/null")
    assert w.merge("feature/a")[0] == 0


def test_repo_hooks_do_not_run_during_merge(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    hooks = w.git_dir() / "hooks"
    names = ["pre-commit", "post-merge", "post-commit", "reference-transaction", "post-checkout"]
    for n in names:
        h = hooks / n
        h.write_text(f"#!/bin/sh\ntouch '{w.tmp}/MARK-{n}'\n")
        h.chmod(0o755)
    rc, out, _ = w.merge("feature/a", "feat: a\n", "--cleanup", "branch")
    assert rc == 0 and out["ok"], out
    assert [p.name for p in w.tmp.glob("MARK-*")] == []
    # 対照: 素の git なら同じ hook が動く（hook が有効な配置だったことの確認）
    _git(w.repo, "commit", "--allow-empty", "-q", "-m", "control")
    assert (w.tmp / "MARK-post-commit").exists()


# ---------------------------------------------------------------- 10 identity


def test_missing_identity_is_refused_without_writing(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "--unset", "user.name")
    _git(w.repo, "config", "--unset", "user.email")
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "no_identity"
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_identity_comes_from_repository_config(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "user.name", "Alice Example")
    _git(w.repo, "config", "user.email", "alice@example.com")
    assert w.merge("feature/a")[0] == 0
    fmt = _git(w.repo, "log", "-1", "--format=%an|%ae|%cn|%ce", "develop").strip()
    assert fmt == "Alice Example|alice@example.com|Alice Example|alice@example.com"


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("Alice <x>", "a@example.com"),
        ("", "a@example.com"),
        ("Alice", ""),
        ("A>B", "a@example.com"),
    ],
)
def test_unsafe_identity_values_are_refused(w, name, email):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "user.name", name)
    _git(w.repo, "config", "user.email", email)
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "no_identity", out
    assert w.rev() == before and not (w.repo / "a.txt").exists()
    _no_leftovers(w)


def test_staged_rename_of_a_touched_file_is_dirty(w):
    """git status の改名は新旧の 2 パスを持つ。旧い側 (統合が触るファイル) も重なりとして見る。"""
    w.feature("feature/a", {"other.txt": "統合で変わる\n"})
    _git(w.repo, "mv", "other.txt", "renamed.txt")
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "dirty", out
    assert w.rev() == before
    _no_leftovers(w)


def test_ref_name_with_double_dot_is_bad_input(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    rc, out, _ = w.merge("feature/a..b")
    assert rc == 2 and out["code"] == "bad_input", out


# ---------------------------------------------------------------- 11 cleanup


def test_cleanup_none_keeps_branch(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["result"]["cleanup"] == {"requested": "none", "done": []}
    assert "feature/a" in _git(w.repo, "branch", "--list", "feature/a")


def test_cleanup_branch_deletes_branch(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "config", "branch.feature/a.remote", ".")  # 枝の設定 (upstream など) も片付く
    _git(w.repo, "config", "branch.feature/a.merge", "refs/heads/develop")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch")
    assert rc == 0 and out["result"]["cleanup"]["done"] == ["branch"], out
    assert _git(w.repo, "branch", "--list", "feature/a").strip() == ""
    assert (
        _git(w.repo, "config", "--get-regexp", "^branch\\.feature/a\\.", check=False).strip() == ""
    )
    assert out["result"]["warnings"] == []


def test_cleanup_branch_when_target_not_checked_out(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "checkout", "-q", "-b", "scratch")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch")
    assert rc == 0 and "branch" in out["result"]["cleanup"]["done"], out
    assert _git(w.repo, "branch", "--list", "feature/a").strip() == ""


def test_cleanup_branch_and_worktree_clean(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["result"]["cleanup"]["done"] == ["worktree", "branch"], out
    assert not wt.exists()
    assert _git(w.repo, "branch", "--list", "feature/a").strip() == ""


def test_cleanup_with_dirty_worktree_keeps_it_and_warns(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    (wt / "wip.txt").write_text("作業中\n")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out  # 統合は成功のまま
    assert wt.exists() and (wt / "wip.txt").read_text() == "作業中\n"
    assert out["result"]["warnings"] and "worktree" not in out["result"]["cleanup"]["done"]
    assert str(w.tmp) not in json.dumps(out)
    assert "feature/a" in _git(w.repo, "branch", "--list", "feature/a")  # checkout 中の枝は消えない
    assert len(_parents(w)) == 2


# ---------------------------------------------------------------- 12 排他


def _start(w: World, source: str, message: str) -> subprocess.Popen:
    mf = w.tmp / f"msg-{source.replace('/', '_')}.txt"
    mf.write_text(message, encoding="utf-8")
    return subprocess.Popen(
        [_node(), str(CLI), "merge", str(w.repo), "--source", source, "--message-file", str(mf)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=w.env(),
        cwd=w.tmp,
    )


def test_two_concurrent_merges_leave_a_consistent_repository(w):
    for i in range(10):
        w.feature(f"feature/a{i}", {f"a{i}.txt": "a\n"})
        w.feature(f"feature/b{i}", {f"b{i}.txt": "b\n"})
        (w.repo / "u.txt").write_text(f"無関係 {i}\n")  # 無関係な untracked は残る
        procs = [_start(w, f"feature/a{i}", "feat: a\n"), _start(w, f"feature/b{i}", "feat: b\n")]
        results = []
        for p in procs:
            stdout, _ = p.communicate(timeout=60)
            results.append((p.returncode, json.loads(stdout.strip().splitlines()[-1])))
        oks = [r for rc, r in results if rc == 0]
        assert len(oks) >= 1, results
        for rc, r in results:
            assert rc == 0 or (rc == 2 and r["code"] == "busy"), results
        for name in ("a", "b"):
            merged = (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", f"feature/{name}{i}", "develop"],
                    cwd=w.repo,
                    check=False,
                ).returncode
                == 0
            )
            assert merged == (w.repo / f"{name}{i}.txt").exists()
        assert (w.repo / "u.txt").read_text() == f"無関係 {i}\n"
        assert w.status() == "?? u.txt\n"
        _no_leftovers(w)
        _git(w.repo, "fsck", "--no-dangling")
        for name in ("a", "b"):  # busy だった側も、後から統合できる
            if not (w.repo / f"{name}{i}.txt").exists():
                assert w.merge(f"feature/{name}{i}")[0] == 0


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_stale_lock_with_dead_pid_is_not_taken_over_automatically(w):
    """古いロックを自動で奪うと、確認と削除の間で競合して両方が保護区間に入る。利用者の recover だけが解除する。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    lock = w.git_dir() / "pr-viewer-merge.lock"
    body = json.dumps({"pid": _dead_pid(), "startedAt": "2020-01-01T00:00:00Z", "id": "old"})
    lock.write_text(body)
    before = w.rev()
    rc, out, _ = w.merge("feature/a")
    assert rc == 2 and out["code"] == "recover_needed", out
    assert lock.read_text() == body and w.rev() == before  # 何も変えない
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "clean" and not lock.exists(), out
    assert w.merge("feature/a")[0] == 0  # 解除の後は統合できる


def test_lock_held_by_live_pid_is_busy_and_kept(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    holder = subprocess.Popen(["sleep", "30"])
    lock = w.git_dir() / "pr-viewer-merge.lock"
    body = json.dumps({"pid": holder.pid, "startedAt": "2020-01-01T00:00:00Z", "id": "live"})
    lock.write_text(body)
    try:
        before = w.rev()
        rc, out, _ = w.merge("feature/a")
        assert rc == 2 and out["code"] == "busy"
        assert lock.read_text() == body and w.rev() == before
        rc, out, _ = w.cli("recover")
        assert rc == 2 and out["code"] == "busy"
    finally:
        holder.kill()
        holder.wait()


# ---------------------------------------------------------------- 13 中断と復旧


def _big_feature(w: World, name: str, count: int = 3000) -> str:
    return w.feature(name, {f"big/{name[-1]}-{i:04}.txt": f"{name}-{i}\n" for i in range(count)})


def _commit_for(w: World, source: str) -> tuple[str, str]:
    """統合の途中状態を手で作るための、merge commit（ref は進めない）。戻り値は (commit, 旧 develop)。"""
    old = w.rev()
    tree = _git(w.repo, "merge-tree", "--write-tree", "develop", source).strip()
    commit = _git(
        w.repo, "commit-tree", tree, "-p", old, "-p", w.rev(source), "-m", "feat: merge"
    ).strip()
    return commit, old


def _write_state(w: World, **kw) -> Path:
    st = {
        "id": "x",
        "source": "feature/a",
        "target": "develop",
        "targetOld": "",
        "commit": "",
        "touched": [],
        "added": [],
        "newDirs": [],
        "phase": "ff",
    }
    st.update(kw)
    p = w.git_dir() / "pr-viewer-merge.state"
    p.write_text(json.dumps(st))
    return p


def test_recover_without_state_is_clean(w):
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out == {"ok": True, "state": "clean"}


def test_recover_reports_and_changes_nothing_after_a_partial_merge(w):
    """途中で止まった ff が書いたものの片付けは、利用者が手で行う。recover は何も消さず、診断だけを返す。"""
    w.feature("feature/a", {"README.md": "a側\n", "newdir/sub/n.txt": "n\n", "other2.txt": "o\n"})
    commit, old = _commit_for(w, "feature/a")
    # 途中で止まった ff-only を再現: 触るファイルが新しい中身になり、index.lock が残る
    (w.repo / "README.md").write_text("a側\n")
    (w.repo / "newdir/sub").mkdir(parents=True)
    (w.repo / "newdir/sub/n.txt").write_text("n\n")
    (w.repo / "other2.txt").write_text("o\n")
    (w.git_dir() / "index.lock").write_text("")
    # 無関係な未コミットの変更
    (w.repo / "other.txt").write_text("手元の変更\n")
    (w.repo / "u.txt").write_text("untracked\n")
    st = _write_state(
        w,
        targetOld=old,
        commit=commit,
        touched=["README.md", "newdir/sub/n.txt", "other2.txt"],
        added=["newdir/sub/n.txt", "other2.txt"],
        newDirs=["newdir", "newdir/sub"],
    )
    snapshot = w.status()
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed" and out["reason"] == "手で確認が要ります。", out
    d = out["details"]
    assert d["cause"] == "worktree_not_clean" and d["indexLock"] is True and d["operation"] is False
    assert (
        sorted(d["paths"]) == ["README.md", "newdir/sub/n.txt", "other2.txt"]
        and d["pathCount"] == 3
    )
    assert str(w.tmp) not in json.dumps(out)
    # 何も変えない: ref・作業ツリー・index.lock・状態ファイル
    assert w.rev() == old and w.status() == snapshot
    assert (w.repo / "README.md").read_text() == "a側\n" and (w.repo / "newdir/sub/n.txt").exists()
    assert (w.git_dir() / "index.lock").exists() and st.exists()
    # 利用者が診断を見て手で片付ける (ここでは、無関係な変更は残して、統合が書いたパスだけを戻す)
    (w.git_dir() / "index.lock").unlink()
    _git(w.repo, "checkout", "--", "README.md")
    (w.repo / "newdir/sub/n.txt").unlink()
    (w.repo / "newdir/sub").rmdir()
    (w.repo / "newdir").rmdir()
    (w.repo / "other2.txt").unlink()
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "cleared" and not st.exists(), out
    assert (w.repo / "other.txt").read_text() == "手元の変更\n"  # 無関係な変更は残る
    assert w.status() == " M other.txt\n?? u.txt\n"
    _no_leftovers(w)
    _git(w.repo, "fsck", "--no-dangling")
    # 復旧の後は、通常どおり統合できる（無関係な変更は残ったまま）
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    assert (w.repo / "other.txt").read_text() == "手元の変更\n"


def test_recover_does_not_touch_paths_outside_state(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    commit, old = _commit_for(w, "feature/a")
    (w.repo / "other.txt").write_text("手元\n")
    (w.repo / "stray.txt").write_text("状態に無い\n")
    _write_state(w, targetOld=old, commit=commit, touched=["a.txt"], added=["a.txt"])
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "cleared"  # 状態のパスに差が無いので、状態だけを解除する
    assert (w.repo / "other.txt").read_text() == "手元\n"
    assert (w.repo / "stray.txt").read_text() == "状態に無い\n"
    assert not (w.git_dir() / "pr-viewer-merge.state").exists()


def test_recover_completed_when_ref_already_advanced(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    commit, old = _commit_for(w, "feature/a")
    _git(w.repo, "merge", "--ff-only", "-q", commit)
    st = _write_state(w, targetOld=old, commit=commit, touched=["a.txt"], added=["a.txt"])
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "completed" and not st.exists()
    assert (w.repo / "a.txt").exists()  # 統合済みの作業ツリーは触らない


def test_recover_fails_and_touches_nothing_when_someone_else_moved_target(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    commit, old = _commit_for(w, "feature/a")
    _commit(w.repo, {"x.txt": "別の誰か\n"}, "someone else")  # develop が別のコミットへ進んだ
    (w.repo / "a.txt").write_text("途中の中身\n")
    (w.git_dir() / "index.lock").write_text("")
    st = _write_state(w, targetOld=old, commit=commit, touched=["a.txt"], added=["a.txt"])
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed"
    assert st.exists()  # 状態は残す
    assert (w.repo / "a.txt").read_text() == "途中の中身\n"
    assert (w.git_dir() / "index.lock").exists()


def test_recover_refuses_unsafe_paths_in_state(w):
    commit, old = NULL_OID, w.rev()
    victim = w.tmp / "victim.txt"
    victim.write_text("守る\n")
    _write_state(
        w, targetOld=old, commit=commit, touched=["../victim.txt"], added=["../victim.txt"]
    )
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed"
    assert victim.read_text() == "守る\n"


def _kill_during_merge(w: World, source: str, delay: float) -> None:
    mf = w.tmp / "msg-big.txt"
    mf.write_text("feat: big\n", encoding="utf-8")
    p = subprocess.Popen(
        [_node(), str(CLI), "merge", str(w.repo), "--source", source, "--message-file", str(mf)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=w.env(),
        cwd=w.tmp,
        start_new_session=True,  # git の子も一緒に止めるため
    )
    # ff の直前に状態ファイルを書く。それを合図にして、ff の最中を狙う (時間だけで狙うと、ff の前で止めてしまう)
    state = w.git_dir() / "pr-viewer-merge.state"
    deadline = time.monotonic() + 10
    while not state.exists() and p.poll() is None and time.monotonic() < deadline:
        time.sleep(0.001)
    time.sleep(delay)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def test_kill_9_during_merge_then_manual_recovery(w):
    """統合の最中に kill -9（ff の直前の状態ファイルを合図に 0〜120ms）。

    通常の統合は断られ、recover は何も変えずに診断を返す。利用者が手で片付けた後にもう一度 recover すると解除され、再統合できる。
    ff が終わっていたときは、recover が completed として解除する。
    """
    seen: set[str] = set()
    for attempt, delay in enumerate([0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12]):
        name = f"feature/big{attempt}"
        _big_feature(w, name)
        (w.repo / "other.txt").write_text(f"手元の変更 {attempt}\n")
        (w.repo / "u.txt").write_text("untracked\n")
        before = w.rev()
        _kill_during_merge(w, name, delay)
        rc, out, _ = w.merge(name)  # 持ち主の pid が死んだロックを、自動では奪わない
        assert rc == 2 and out["code"] == "recover_needed", out
        snapshot = w.status()
        rc, out, _ = w.cli("recover")
        if rc == 0:
            assert out["state"] in ("completed", "cleared"), out
            seen.add(out["state"])
        else:
            assert out["code"] == "failed" and out["details"]["cause"] == "worktree_not_clean", out
            seen.add("manual")
            assert w.rev() == before and w.status() == snapshot  # recover は何も変えない
            # 利用者が診断を見て手で片付ける: index.lock と、統合が書いたパスだけ
            (w.git_dir() / "index.lock").unlink(missing_ok=True)
            # 統合が書いたパスは、index に載っていることもある（index の書き換えの後・ref の更新の前で止まったとき）。残らず戻す
            _git(w.repo, "reset", "-q", "HEAD", "--", f"big/{attempt}-*.txt")
            for p in (w.repo / "big").glob(f"{attempt}-*.txt"):
                p.unlink()
            rc, out, _ = w.cli("recover")
            assert rc == 0 and out["state"] == "cleared", out
        _no_leftovers(w)
        assert (w.repo / "other.txt").read_text() == f"手元の変更 {attempt}\n"  # 無関係な変更は残る
        assert (w.repo / "u.txt").read_text() == "untracked\n"
        _git(w.repo, "fsck", "--no-dangling")
        assert w.status() == " M other.txt\n?? u.txt\n", w.status()
        merged = w.rev() != before
        if merged:
            assert len(_parents(w)) == 2 and (w.repo / f"big/{attempt}-0000.txt").exists()
        else:
            assert not (w.repo / f"big/{attempt}-0000.txt").exists()
            rc, out, _ = w.merge(name)  # 解除の後の統合が成功する
            assert rc == 0 and out["ok"], out
        _git(w.repo, "checkout", "--", "other.txt")
        (w.repo / "u.txt").unlink()
        if "manual" in seen and attempt >= 3:
            break
    if "manual" not in seen:
        pytest.skip(
            f"kill の窓に当たらなかった（結果: {sorted(seen)}）。手で作る復旧の試験が代わりに固定する"
        )


# ---------------------------------------------------------------- 14 CLI


def test_cli_plan_json_and_exit_codes(w):
    a = w.feature("feature/a", {"a.txt": "a\n", "d/b.txt": "b\n"})
    rc, out, proc = w.plan("feature/a")
    assert rc == 0 and out["ok"] and proc.stdout.count("\n") == 1  # JSON は 1 行
    plan = out["plan"]
    assert plan["source"] == {"ref": "refs/heads/feature/a", "oid": a}
    assert plan["target"] == {"ref": "refs/heads/develop", "oid": w.rev()}
    assert plan["alreadyMerged"] is False and plan["conflicts"] == []
    assert sorted(plan["touched"]) == ["a.txt", "d/b.txt"]
    assert sorted((f["status"], f["path"]) for f in plan["files"]) == [
        ("A", "a.txt"),
        ("A", "d/b.txt"),
    ]
    assert re.fullmatch(r"[0-9a-f]{40}", plan["resultTree"]) and plan["mergeBase"] == w.rev()
    rc, out, _ = w.plan("feature/none")
    assert rc == 2 and out["ok"] is False


def test_cli_message_only_from_file_or_stdin(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    rc, out, _ = w.cli("merge", "--source", "feature/a", "--message", "x")
    assert rc == 2 and out["code"] == "bad_input"
    rc, out, _ = w.cli("merge", "--source", "feature/a")  # メッセージ無し
    assert rc == 2 and out["code"] == "bad_input"
    mf = w.tmp / "msg.txt"
    mf.write_text("feat: ファイルから\n", encoding="utf-8")
    rc, out, _ = w.cli("merge", "--source", "feature/a", "--message-file", str(mf))
    assert rc == 0 and out["ok"]
    assert _git(w.repo, "log", "-1", "--format=%s", "develop").strip() == "feat: ファイルから"
    assert "--message-file" in (APP / "merge-cli.ts").read_text(encoding="utf-8")
    assert '"--message"' not in (APP / "merge-cli.ts").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    [[], ["bogus", "."], ["plan"], ["plan", "-x"], ["recover", ".", "--source", "feature/a"]],
)
def test_cli_bad_arguments_exit_2(w, argv):
    proc = subprocess.run(
        [_node(), str(CLI), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=w.env(),
        cwd=w.tmp,
        check=False,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout.strip())["code"] == "bad_input"


def test_cli_unexpected_exception_exits_1_without_leaking(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    (w.git_dir() / "pr-viewer-merge.state").mkdir()  # 状態ファイルを書けず、例外になる
    before = w.rev()
    rc, out, proc = w.merge("feature/a")
    # 想定外の例外は、絶対パスを含まない固定の拒否になる (S8)。壊れた状態ファイルがある間は新しい統合を始めない
    assert rc == 2 and out["ok"] is False and out["code"] == "recover_needed"
    assert w.rev() == before
    assert str(w.tmp) not in proc.stdout + proc.stderr
    assert not (w.git_dir() / "pr-viewer-merge.lock").exists()  # 拒否でもロックは解放される


def test_api_exceptions_never_escape_with_paths(w):
    """公開の関数は例外を投げず、固定の拒否を返す (直接 import して使う A2 のため)。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const bad = { repo: arg.repo, source: "feature/a", message: "m\\n", expect: { sourceOid: 5 } };
const r = [await M.planMerge(bad), await M.executeMerge(bad), await M.recoverMerge(5)];
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert all(r["ok"] is False for r in out) and str(w.tmp) not in json.dumps(out)


def test_exceptions_inside_the_merge_become_a_fixed_refusal_and_release_the_lock(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { afterPlan: () => { throw new Error(arg.repo + "/秘密のパス"); } });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False and out["code"] == "failed"
    assert str(w.tmp) not in json.dumps(out) and "秘密" not in json.dumps(out)
    _no_leftovers(w)


def test_cleanup_keeps_a_branch_that_moved_after_the_merge(w):
    """承認して統合した先頭と違う枝 (統合の後に進んだ) は、統合していないので消さない。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    out = w.api(
        """const o = (...a) => execFileSync("git", a, { cwd: arg.repo, encoding: "utf8" }).trim();
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n", cleanup: "branch" }, undefined,
  { beforeCleanup: () => {
    const c = o("commit-tree", o("rev-parse", "feature/a^{tree}"), "-p", "feature/a", "-m", "統合後の追加");
    g("update-ref", "refs/heads/feature/a", c);
    g("update-ref", "refs/heads/up", c);
    g("config", "branch.feature/a.remote", ".");
    g("config", "branch.feature/a.merge", "refs/heads/up");
  } });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is True and out["result"]["cleanup"]["done"] == [], out
    assert out["result"]["warnings"]
    assert "feature/a" in _git(w.repo, "branch", "--list", "feature/a")  # 枝は残る
    assert len(_parents(w)) == 2


def test_unwritable_tmpdir_is_reported_without_a_path(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    env = {**w.env(), "TMPDIR": str(w.tmp / "no-such-dir" / "deeper")}
    proc = subprocess.run(
        [_node(), str(CLI), "plan", str(w.repo), "--source", "feature/a"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert proc.returncode in (1, 2), proc.stderr
    assert str(w.tmp) not in proc.stdout + proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1])["ok"] is False


def test_cleanup_removes_a_worktree_that_has_only_ignored_files(w):
    """無視ファイルだけなら、tgz に退避してから worktree と枝を消す（変更・未追跡があれば残す。上のテスト）。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    (wt / "local.ign").write_text("ビルドの生成物\n")  # .gitignore の *.ign
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out
    assert out["result"]["cleanup"]["done"] == ["worktree", "branch"], out
    assert not wt.exists()
    backups = list((w.repo / ".git" / "pi-cleanup-backups").glob("a-*.tgz"))
    assert len(backups) == 1
    assert len(_parents(w)) == 2


def test_cleanup_keeps_a_worktree_with_a_live_owner_lock(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    reason = f"owner=worker id=w1 pid={os.getpid()} started={int(time.time())}"
    _git(w.repo, "worktree", "lock", "--reason", reason, str(wt))
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out
    assert (
        wt.exists()
        and "worktree" not in out["result"]["cleanup"]["done"]
        and out["result"]["warnings"]
    )
    assert "feature/a" in _git(w.repo, "branch", "--list", "feature/a")


def test_cleanup_keeps_a_worktree_with_a_stale_owner_lock(w):
    # 意図して変更: 旧い挙動（残骸を unlock して worktree を削除）を、「解除せず残して reap を案内」へ
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    dead = subprocess.Popen(["true"])
    dead.wait()
    reason = f"owner=worker id=w1 pid={dead.pid} started={int(time.time())}"
    _git(w.repo, "worktree", "lock", "--reason", reason, str(wt))
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out
    assert "worktree" not in out["result"]["cleanup"]["done"], out
    assert any("wt_owner.py reap" in x for x in out["result"]["warnings"]), out
    assert wt.exists() and "locked" in _git(w.repo, "worktree", "list", "--porcelain")
    assert "feature/a" in _git(w.repo, "branch", "--list", "feature/a")


def test_cleanup_keeps_a_worktree_with_an_untracked_file(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    (wt / "wip.txt").write_text("未追跡\n")
    (wt / "local.ign").write_text("ign\n")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out
    assert (wt / "wip.txt").exists() and (wt / "local.ign").exists() and out["result"]["warnings"]


def test_cleanup_does_not_run_filters_from_the_source_worktree_config(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    wt = w.tmp / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    marker = w.tmp / "MARK-filter"
    _git(w.repo, "config", "extensions.worktreeConfig", "true")
    _git(wt, "config", "--worktree", "filter.x.clean", f"touch {marker}; cat")
    (wt / ".gitattributes").write_text("* filter=x\n")
    (wt / "a.txt").write_text("変更\n")
    rc, out, _ = w.merge("feature/a", "m\n", "--cleanup", "branch_and_worktree")
    assert rc == 0 and out["ok"], out
    assert not marker.exists()  # 設定が指すコードは動かない
    assert wt.exists() and "worktree" not in out["result"]["cleanup"]["done"]


def test_ignored_file_that_appears_after_the_checks_is_not_overwritten(w):
    """最終の検査の後 (ff の前) に現れた ignored は、--no-overwrite-ignore で守る。"""
    w.feature("feature/a", {"keep.ign": "統合側\n"}, force=True)
    before = w.rev()
    out = w.api(
        """import { writeFileSync } from "node:fs";
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => writeFileSync(arg.repo + "/keep.ign", "利用者のファイル\\n") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    assert out["ok"] is False, out
    assert (w.repo / "keep.ign").read_text(encoding="utf-8") == "利用者のファイル\n"
    assert w.rev() == before  # 統合のコミットは反映されない


def test_a_new_merge_is_refused_while_the_previous_state_remains(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    w.feature("feature/b", {"b.txt": "b\n"})
    w.api(
        """import { writeFileSync } from "node:fs";
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => writeFileSync(arg.repo + "/a.txt", "手元\\n") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    state = w.git_dir() / "pr-viewer-merge.state"
    before = state.read_text(encoding="utf-8")
    rc, out, _ = w.merge("feature/b")
    assert rc == 2 and out["code"] == "recover_needed" and "recover" in out["reason"], out
    assert state.read_text(encoding="utf-8") == before  # 復旧の記録を上書き・削除しない
    assert not (w.repo / "b.txt").exists()


def test_recover_keeps_a_user_file_that_git_refused_to_overwrite(w):
    """統合が作るパスと同名の利用者のファイルを、「統合の残骸」として消さない。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    w.api(
        """import { writeFileSync } from "node:fs";
const r = await M.executeMerge(
  { repo: arg.repo, source: "feature/a", message: "feat: a\\n" }, undefined,
  { beforeAdvance: () => writeFileSync(arg.repo + "/a.txt", "利用者のファイル\\n") });
console.log(JSON.stringify(r));""",
        {"repo": str(w.repo)},
    )
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed", out
    assert (w.repo / "a.txt").read_text(encoding="utf-8") == "利用者のファイル\n"
    assert (w.git_dir() / "pr-viewer-merge.state").exists()  # 手で確認できるよう残す


def test_recover_never_deletes_anything_in_a_directory_that_replaced_a_file(w):
    """ファイル d をディレクトリ d/ に変える統合の途中: d/ に利用者のファイルがあっても、recover は何も消さない。"""
    _commit(w.repo, {"d": "ファイル\n"}, "add file d")
    _git(w.repo, "checkout", "-q", "-b", "feature/a", "develop")
    (w.repo / "d").unlink()
    (w.repo / "d").mkdir()
    (w.repo / "d/a.txt").write_text("a\n")
    _git(w.repo, "add", "-A")
    _git(w.repo, "commit", "-q", "-m", "d をディレクトリに")
    _git(w.repo, "checkout", "-q", "develop")
    commit, old = _commit_for(w, "feature/a")
    # 途中で止まった状態: d はディレクトリになり、統合が書いた d/a.txt と、利用者の d/keep.txt がある
    (w.repo / "d").unlink()
    (w.repo / "d").mkdir()
    (w.repo / "d/a.txt").write_text("a\n")
    (w.repo / "d/keep.txt").write_text("利用者\n")
    st = _write_state(
        w, targetOld=old, commit=commit, touched=["d", "d/a.txt"], added=["d/a.txt"], newDirs=["d"]
    )
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed", out
    assert out["details"]["cause"] == "worktree_not_clean"
    assert (w.repo / "d/keep.txt").read_text(encoding="utf-8") == "利用者\n"
    assert (w.repo / "d/a.txt").exists() and st.exists()
    # 利用者が自分のファイルを退避し、d を元に戻した後に recover すると解除される
    (w.repo / "d/keep.txt").rename(w.tmp / "keep.txt")
    (w.repo / "d/a.txt").unlink()
    (w.repo / "d").rmdir()
    _git(w.repo, "checkout", "--", "d")
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "cleared", out
    assert (w.repo / "d").read_text(encoding="utf-8") == "ファイル\n"


def test_recover_refuses_when_someone_else_moved_target_even_if_the_worktree_is_clean(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    commit, old = _commit_for(w, "feature/a")
    _commit(w.repo, {"x.txt": "別の誰か\n"}, "someone else")
    st = _write_state(w, targetOld=old, commit=commit, touched=["a.txt"], added=["a.txt"])
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["details"]["cause"] == "target_moved", out
    assert st.exists()  # 状態は解除しない


def test_recover_never_removes_index_lock_and_refuses_an_operation_in_progress(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    commit, old = _commit_for(w, "feature/a")
    _write_state(w, targetOld=old, commit=commit, touched=["a.txt"], added=["a.txt"])
    lock = w.git_dir() / "index.lock"
    lock.write_text("")  # いま動いている別の git かもしれない。古さによらず、消さない
    old_time = time.time() - 3600
    os.utime(lock, (old_time, old_time))
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["details"]["indexLock"] is True and lock.exists()
    lock.unlink()  # index.lock を利用者が解除した後でも、進行中の操作だけで断る
    (w.git_dir() / "CHERRY_PICK_HEAD").write_text(old + "\n")
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["details"]["operation"] is True and out["details"]["indexLock"] is False
    # 利用者が確認して手で解除した後は、状態だけが解除される
    (w.git_dir() / "CHERRY_PICK_HEAD").unlink()
    rc, out, _ = w.cli("recover")
    assert rc == 0 and out["state"] == "cleared"


def test_recover_does_not_rmdir_outside_the_worktree_from_newdirs(w):
    victim = w.tmp / "empty-victim"
    victim.mkdir()
    _write_state(
        w, targetOld=w.rev(), commit=NULL_OID, touched=[], added=[], newDirs=["../empty-victim"]
    )
    rc, out, _ = w.cli("recover")
    assert rc == 2 and out["code"] == "failed"
    assert victim.exists()


def test_identity_is_read_from_the_target_worktree_config(w):
    """develop が linked worktree にあり、user.* がその worktree の設定にだけある場合。"""
    w.feature("feature/a", {"a.txt": "a\n"})
    _git(w.repo, "checkout", "-q", "-b", "scratch")
    wt = w.tmp / "wt-develop"
    _git(w.repo, "worktree", "add", "-q", str(wt), "develop")
    _git(w.repo, "config", "extensions.worktreeConfig", "true")
    _git(w.repo, "config", "--unset", "user.name")
    _git(w.repo, "config", "--unset", "user.email")
    _git(wt, "config", "--worktree", "user.name", "Worktree Dev")
    _git(wt, "config", "--worktree", "user.email", "wt@example.com")
    rc, out, _ = w.merge("feature/a")
    assert rc == 0 and out["ok"], out
    fmt = _git(w.repo, "log", "-1", "--format=%an|%ae", "develop").strip()
    assert fmt == "Worktree Dev|wt@example.com"


def test_no_absolute_path_in_any_output(w):
    w.feature("feature/a", {"a.txt": "a\n"})
    w.feature("feature/b", {"README.md": "b\n"})
    w.feature("feature/c", {"README.md": "c\n"})
    seen = []
    for rc_out in (
        w.plan("feature/a"),
        w.merge("feature/b"),
        w.merge("feature/c"),  # conflict
        w.plan("feature/none"),
        w.merge("feature/a", "bad\x01"),
        w.cli("recover"),
    ):
        seen.append(rc_out[2].stdout + rc_out[2].stderr)
    text = "\n".join(seen)
    assert str(w.tmp) not in text and str(w.repo) not in text and "/home/" not in text


# ---------------------------------------------------------------- 15・S1・S3 の静的な確認


SOURCES = [APP / "merge.ts", APP / "merge-git.ts", APP / "merge-cli.ts"]


def test_imports_are_node_builtins_and_local_only():
    for p in SOURCES:
        text = p.read_text(encoding="utf-8")
        specs = re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", text)
        assert specs, p.name
        for spec in specs:
            assert spec.startswith(("node:", "./")), (p.name, spec)
            assert "harness" not in spec, (p.name, spec)
        assert "harness" not in "\n".join(re.findall(r"""["'][^"'\n]*["']""", text)), p.name


def test_git_invocation_is_hardened_and_never_forceful():
    git = (APP / "merge-git.ts").read_text(encoding="utf-8")
    for needle in (
        "core.hooksPath=/dev/null",
        "core.fsmonitor=false",
        "core.attributesFile=/dev/null",
        "diff.external=",
        "protocol.ext.allow=never",
        "gc.auto=0",
        "shell: false",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_TERMINAL_PROMPT",
        "GIT_NO_LAZY_FETCH",
        "GIT_ALLOW_PROTOCOL",
        "GIT_EDITOR",
        "GIT_MERGE_AUTOEDIT",
    ):
        assert needle in git, needle
    assert "shell: true" not in git
    sources = "\n".join(p.read_text(encoding="utf-8") for p in SOURCES)
    for forbidden in (
        '"--hard"',
        '["clean"',
        '"push"',
        '"-D"',
        '"-f"',
        '"--force"',
        "exec(",
        "execSync",
    ):
        assert forbidden not in sources, forbidden
    # update-ref は必ず旧先頭（CAS）を渡す
    for m in re.finditer(r"""\[\s*"update-ref"[^\]]*\]""", sources):
        assert "oldOid" in m.group(0) or "sourceOid" in m.group(0), m.group(0)


# ---------------------------------------------------------------- 16 plan は読み取り専用


def _snapshot(w: World) -> tuple:
    refs = _git(w.repo, "for-each-ref")
    index = hashlib.sha256((w.git_dir() / "index").read_bytes()).hexdigest()
    tree = sorted(
        (str(p.relative_to(w.repo)), p.read_bytes() if p.is_file() else b"")
        for p in w.repo.rglob("*")
        if ".git" not in p.relative_to(w.repo).parts
    )
    head = (w.git_dir() / "HEAD").read_text()
    return refs, index, tree, head, w.status()


def test_plan_does_not_change_refs_index_or_worktree(w):
    w.feature("feature/a", {"a.txt": "a\n", "other.txt": "変更\n"})
    w.feature("feature/b", {"README.md": "b\n"})
    (w.repo / "u.txt").write_text("untracked\n")
    (w.repo / "README.md").write_text("手元\n")  # dirty でも plan の前後は同じ
    before = _snapshot(w)
    for src in ("feature/a", "feature/b", "feature/none", "main"):
        w.plan(src)
    assert _snapshot(w) == before
    _no_leftovers(w)
