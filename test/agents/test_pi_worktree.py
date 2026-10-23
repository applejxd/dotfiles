"""子エージェントの worktree 隔離 (``home/dot_config/pi/harness/worktree.ts``) の試験。

``test/agents/pi/worktree_driver.mjs`` が worktree.ts を読んで結果を JSON で出す。node の型除去
(strip-types) を使うので、22.18 未満の node では飛ばす。試験ごとに使い捨ての git リポジトリを
``tmp_path`` に作る (本物のリポジトリは触らない)。

see docs/change/0029-worktree-isolation.md#w1-の実装計画
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node

RUNNER = ROOT / "test" / "agents" / "pi" / "worktree_driver.mjs"

pytestmark = pytest.mark.skipif(
    _node() is None or not Path("/usr/bin/git").exists(),
    reason="型除去に対応した node (22.18 以上) か /usr/bin/git が無い",
)

GITIGNORE = ".tmp/\nignored/\n*.log\n"
NODENY = {"globs": [], "exceptions": []}
ENVDENY = {"globs": ["**/.env"], "exceptions": []}
PATCH = "job-00000001.patch"  # jid(1) を含む (patch 名は jobId を含める必要がある)
# 親の作業ツリーの比較から外すもの (ignored と、ハーネスの置き場)
SKIP_TOP = {".git", ".tmp", "ignored", "x.log"}


def jid(n: int) -> str:
    return f"job-{n:08x}"


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.markers = tmp_path / "markers"
        self.markers.mkdir()
        self.repo = tmp_path.resolve() / "repo"
        base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        base["HOME"] = str(self.home)  # global 設定 (filter など) を遮断する
        self.node_env = dict(base)
        self.git_env = dict(base)
        self.git_env.update(
            GIT_AUTHOR_NAME="t",
            GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@example.invalid",
            GIT_CONFIG_NOSYSTEM="1",
        )

    def git(self, *args, cwd=None, check=True, binary=False):
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            env=self.git_env,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            check=False,
        )
        if check:
            assert proc.returncode == 0, f"git {args}: {proc.stderr}"
        return proc.stdout if check else proc

    def argv(self, **kw):
        return [_node(), str(RUNNER), json.dumps(kw)]

    def op(self, extra_env=None, **kw):
        env = dict(self.node_env)
        env.update(extra_env or {})
        proc = subprocess.run(
            self.argv(**kw),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
        return json.loads(proc.stdout)

    def create(self, n: int, **kw):
        return self.op(op="create", repo=str(self.repo), jobId=jid(n), readDeny=NODENY, **kw)

    def collect(self, n: int, patch: str | None = None, **kw):
        patch = patch or f"{jid(n)}.patch"  # 名前は jobId を含む必要がある
        return self.op(op="collect", repo=str(self.repo), jobId=jid(n), patchName=patch, **kw)


def code(res) -> str:
    assert "error" in res, res
    return res["error"]["code"]


def build_repo(e: Env, gitignore: str | None = GITIGNORE, dirty: bool = True) -> Path:
    repo = e.repo
    repo.mkdir()
    e.git("init", "-q", "-b", "main")
    e.git("config", "user.name", "t")
    e.git("config", "user.email", "t@example.invalid")
    e.git("config", "commit.gpgsign", "false")
    if gitignore is not None:
        (repo / ".gitignore").write_text(gitignore)
    (repo / "tracked.txt").write_text("a\nb\nc\nd\ne\n")
    (repo / "other.txt").write_text("1\n2\n3\n")
    (repo / "run.sh").write_text("#!/bin/sh\necho hi\n")
    os.chmod(repo / "run.sh", 0o644)
    (repo / "bin.dat").write_bytes(bytes(range(256)) * 4)
    (repo / "crlf.txt").write_bytes(b"x\r\ny\r\n")
    (repo / "dir").mkdir()
    (repo / "dir" / "keep.txt").write_text("k\n")
    e.git("add", "-A")
    e.git("commit", "-q", "-m", "init")
    for name in ("pre-commit", "post-checkout"):
        hook = repo / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\ntouch '{e.markers / name}'\n")
        os.chmod(hook, 0o755)
    if dirty:
        (repo / "tracked.txt").write_text("a\nB-parent\nc\nd\ne\n")  # 追跡の変更
        (repo / "untracked_new.txt").write_text("u1\nu2\n")  # 未追跡
        (repo / "tool.sh").write_text("#!/bin/sh\necho tool\n")  # 未追跡の実行ファイル
        os.chmod(repo / "tool.sh", 0o755)
        (repo / "ignored").mkdir()
        (repo / "ignored" / "cache.bin").write_text("ignored\n")
        (repo / "x.log").write_text("log\n")
        os.symlink("tracked.txt", repo / "link")
    return repo


def tree_state(root: Path) -> dict:
    """作業ツリーの内容・種別・実行ビット (ignored と置き場を除く)。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in SKIP_TOP]
            filenames = [f for f in filenames if f not in SKIP_TOP]
        for name in list(dirnames) + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_file():
                out[rel] = ("file", p.read_bytes(), bool(p.stat().st_mode & stat.S_IXUSR))
    return out


def mtimes(root: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in {".git", ".tmp"}]
            filenames = [f for f in filenames if f not in {".git", ".tmp"}]
        for name in filenames:
            p = Path(dirpath) / name
            out[str(p.relative_to(root))] = p.lstat().st_mtime_ns
    return out


def objects(e: Env) -> set[str]:
    base = e.repo / ".git" / "objects"
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


def index_hash(e: Env) -> str:
    return hashlib.sha256((e.repo / ".git" / "index").read_bytes()).hexdigest()


def settle(e: Env) -> None:
    """git status が index を更新し直す分を先に済ませる (比較の前後で index が揺れないように)。"""
    e.git("status", "--porcelain")


def repo_state(e: Env) -> dict:
    return {
        "index": index_hash(e),
        "head": e.git("rev-parse", "HEAD").strip(),
        "branch": e.git("symbolic-ref", "HEAD").strip(),
        "refs": e.git("for-each-ref"),
        "status": e.git("status", "--porcelain"),
    }


def wt_blocks(e: Env) -> list[list[str]]:
    out = e.git("worktree", "list", "--porcelain").strip()
    return [b.splitlines() for b in out.split("\n\n")]


def block_for(e: Env, path: str) -> list[str]:
    return next(b for b in wt_blocks(e) if b[0] == f"worktree {path}")


def locked(block: list[str]) -> bool:
    return any(line == "locked" or line.startswith("locked ") for line in block)


def child_edit(wt: Path) -> None:
    (wt / "tracked.txt").write_text("a\nB-parent\nc\nD-child\ne\n")
    (wt / "untracked_new.txt").write_text("u1\nu2\nu3-child\n")
    (wt / "other.txt").unlink()
    (wt / "new_child.txt").write_text("child-new\n")
    os.chmod(wt / "run.sh", 0o755)
    (wt / "bin.dat").write_bytes(bytes(range(255, -1, -1)) * 4)
    (wt / "crlf.txt").write_bytes(b"x\r\ny2\r\n")


def ref_exists(e: Env, ref: str) -> bool:
    return e.git("rev-parse", "--verify", "-q", ref, check=False).returncode == 0


# ─── 1. 正常系 ────────────────────────────────────────────────────────────


def test_create_reproduces_the_dirty_tree_without_touching_git_state(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    parent = tree_state(e.repo)
    settle(e)
    before = repo_state(e)
    rec = e.create(1)
    assert "error" not in rec, rec
    wt = e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(1)}"
    assert rec["version"] == 1 and rec["state"] == "running" and rec["jobId"] == jid(1)
    assert rec["repo"] == str(e.repo) and rec["worktree"] == str(wt)
    assert rec["startCommit"] == before["head"]
    assert rec["snapshotCommit"] != rec["startCommit"]
    assert e.git("rev-parse", f"{rec['snapshotCommit']}^").strip() == rec["startCommit"]
    # 内容は親の作業ツリーと同じ (ignored を除く)。ignored は持ち込まれない
    assert tree_state(wt) == parent
    assert not (wt / "ignored").exists() and not (wt / "x.log").exists()
    assert e.git("status", "--porcelain", cwd=wt) == ""
    assert locked(block_for(e, str(wt)))
    # 記録
    rec_file = e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json"
    assert json.loads(rec_file.read_text()) == rec
    assert stat.S_IMODE(rec_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(rec_file.parent.stat().st_mode) == 0o700
    assert not (rec_file.parent / ".lock").exists()
    # 親の index・ブランチ・全 ref・状態は不変。一時 index は残らない
    assert repo_state(e) == before
    assert not list((e.repo / ".git").glob("pi-agent-index-*"))
    # hook は走らない。対照として、通常の worktree add では走る (試験の仕掛けが効いている証拠)
    assert not (e.markers / "pre-commit").exists()
    assert not (e.markers / "post-checkout").exists()
    e.git("worktree", "add", "--detach", str(tmp_path / "ctl"), "HEAD")
    assert (e.markers / "post-checkout").exists()


# ─── 2〜4. 事前選別 (オブジェクトを書く前に止まる) ─────────────────────────


def test_protected_path_stops_before_any_object_is_written(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    (e.repo / ".env").write_text("TOKEN=secret-value\n")
    before = objects(e)
    res = e.op(op="create", repo=str(e.repo), jobId=jid(1), readDeny=ENVDENY)
    assert code(res) == "protected_path"
    assert res["error"]["detail"]["path"] == ".env"
    assert "secret-value" not in json.dumps(res)
    assert objects(e) == before
    assert not (e.repo / ".tmp" / "worktrees").exists()
    assert not list((e.repo / ".tmp" / "subagents" / "worktrees").glob("*"))
    assert "pi-agent" not in e.git("worktree", "list")


def test_protected_path_matches_exceptions_and_subdirectories(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    (e.repo / ".env.example").write_text("TOKEN=\n")
    deny = {
        "globs": ["**/.env*"],
        "exceptions": [{"deny": "**/.env*", "except": ["**/.env.example"]}],
    }
    ok = e.op(op="create", repo=str(e.repo), jobId=jid(1), readDeny=deny)
    assert "error" not in ok, ok
    (e.repo / "sub").mkdir()
    (e.repo / "sub" / ".env").write_text("x\n")
    res = e.op(op="create", repo=str(e.repo), jobId=jid(2), readDeny=deny)
    assert code(res) == "protected_path" and res["error"]["detail"]["path"] == "sub/.env"


def test_too_large_per_file_and_total(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    (e.repo / "big.bin").write_bytes(b"\0" * 5000)
    before = objects(e)
    res = e.op(
        op="create", repo=str(e.repo), jobId=jid(1), readDeny=NODENY, limits={"maxFileBytes": 1000}
    )
    assert code(res) == "too_large"
    assert res["error"]["detail"]["path"] == "big.bin" and res["error"]["detail"]["size"] == 5000
    res = e.op(
        op="create", repo=str(e.repo), jobId=jid(1), readDeny=NODENY, limits={"maxTotalBytes": 100}
    )
    assert code(res) == "too_large" and res["error"]["detail"]["total"] >= 5000
    assert objects(e) == before


def test_filter_driver_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.git("config", "filter.x.clean", "cat")
    before = objects(e)
    res = e.create(1)
    assert code(res) == "filter_driver" and res["error"]["detail"]["names"] == ["x"]
    assert objects(e) == before


def test_preflight_lists_candidates_and_writes_nothing(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    before = objects(e)
    res = e.op(op="preflight", repo=str(e.repo), readDeny=NODENY)
    assert "error" not in res, res
    assert res["candidates"]["tracked"] == ["tracked.txt"]
    assert res["candidates"]["untracked"] == ["link", "tool.sh", "untracked_new.txt"]
    expected = sum(
        (e.repo / n).stat().st_size for n in ("tracked.txt", "tool.sh", "untracked_new.txt")
    )
    assert res["totalBytes"] == expected
    assert objects(e) == before
    assert not (e.repo / ".tmp").exists()


def test_preflight_requires_a_repo_root_and_a_head(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    res = e.op(op="preflight", repo=str(e.repo / "dir"), readDeny=NODENY)
    assert code(res) == "bad_placement"
    empty = tmp_path / "empty"
    empty.mkdir()
    e.git("init", "-q", "-b", "main", cwd=empty)
    assert code(e.op(op="preflight", repo=str(empty), readDeny=NODENY)) == "no_head"


# ─── 5. 配置先 ────────────────────────────────────────────────────────────


def test_tmp_not_ignored_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e, gitignore=None)
    res = e.create(1)
    assert code(res) == "not_ignored"
    assert not (e.repo / ".tmp").exists()  # 親の作業ツリーに何も作らない


def test_tmp_symlink_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, e.repo / ".tmp")
    assert code(e.create(1)) == "bad_placement"
    assert not list(elsewhere.iterdir())


# ─── 6・7. 同時数・job id ─────────────────────────────────────────────────


def test_max_worktrees_refuses_and_keeps_existing(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    assert "error" not in e.create(1, limits={"maxWorktrees": 1})
    res = e.create(2, limits={"maxWorktrees": 1})
    assert code(res) == "too_many"
    assert res["error"]["detail"]["jobIds"] == [jid(1)]
    assert (e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(1)}").is_dir()
    assert not (e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(2)}").exists()


@pytest.mark.parametrize(
    "bad", ["../x", "job-ZZ", "", "job-1234567", "job-" + "a" * 33, "job-abcdef12\n"]
)
def test_bad_job_id(tmp_path, bad):
    e = Env(tmp_path)
    assert code(e.op(op="validate", id=bad)) == "bad_job_id"
    assert code(e.op(op="create", repo=str(tmp_path), jobId=bad, readDeny=NODENY)) == "bad_job_id"
    assert e.op(op="validate", id="job-0123abcd")["id"] == "job-0123abcd"


@pytest.mark.parametrize(
    "bad",
    [
        "../x.patch",
        "a/b.patch",
        "x.txt",
        "a..b.patch",
        "",
        ".patch/x",
        "child.patch",
        "job-00000002.patch",
    ],
)
def test_bad_patch_name(tmp_path, bad):
    e = Env(tmp_path)
    assert (
        code(e.op(op="collect", repo=str(tmp_path), jobId=jid(1), patchName=bad))
        == "bad_patch_name"
    )


# ─── 8. 回収 ──────────────────────────────────────────────────────────────


def test_collect_patch_round_trips_into_the_parent(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    wt = Path(rec["worktree"])
    child_edit(wt)
    res = e.collect(1)
    assert res["changed"] is True, res
    ref = f"refs/pi-agent/{jid(1)}"
    assert res["ref"] == ref and e.git("rev-parse", ref).strip() == res["resultCommit"]
    assert e.git("rev-parse", f"{res['resultCommit']}^").strip() == rec["snapshotCommit"]
    patch_file = e.repo / ".tmp" / "subagents" / PATCH
    data = patch_file.read_bytes()
    assert res["patch"]["path"] == str(patch_file)
    assert res["patch"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert stat.S_IMODE(patch_file.stat().st_mode) == 0o600
    # 子の変更だけ (親の未コミットの変更を含まない)。バイナリと CRLF はそのまま
    assert b"+B-parent" not in data and b"tool.sh" not in data and b"+u1" not in data
    assert b"y2\r\n" in data and b"GIT binary patch" in data
    # 記録
    stored = json.loads(
        (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").read_text()
    )
    assert stored["state"] == "collected" and stored["resultCommit"] == res["resultCommit"]
    assert stored["ref"] == ref and stored["patch"] == res["patch"]
    # worktree は残り、lock は外れる
    assert wt.is_dir() and not locked(block_for(e, str(wt)))
    # 親 (起点の状態のまま) に適用でき、子の変更が再現する
    e.git("apply", "--check", "--binary", str(patch_file))
    e.git("apply", "--binary", str(patch_file))
    assert tree_state(e.repo) == tree_state(wt)
    # 回収済みの job は再回収できない (記録は変わらない)
    again = e.collect(1, patch=f"{jid(1)}-again.patch")
    assert code(again) == "collect_failed"
    assert (
        json.loads((e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").read_text())
        == stored
    )


def test_collect_checks_protected_paths_when_given(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    (Path(rec["worktree"]) / ".env").write_text("TOKEN=secret-value\n")
    res = e.collect(1, readDeny=ENVDENY)
    assert code(res) == "collect_failed" and res["error"]["detail"]["cause"] == "protected_path"
    assert "secret-value" not in json.dumps(res)
    assert not ref_exists(e, f"refs/pi-agent/{jid(1)}")
    assert not (e.repo / ".tmp" / "subagents" / PATCH).exists()
    stored = json.loads(
        (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").read_text()
    )
    assert stored["state"] == "kept"


# ─── 9. 変更なし ──────────────────────────────────────────────────────────


def test_collect_without_changes_removes_worktree_and_record(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    res = e.collect(1)
    assert res == {"changed": False}
    assert not Path(rec["worktree"]).exists()
    assert "pi-agent" not in e.git("worktree", "list")
    assert not (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").exists()
    assert not ref_exists(e, f"refs/pi-agent/{jid(1)}")
    assert not (e.repo / ".tmp" / "subagents" / PATCH).exists()


# ─── 10. 回収の失敗 ───────────────────────────────────────────────────────


def test_collect_failure_keeps_everything(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec_a = e.create(1)
    e.create(2)
    other = e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(2)}.json"
    other_bytes = other.read_bytes()
    shutil.rmtree(rec_a["worktree"])
    res = e.collect(1)
    assert code(res) == "collect_failed" and res["error"]["detail"]["stage"] == "worktree"
    stored = json.loads(
        (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").read_text()
    )
    assert stored["state"] == "kept" and stored["note"].startswith("worktree")
    assert not ref_exists(e, f"refs/pi-agent/{jid(1)}")
    assert not list((e.repo / ".tmp" / "subagents").glob("*.patch"))
    assert other.read_bytes() == other_bytes


def test_collect_patch_name_collision_does_not_overwrite(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    wt = Path(rec["worktree"])
    child_edit(wt)
    existing = e.repo / ".tmp" / "subagents" / f"{jid(1)}-c.patch"
    existing.write_bytes(b"old")
    res = e.collect(1, patch=existing.name)
    assert code(res) == "collect_failed" and res["error"]["detail"]["stage"] == "patch"
    assert existing.read_bytes() == b"old"
    stored = json.loads(
        (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").read_text()
    )
    assert stored["state"] == "kept" and "patch" not in stored
    assert ref_exists(e, f"refs/pi-agent/{jid(1)}")  # 結果は ref に残る
    assert wt.is_dir() and locked(block_for(e, str(wt)))
    assert sorted(p.name for p in (e.repo / ".tmp" / "subagents").iterdir()) == [
        existing.name,
        "worktrees",
    ]
    # 別名で再回収できる (kept からの復旧)
    again = e.collect(1, patch=f"{jid(1)}-d.patch")
    assert again["changed"] is True


# ─── 11. 照合 ─────────────────────────────────────────────────────────────


def test_reconcile_detects_mismatches_and_ignores_user_worktrees(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    records = e.repo / ".tmp" / "subagents" / "worktrees"
    # A: 記録を消す → worktree_only
    e.create(0xA)
    (records / f"{jid(0xA)}.json").unlink()
    # B: worktree を失う → record_only
    rec_b = e.create(0xB)
    e.git("worktree", "unlock", rec_b["worktree"])
    shutil.rmtree(rec_b["worktree"])
    e.git("worktree", "prune")
    # C: ref だけ → ref_only
    e.git("update-ref", f"refs/pi-agent/{jid(0xC)}", "HEAD")
    # D: 回収済みで patch を失う → patch_missing
    rec_d = e.create(0xD)
    child_edit(Path(rec_d["worktree"]))
    assert e.collect(0xD, patch=f"{jid(0xD)}-d.patch")["changed"] is True
    (e.repo / ".tmp" / "subagents" / f"{jid(0xD)}-d.patch").unlink()
    # E: running のまま → stuck_running
    e.create(0xE)
    # 利用者の worktree (リポジトリの外と、.tmp/worktrees の中の別名)
    e.git("worktree", "add", "--detach", str(tmp_path / "other"), "HEAD")
    e.git("worktree", "add", "--detach", str(e.repo / ".tmp" / "worktrees" / "mine"), "HEAD")
    before = (
        objects(e),
        e.git("for-each-ref"),
        e.git("worktree", "list"),
        sorted(p.name for p in records.iterdir()),
    )

    issues = e.op(op="reconcile", repo=str(e.repo))
    assert sorted((i["jobId"], i["issue"]) for i in issues) == sorted(
        [
            (jid(0xA), "worktree_only"),
            (jid(0xB), "record_only"),
            (jid(0xC), "ref_only"),
            (jid(0xD), "patch_missing"),
            (jid(0xE), "stuck_running"),
        ]
    )
    text = json.dumps(issues)
    assert "other" not in text and "mine" not in text
    # 何も消さない・直さない
    after = (
        objects(e),
        e.git("for-each-ref"),
        e.git("worktree", "list"),
        sorted(p.name for p in records.iterdir()),
    )
    assert after == before
    live = e.op(op="reconcile", repo=str(e.repo), liveJobIds=[jid(0xE)])
    assert (jid(0xE), "stuck_running") not in {(i["jobId"], i["issue"]) for i in live}


def test_list_records_reports_broken_files(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    records = e.repo / ".tmp" / "subagents" / "worktrees"
    (records / "junk.json").write_text("{not json")
    (records / f"{jid(2)}.json").write_text(json.dumps({"version": 2, "jobId": jid(2)}))
    got = e.op(op="list", repo=str(e.repo))
    assert [r["jobId"] for r in got if "broken" not in r] == [jid(1)]
    assert sorted(Path(r["file"]).name for r in got if r.get("broken")) == [
        f"{jid(2)}.json",
        "junk.json",
    ]


# ─── 12. 破棄 ─────────────────────────────────────────────────────────────


def test_discard_removes_everything_and_tolerates_missing_parts(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    e.collect(1)
    keep = e.create(2)
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(1))
    assert "error" not in out, out
    assert not Path(rec["worktree"]).exists()
    assert not ref_exists(e, f"refs/pi-agent/{jid(1)}")
    assert not (e.repo / ".tmp" / "subagents" / PATCH).exists()
    assert not (e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(1)}.json").exists()
    assert str(Path(rec["worktree"])) not in e.git("worktree", "list")
    # 他の job は無傷。記録のない job の破棄は拒否される (not_owned)
    assert Path(keep["worktree"]).is_dir()
    assert code(e.op(op="discard", repo=str(e.repo), jobId=jid(9))) == "not_owned"
    # ディレクトリが先に無くなっていても管理領域まで消える
    shutil.rmtree(keep["worktree"])
    e.op(op="discard", repo=str(e.repo), jobId=jid(2))
    assert "pi-agent" not in e.git("worktree", "list")
    assert not (e.repo / ".git" / "worktrees" / f"pi-agent-{jid(2)}").exists()


# ─── 13. 時間の上限 ───────────────────────────────────────────────────────


def test_exhausted_budget_makes_run_git_time_out(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    assert code(e.op(op="budget0", repo=str(e.repo))) == "timeout"


# ─── 14. 親の作業ツリーに触れない ─────────────────────────────────────────


def test_create_and_collect_leave_the_parent_files_alone(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    files = tree_state(e.repo)
    times = mtimes(e.repo)
    settle(e)
    state = repo_state(e)
    state_no_refs = {k: v for k, v in state.items() if k != "refs"}
    rec = e.create(1)
    assert tree_state(e.repo) == files and mtimes(e.repo) == times
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True
    assert tree_state(e.repo) == files and mtimes(e.repo) == times
    after = repo_state(e)
    assert {k: v for k, v in after.items() if k != "refs"} == state_no_refs
    # 増えた ref は refs/pi-agent だけ
    new_refs = [ln for ln in after["refs"].splitlines() if ln not in state["refs"].splitlines()]
    assert len(new_refs) == 1 and new_refs[0].endswith(f"refs/pi-agent/{jid(1)}")


# ─── 15. 直列化 ───────────────────────────────────────────────────────────


def test_concurrent_creates_serialize_or_report_busy(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    procs = [
        subprocess.Popen(
            e.argv(op="create", repo=str(e.repo), jobId=jid(n), readDeny=NODENY),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=e.node_env,
        )
        for n in (1, 2)
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err[-1500:]
        results.append(json.loads(out))
    ok = [r for r in results if "error" not in r]
    assert ok and all(code(r) == "busy" for r in results if "error" in r)
    registered = [b for b in wt_blocks(e) if "pi-agent-" in b[0]]
    assert len(registered) == len(ok)
    for r in ok:
        assert Path(r["worktree"]).is_dir()
    assert not (e.repo / ".tmp" / "subagents" / "worktrees" / ".lock").exists()
    assert not list((e.repo / ".git").glob("pi-agent-index-*"))


def test_lock_is_never_taken_over_automatically_and_clear_stale_lock_is_explicit(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    lock = e.repo / ".tmp" / "subagents" / "worktrees" / ".lock"
    lock.mkdir(parents=True)
    old = time.time() - 3600
    pid_file = lock / "pid"
    pid_file.write_text(f"{os.getpid()}\n")  # 生きているプロセス (この試験)
    os.utime(lock, (old, old))
    res = e.create(1, limits={"lockWaitMs": 0})
    assert code(res) == "busy" and res["error"]["detail"]["stale"] is False
    assert res["error"]["detail"]["pid"] == os.getpid()
    cleared = e.op(op="clear_stale_lock", repo=str(e.repo))
    assert cleared["cleared"] is False and cleared["reason"] == "pid_alive"
    assert lock.is_dir()
    pid_file.write_text("2147483646\n")  # 存在しないプロセス
    now = time.time()
    os.utime(lock, (now, now))
    res = e.create(1, limits={"lockWaitMs": 0})
    assert code(res) == "busy" and res["error"]["detail"]["stale"] is False  # 新しい
    cleared = e.op(op="clear_stale_lock", repo=str(e.repo))
    assert cleared["cleared"] is False and cleared["reason"] == "fresh"
    assert lock.is_dir() and pid_file.exists()
    os.utime(lock, (old, old))
    res = e.create(1, limits={"lockWaitMs": 0})
    # 死んだ pid ・古い mtime でも自動では奪わない (stale を報告するだけ)
    assert code(res) == "busy" and res["error"]["detail"]["stale"] is True
    assert res["error"]["detail"]["pid"] == 2147483646
    assert lock.is_dir()
    cleared = e.op(op="clear_stale_lock", repo=str(e.repo))
    assert cleared == {"cleared": True, "reason": "stale"}
    assert not lock.exists()
    assert e.op(op="clear_stale_lock", repo=str(e.repo))["reason"] == "no_lock"
    assert "error" not in e.create(1)
    assert not lock.exists()
    assert not list(lock.parent.glob(".lock.stale-*"))


# ─── 所有・作成の途中失敗・管理領域・ロックの試験 ─────────────────────────


def rec_file(e: Env, n: int) -> Path:
    return e.repo / ".tmp" / "subagents" / "worktrees" / f"{jid(n)}.json"


def load_rec(e: Env, n: int) -> dict:
    return json.loads(rec_file(e, n).read_text())


def admin_dir(e: Env, n: int) -> Path:
    return e.repo / ".git" / "worktrees" / f"pi-agent-{jid(n)}"


def test_discard_without_record_touches_nothing(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)  # 記録の置き場を作る
    mine = e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(7)}"
    e.git("worktree", "add", "--detach", str(mine), "HEAD")
    e.git("update-ref", f"refs/pi-agent/{jid(7)}", "HEAD")
    before = (e.git("for-each-ref"), e.git("worktree", "list"))
    assert code(e.op(op="discard", repo=str(e.repo), jobId=jid(7))) == "not_owned"
    assert mine.is_dir() and (e.git("for-each-ref"), e.git("worktree", "list")) == before
    # 壊れた記録も所有の証拠にならない (何も消さない)
    rec_file(e, 8).write_text("{not json")
    assert code(e.op(op="discard", repo=str(e.repo), jobId=jid(8))) == "not_owned"
    assert rec_file(e, 8).exists()


def test_discard_keeps_parts_that_do_not_match_the_record(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True
    ref = f"refs/pi-agent/{jid(1)}"
    e.git("update-ref", ref, "HEAD")  # 記録の resultCommit と一致しなくなる
    patch = e.repo / ".tmp" / "subagents" / PATCH
    patch.write_bytes(patch.read_bytes() + b"x")  # sha256 が合わなくなる
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(1))
    assert "error" not in out, out
    assert any("ref kept" in n for n in out["notes"])
    assert any("patch kept" in n for n in out["notes"])
    assert e.git("rev-parse", ref).strip() == e.git("rev-parse", "HEAD").strip()
    assert patch.exists()
    # worktree は消えるが、残したものがあるので記録は kept で残る
    assert not Path(rec["worktree"]).exists()
    stored = load_rec(e, 1)
    assert (
        stored["state"] == "kept"
        and "ref kept" in stored["note"]
        and "patch kept" in stored["note"]
    )


def test_discard_refuses_a_tampered_admin_dir(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    (admin_dir(e, 1) / "config.worktree").write_text("[core]\n\tfsmonitor = true\n")
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(1))
    assert "error" not in out, out
    assert any("config_worktree" in n for n in out["notes"])
    assert Path(rec["worktree"]).is_dir() and admin_dir(e, 1).is_dir()
    assert rec["worktree"] in e.git("worktree", "list")
    assert load_rec(e, 1)["state"] == "kept"


def test_discard_stops_everything_on_an_admin_violation_even_with_ref_and_patch(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    res = e.collect(1)
    assert res["changed"] is True
    ref = f"refs/pi-agent/{jid(1)}"
    patch = e.repo / ".tmp" / "subagents" / PATCH
    (admin_dir(e, 1) / "config.worktree").write_text("[core]\n\tfsmonitor = true\n")
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(1))
    assert "error" not in out, out
    assert any("config_worktree" in n for n in out["notes"])
    assert Path(rec["worktree"]).is_dir() and admin_dir(e, 1).is_dir()
    assert e.git("rev-parse", ref).strip() == res["resultCommit"]
    assert patch.is_file() and rec_file(e, 1).exists()
    stored = load_rec(e, 1)
    assert stored["state"] == "kept" and "config_worktree" in stored["note"]
    assert stored["ref"] == ref and stored["patch"] == res["patch"]


def test_discard_keeps_a_patch_that_another_record_refers_to(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    assert e.collect(1)["changed"] is True
    patch = e.repo / ".tmp" / "subagents" / PATCH
    # 別の job の記録を手で作り、同じ patch を指させる
    other = dict(load_rec(e, 1))
    other.update(
        jobId=jid(2),
        worktree=str(e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(2)}"),
        state="collected",
    )
    other.pop("ref", None)
    other.pop("resultCommit", None)
    rec_file(e, 2).write_text(json.dumps(other))
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(1))
    assert "error" not in out, out
    assert "patch kept: 他の記録が参照" in out["notes"]
    assert patch.is_file()
    assert not rec_file(e, 1).exists() and rec_file(e, 2).exists()
    # 参照している記録が無くなれば消せる
    out = e.op(op="discard", repo=str(e.repo), jobId=jid(2))
    assert "error" not in out, out
    assert not patch.exists() and not rec_file(e, 2).exists()


def test_collect_does_not_reuse_a_patch_that_another_record_refers_to(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    first = e.collect(1)
    assert first["changed"] is True
    patch = e.repo / ".tmp" / "subagents" / PATCH
    # 別の記録が同じ patch を参照し、job 1 は自分の patch 記録を失った状況
    other = dict(load_rec(e, 1))
    other.update(jobId=jid(2), worktree=str(e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(2)}"))
    rec_file(e, 2).write_text(json.dumps(other))
    stored = load_rec(e, 1)
    stored["state"] = "kept"
    stored.pop("patch")
    rec_file(e, 1).write_text(json.dumps(stored))
    res = e.collect(1)
    assert code(res) == "collect_failed" and res["error"]["detail"]["stage"] == "patch"
    assert patch.is_file()


def test_recollect_after_a_crash_following_publish_is_idempotent(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    first = e.collect(1)
    assert first["changed"] is True
    patch = e.repo / ".tmp" / "subagents" / PATCH
    before = patch.read_bytes()
    # patch 公開後・collected 記録前に落ちた状況: 記録を kept (patch なし) へ戻す
    stored = load_rec(e, 1)
    stored["state"] = "kept"
    stored.pop("patch")
    rec_file(e, 1).write_text(json.dumps(stored))
    again = e.collect(1)
    assert again["changed"] is True, again
    assert again["resultCommit"] == first["resultCommit"]
    assert again["patch"]["sha256"] == first["patch"]["sha256"]
    assert patch.read_bytes() == before and load_rec(e, 1)["state"] == "collected"
    # 内容が違う既存の patch は上書きせず失敗する
    patch.write_bytes(before + b"x")
    stored = load_rec(e, 1)
    stored["state"] = "kept"
    rec_file(e, 1).write_text(json.dumps(stored))
    res = e.collect(1)
    assert code(res) == "collect_failed" and res["error"]["detail"]["stage"] == "patch"
    assert patch.read_bytes() == before + b"x"


@pytest.mark.skipif(os.geteuid() == 0, reason="root は書込不可を無視する")
def test_worktree_add_failure_leaves_no_record_or_keeps_what_exists(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    wtdir = e.repo / ".tmp" / "worktrees"
    wtdir.mkdir(parents=True)
    wtdir.chmod(0o500)  # 作成先の親に書けない -> worktree add が失敗する
    try:
        res = e.create(1)
    finally:
        wtdir.chmod(0o700)
    assert code(res) == "git_failed"
    traces = (wtdir / f"pi-agent-{jid(1)}").exists() or admin_dir(e, 1).exists()
    if traces:  # 作りかけがあれば消さずに保持
        assert load_rec(e, 1)["state"] == "kept" and res["error"]["detail"]["kept"] is True
    else:  # 何も作られていなければ記録も残さない
        assert not rec_file(e, 1).exists()
    assert not (rec_file(e, 1).parent / ".lock").exists()
    assert not list((e.repo / ".git").glob("pi-agent-index-*"))


def test_settle_failed_create_keeps_traces_and_drops_only_empty_records(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    stored = load_rec(e, 1)
    stored["state"] = "creating"
    rec_file(e, 1).write_text(json.dumps(stored))
    res = e.op(op="settle_create", repo=str(e.repo), jobId=jid(1))
    assert code(res) == "git_failed" and res["error"]["detail"]["kept"] is True
    assert load_rec(e, 1)["state"] == "kept" and Path(rec["worktree"]).is_dir()
    # 何も作られていない job: 記録だけ消え、元の失敗がそのまま返る
    ghost = dict(stored)
    ghost.update(
        jobId=jid(2),
        worktree=str(e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(2)}"),
        state="creating",
    )
    rec_file(e, 2).write_text(json.dumps(ghost))
    res = e.op(op="settle_create", repo=str(e.repo), jobId=jid(2))
    assert code(res) == "git_failed" and "kept" not in res["error"]["detail"]
    assert not rec_file(e, 2).exists()


def test_collect_rejects_a_tampered_admin_dir(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    other = tmp_path / "other"
    other.mkdir()
    cases = [
        (
            1,
            lambda a: (a / "config.worktree").write_text("[core]\n\tfsmonitor = true\n"),
            "config_worktree",
        ),
        (2, lambda a: (a / "commondir").write_text(f"{other}\n"), "commondir_mismatch"),
        (3, lambda a: (a / "gitdir").write_text("/nonexistent/.git\n"), "gitdir_mismatch"),
        (4, lambda a: (a / "config").write_text("[core]\n"), "unexpected_entry:config"),
    ]
    for n, tamper, violation in cases:
        rec = e.create(n)
        child_edit(Path(rec["worktree"]))
        tamper(admin_dir(e, n))
        res = e.collect(n)
        assert code(res) == "collect_failed", res
        detail = res["error"]["detail"]
        assert detail["stage"] == "admin" and detail["causeDetail"]["violation"] == violation
        assert load_rec(e, n)["state"] == "kept"
        assert not ref_exists(e, f"refs/pi-agent/{jid(n)}")
        assert not (e.repo / ".tmp" / "subagents" / f"{jid(n)}.patch").exists()


def test_collect_rejects_unsafe_contents_of_allowed_admin_entries(tmp_path):
    e = Env(tmp_path)
    build_repo(e)

    def symlink_in_logs(a: Path) -> None:
        (a / "logs").mkdir(exist_ok=True)
        os.symlink("/nonexistent", a / "logs" / "evil")

    def fifo_in_refs(a: Path) -> None:
        (a / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        os.mkfifo(a / "refs" / "heads" / "x")

    def many_logs(a: Path) -> None:
        (a / "logs").mkdir(exist_ok=True)
        for i in range(1001):
            (a / "logs" / f"f{i}").write_text("")

    cases = [
        (1, lambda a: (a / "HEAD").write_text("ref: refs/heads/main\n"), "head_not_detached", {}),
        (2, symlink_in_logs, "symlink_in_logs", {}),
        (
            3,
            lambda a: (a / "index").write_bytes(b"x" * 100),
            "bad_size",
            {"maxAdminIndexBytes": 10},
        ),
        (4, fifo_in_refs, "entry_type:refs", {}),
        (5, many_logs, "too_many_entries", {}),
        (6, lambda a: (a / "locked").write_text("x" * 2000), "bad_size", {}),
    ]
    for n, tamper, violation, limits in cases:
        rec = e.create(n)
        child_edit(Path(rec["worktree"]))
        tamper(admin_dir(e, n))
        kw = {"limits": limits} if limits else {}
        res = e.collect(n, **kw)
        assert code(res) == "collect_failed", res
        detail = res["error"]["detail"]
        assert detail["stage"] == "admin" and detail["causeDetail"]["violation"] == violation
        assert load_rec(e, n)["state"] == "kept"
        assert not ref_exists(e, f"refs/pi-agent/{jid(n)}")
        assert not (e.repo / ".tmp" / "subagents" / f"{jid(n)}.patch").exists()


def test_user_directory_at_conventional_path_is_not_listed_or_overwritten(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    mine = e.repo / ".tmp" / "worktrees" / f"pi-agent-{jid(5)}"
    mine.mkdir()
    (mine / "mine.txt").write_text("x")
    issues = e.op(op="reconcile", repo=str(e.repo))
    assert all(i["jobId"] != jid(5) for i in issues)
    assert code(e.create(5)) == "bad_placement"
    assert (mine / "mine.txt").read_text() == "x" and not rec_file(e, 5).exists()


def test_global_filter_driver_is_refused(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    (e.home / ".gitconfig").write_text('[filter "x"]\n\tclean = cat\n')
    before = objects(e)
    res = e.create(1)
    assert code(res) == "filter_driver" and res["error"]["detail"]["names"] == ["x"]
    assert objects(e) == before


def test_creating_state_counts_and_is_reported_when_stale(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    e.create(1)
    data = load_rec(e, 1)
    data["state"] = "creating"
    data["createdAt"] = "2000-01-01T00:00:00.000Z"
    rec_file(e, 1).write_text(json.dumps(data))
    issues = e.op(op="reconcile", repo=str(e.repo))
    assert [(i["jobId"], i["issue"]) for i in issues] == [(jid(1), "stuck_creating")]
    res = e.create(2, limits={"maxWorktrees": 1})
    assert code(res) == "too_many" and res["error"]["detail"]["states"] == {jid(1): "creating"}
    data["createdAt"] = datetime.now(UTC).isoformat()
    rec_file(e, 1).write_text(json.dumps(data))
    assert e.op(op="reconcile", repo=str(e.repo)) == []


def test_concurrent_collect_and_discard_stay_consistent(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    child_edit(Path(rec["worktree"]))
    procs = [
        subprocess.Popen(
            e.argv(**kw),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=e.node_env,
        )
        for kw in (
            {
                "op": "collect",
                "repo": str(e.repo),
                "jobId": jid(1),
                "patchName": PATCH,
                "readDeny": NODENY,
            },
            {"op": "discard", "repo": str(e.repo), "jobId": jid(1)},
        )
    ]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err[-1500:]
        results.append(json.loads(out))
    assert all(code(r) in {"busy", "collect_failed"} for r in results if "error" in r)
    assert not (rec_file(e, 1).parent / ".lock").exists()
    if "error" not in results[1]:  # discard が実行された -> 何も残らない
        assert not Path(rec["worktree"]).exists() and not rec_file(e, 1).exists()
        assert not ref_exists(e, f"refs/pi-agent/{jid(1)}")
        assert not (e.repo / ".tmp" / "subagents" / PATCH).exists()
    else:  # discard が busy -> collect は最後まで完了している
        assert "error" not in results[0] and load_rec(e, 1)["state"] == "collected"


# ─── gitEnv ───────────────────────────────────────────────────────────────


def test_git_env_drops_git_variables_and_keeps_home(tmp_path):
    e = Env(tmp_path)
    env = e.op(
        op="gitenv", extra_env={"GIT_DIR": "/nonexistent", "GIT_FOO": "1", "GIT_INDEX_FILE": "/x"}
    )
    assert {k for k in env if k.startswith("GIT_")} == {
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_TERMINAL_PROMPT",
    }
    assert (
        env["GIT_AUTHOR_NAME"] == "pi-agent"
        and env["GIT_COMMITTER_EMAIL"] == "pi-agent@localhost.invalid"
    )
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["HOME"] == str(e.home)


# ─── markKept ───


def test_mark_kept_updates_state_and_note_and_nothing_else(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    rec = e.create(1)
    before = load_rec(e, 1)
    assert before["state"] == "running"
    out = e.op(op="mark_kept", repo=str(e.repo), jobId=jid(1), note="stop not confirmed")
    assert out["record"]["state"] == "kept" and out["record"]["note"] == "stop not confirmed"
    after = load_rec(e, 1)
    assert after["state"] == "kept" and after["note"] == "stop not confirmed"
    assert {k: v for k, v in after.items() if k not in ("state", "note")} == {
        k: v for k, v in before.items() if k not in ("state", "note")
    }
    # worktree は残し、ロックは解放する
    assert Path(rec["worktree"]).is_dir()
    assert not (rec_file(e, 1).parent / ".lock").exists()


def test_mark_kept_without_a_record_does_nothing(tmp_path):
    e = Env(tmp_path)
    build_repo(e)
    # 記録の置き場自体が無い: 何も作らない
    assert e.op(op="mark_kept", repo=str(e.repo), jobId=jid(2), note="x") == {"record": None}
    assert not (e.repo / ".tmp" / "subagents").exists()
    # 置き場はあるが、この job の記録が無い
    e.create(1)
    files = sorted(p.name for p in rec_file(e, 1).parent.iterdir())
    assert e.op(op="mark_kept", repo=str(e.repo), jobId=jid(2), note="x") == {"record": None}
    assert sorted(p.name for p in rec_file(e, 1).parent.iterdir()) == files
    assert load_rec(e, 1)["state"] == "running"
