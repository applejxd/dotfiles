"""PR ビューアのジョブの git 層（job-git.ts・job-check.ts）の試験。

実 git の使い捨てリポジトリで、起動前の検査（P2〜P4・P6）・終了後の照合（Q2）・使い捨て index での tree の構築（Q3）・
結果の検査（Q4・Q5）・commit と CAS（Q6・Q7）を固定する。反例（改ざん・敵対的なパス・巨大/バイナリ・競合）を先に置く。
pis は動かさず、pis が作業ツリーや共通 .git に書く変更を、試験が直接再現する。名前・メールは架空。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_server import APP, _commit, _git, _init

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

JOB_GIT = APP / "job-git.ts"
JOB_CHECK = APP / "job-check.ts"
BRANCH = "feature/x"
JOB_ID = "11111111-2222-4333-8444-555555555555"
BATCH_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class World:
    """基準のリポジトリ（develop）・feature/x の worktree・node の呼び出し口。"""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.repo = _init(tmp / "repo")
        _git(self.repo, "config", "user.name", "Example Dev")
        _git(self.repo, "config", "user.email", "you@example.com")
        # 準備用の素の git が背景で gc を起動して、loose object を消す競合を避ける
        _git(self.repo, "config", "gc.auto", "0")
        _git(self.repo, "config", "maintenance.auto", "false")
        _commit(
            self.repo,
            {"README.md": "base\n", "other.txt": "other\n", "src/a.txt": "a\n"},
            "base",
        )
        self.wt = tmp / "wt"
        _git(self.repo, "worktree", "add", "-q", "-b", BRANCH, str(self.wt), "develop")
        self.marker = tmp / "MARKER"  # 外部のコードが動いたら作られる

    @property
    def common(self) -> Path:
        return (self.repo / ".git").resolve()

    @property
    def admin(self) -> Path:
        return self.common / "worktrees" / "wt"

    def env(self) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def rev(self, ref: str = BRANCH) -> str:
        return _git(self.repo, "rev-parse", ref).strip()

    def js(self, body: str, arg: dict | None = None):
        """job-git.ts・job-check.ts を import する node スクリプトを実行し、return した値を JSON で受け取る。"""
        script = self.tmp / "run.mjs"
        script.write_text(
            f"""import {{ execFileSync }} from "node:child_process";
const G = await import({json.dumps(JOB_GIT.as_uri())});
const C = await import({json.dumps(JOB_CHECK.as_uri())});
const arg = JSON.parse(process.argv[2]);
const sh = (...a) => execFileSync("git", a, {{ cwd: arg.repo, encoding: "utf8" }});
const out = await (async () => {{
{body}
}})();
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                _node(),
                str(script),
                json.dumps({"repo": str(self.repo), "wt": str(self.wt), **(arg or {})}),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
            cwd=self.tmp,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def preflight(self, expect: str | None = None, protected: list[str] | None = None) -> dict:
        return self.js(
            """return await G.preflight({ repo: arg.repo, source: "feature/x", expectOid: arg.expect, protectedRefs: arg.protected });""",
            {"expect": expect or self.rev(), "protected": protected or ["develop", "main"]},
        )

    def finalize(
        self,
        started: dict,
        risk: list[str] | None = ("^docs/secret",),  # type: ignore[assignment]
        hook: str | None = None,
    ) -> dict:
        body = """
const deps = arg.hook ? { beforeUpdateRef: async () => { sh(...arg.hook); } } : undefined;
return await G.finalizeJob(arg.started.pre, arg.started.record, {
  riskPaths: arg.risk === null ? null : arg.risk.map((s) => new RegExp(s)),
  jobId: arg.jobId, batchIds: arg.batchIds,
}, deps);"""
        return self.js(
            body,
            {
                "started": started,
                "risk": None if risk is None else list(risk),
                "jobId": JOB_ID,
                "batchIds": [BATCH_ID],
                "hook": None if hook is None else json.loads(hook),
            },
        )

    def started(self) -> dict:
        r = self.preflight()
        assert r["ok"], r
        return r

    def write(self, rel: str, body: str | bytes) -> None:
        p = self.wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8", newline="\n")

    def assert_untouched(self, base: str) -> None:
        """commit されていない: feature の ref が基点のまま・外部のコードが動いていない。"""
        assert self.rev() == base
        assert not self.marker.exists()

    def evil_filter(self, path: Path) -> None:
        """clean フィルタが動いたら MARKER を作る設定（動いてはいけない）。"""
        path.write_text(f'[filter "x"]\n\tclean = touch {self.marker}\n', encoding="utf-8")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


# ---------------------------------------------------------------- 起動前の検査（P2〜P4・P6）


def test_preflight_ok_returns_pre_and_record(w):
    r = w.preflight()
    assert r["ok"], r
    pre = r["pre"]
    assert pre["baseOid"] == w.rev() and Path(pre["worktree"]) == w.wt.resolve()
    assert Path(pre["adminDir"]) == w.admin and Path(pre["gitDir"]) == w.common
    rec = r["record"]
    assert rec["refs"]["refs/heads/develop"] == w.rev("develop")
    assert rec["refs"]["refs/heads/main"] is None  # 無い保護 ref も記録する
    assert rec["pointer"] and rec["admin"]["HEAD"] and rec["attributes"] is None


def test_preflight_rejects_stale_expected_oid(w):
    r = w.preflight(expect="0" * 40)
    assert r == {"ok": False, "code": "stale_view", "reason": r["reason"]}


def test_preflight_rejects_branch_without_worktree(w):
    _git(w.repo, "branch", "feature/none", "develop")
    r = w.js(
        """return await G.preflight({ repo: arg.repo, source: "feature/none", expectOid: arg.o });""",
        {"o": w.rev("feature/none")},
    )
    assert not r["ok"] and r["code"] == "no_worktree"


@pytest.mark.parametrize(
    "source", ["feature/x; rm", "--upload-pack=x", "../x", "feature/..", "", "refs/tags/v"]
)
def test_preflight_rejects_bad_branch_names(w, source):
    r = w.js(
        """return await G.preflight({ repo: arg.repo, source: arg.s, expectOid: arg.o });""",
        {"s": source, "o": w.rev()},
    )
    assert not r["ok"] and r["code"] == "bad_request"


@pytest.mark.parametrize("how", ["modified", "untracked", "staged"])
def test_preflight_rejects_dirty_worktree(w, how):
    if how == "modified":
        w.write("README.md", "changed\n")
    elif how == "untracked":
        w.write("new.txt", "x\n")
    else:
        w.write("README.md", "changed\n")
        _git(w.wt, "add", "README.md")
    assert w.preflight()["code"] == "dirty"


@pytest.mark.parametrize(
    "name",
    ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "index.lock"],
)
def test_preflight_rejects_operation_in_progress(w, name):
    p = w.admin / name
    if name == "rebase-merge":
        p.mkdir()
    else:
        p.write_text(w.rev() + "\n", encoding="utf-8")
    assert w.preflight()["code"] == "in_progress"


def _lock(w, reason: str | None = None) -> None:
    args = ["worktree", "lock", *(["--reason", reason] if reason else []), str(w.wt)]
    _git(w.repo, *args)


def test_preflight_rejects_a_worktree_owned_by_a_live_owner(w):
    _lock(w, f"owner=worker id=w1 pid={os.getpid()} started=1")
    assert w.preflight()["code"] == "worktree_busy"


def test_preflight_rejects_a_human_lock_and_a_reasonless_lock(w):
    _lock(w, "手で守っています")
    assert w.preflight()["code"] == "worktree_busy"
    _git(w.repo, "worktree", "unlock", str(w.wt))
    _lock(w)
    assert w.preflight()["code"] == "worktree_busy"


def test_preflight_ignores_a_stale_owner_with_a_dead_pid(w):
    p = subprocess.Popen(["true"])
    p.wait()
    _lock(w, f"owner=worker id=w1 pid={p.pid} started=1")
    assert w.preflight()["ok"] is True


def test_preflight_rejects_a_process_whose_cwd_is_in_the_worktree(w):
    sub = w.wt / "sub"
    sub.mkdir()
    proc = subprocess.Popen(["sleep", "30"], cwd=sub)
    try:
        assert w.preflight()["code"] == "worktree_busy"
    finally:
        proc.kill()
        proc.wait()
    assert w.preflight()["ok"] is True


def test_preflight_rejects_external_code_in_worktree_config(w):
    w.evil_filter(w.admin / "config.worktree")
    assert w.preflight()["code"] == "external_code"
    assert not w.marker.exists()


def test_preflight_rejects_external_code_in_common_config(w):
    cfg = w.common / "config"
    cfg.write_text(
        cfg.read_text(encoding="utf-8") + '[merge "x"]\n\tdriver = touch ' + str(w.marker) + "\n",
        encoding="utf-8",
    )
    assert w.preflight()["code"] == "external_code"


def test_preflight_rejects_committed_opencode(w):
    _commit(w.wt, {".opencode/sandbox.toml": "x = 1\n"}, "feat: oc")
    assert w.preflight()["code"] == "fence_request_present"


def test_preflight_rejects_untracked_opencode_even_before_dirty(w):
    w.write(".opencode/sandbox.toml", "x = 1\n")
    assert w.preflight()["code"] == "fence_request_present"


def test_preflight_rejects_rewritten_git_pointer_without_running_evil_config(w):
    """.git ポインタを別の gitdir に向けても、そこの設定（filter）は読まない。"""
    evil = w.tmp / "evil-gitdir"
    subprocess.run(["cp", "-a", str(w.admin), str(evil)], check=True)
    w.evil_filter(evil / "config.worktree")
    (evil / "info").mkdir(exist_ok=True)
    (evil / "info" / "attributes").write_text("* filter=x\n", encoding="utf-8")
    (w.wt / ".git").write_text(f"gitdir: {evil}\n", encoding="utf-8")
    r = w.preflight()
    assert not r["ok"] and r["code"] == "tampered"
    assert not w.marker.exists()


def test_preflight_rejects_pointer_to_another_worktrees_admin(w):
    wt2 = w.tmp / "wt2"
    _git(w.repo, "worktree", "add", "-q", "-b", "feature/y", str(wt2), "develop")
    (w.wt / ".git").write_text(f"gitdir: {w.common / 'worktrees' / 'wt2'}\n", encoding="utf-8")
    assert w.preflight()["code"] == "tampered"


def test_preflight_rejects_admin_gitdir_file_rewritten(w):
    (w.admin / "gitdir").write_text(str(w.tmp / "elsewhere" / ".git") + "\n", encoding="utf-8")
    assert w.preflight()["code"] in ("no_worktree", "tampered")


# ---------------------------------------------------------------- 正常系（Q3・Q6・Q7）


def test_finalize_commits_add_modify_delete(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    w.write("README.md", "changed\n")
    w.write("docs/new.md", "new\n")
    (w.wt / "other.txt").unlink()
    res = w.finalize(started)
    assert res["state"] == "committed", res
    new = res["resultOid"]
    assert w.rev() == new != base
    assert _git(w.repo, "rev-list", "--parents", "-n", "1", new).split()[1:] == [base]
    assert {(f["path"], f["status"]) for f in res["files"]} == {
        ("README.md", "M"),
        ("docs/new.md", "A"),
        ("other.txt", "D"),
    }
    body = _git(w.repo, "log", "-1", "--format=%an <%ae>%n%B", new)
    assert body.startswith("Example Dev <you@example.com>\n")
    assert JOB_ID in body and BATCH_ID in body and "3" in body
    # worktree の index も新しい HEAD に揃い、作業ツリーはそのまま（clean）
    assert _git(w.wt, "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(w.repo, "show", f"{new}:README.md") == "changed\n"


def test_finalize_no_change(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    res = w.finalize(started)
    assert res["state"] == "no_change" and w.rev() == base


def test_finalize_ignores_a_stale_real_index(w):
    """worktree の index（pis が書き換えうる）は信用しない: index にだけ載せた変更は結果に入らない。"""
    started = w.started()
    w.write("staged-only.txt", "x\n")
    _git(w.wt, "add", "staged-only.txt")
    (w.wt / "staged-only.txt").unlink()  # index には有るが作業ツリーには無い
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "committed"
    assert [f["path"] for f in res["files"]] == ["README.md"]


def test_finalize_ignored_files_are_not_committed(w):
    started = w.started()
    w.write(".gitignore", "*.log\n")
    w.write("build.log", "x\n")
    res = w.finalize(started)
    assert res["state"] == "committed"
    assert [f["path"] for f in res["files"]] == [".gitignore"]


# ---------------------------------------------------------------- 照合 Q2（改ざんの検出）


def test_tamper_git_pointer_is_detected(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    evil = w.tmp / "evil"
    subprocess.run(["cp", "-a", str(w.admin), str(evil)], check=True)
    w.evil_filter(evil / "config.worktree")
    (w.wt / ".git").write_text(f"gitdir: {evil}\n", encoding="utf-8")
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "tampered" and "tampered" in res["reasons"]
    w.assert_untouched(base)


def test_tamper_config_worktree_filter_is_detected_and_not_run(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    w.evil_filter(w.admin / "config.worktree")
    w.write("info.txt", "x\n")
    res = w.finalize(started)
    assert res["state"] == "tampered"
    w.assert_untouched(base)


def test_tamper_head_move_is_detected(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    (w.admin / "HEAD").write_text("ref: refs/heads/develop\n", encoding="utf-8")
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "tampered"
    assert w.rev("develop") != res.get("resultOid")
    assert w.rev() == base


def test_tamper_detached_head_is_detected(w):
    started = w.started()
    (w.admin / "HEAD").write_text(w.rev("develop") + "\n", encoding="utf-8")
    assert w.finalize(started)["state"] == "tampered"


@pytest.mark.parametrize("target", ["develop", "main"])
def test_tamper_protected_ref_update_is_detected(w, target):
    started = w.started()
    base = started["pre"]["baseOid"]
    _commit(w.wt, {"x.txt": "x\n"}, "feat: x")  # feature 側に commit を作って OID を得る
    other = w.rev()
    _git(w.repo, "update-ref", f"refs/heads/{target}", other)
    _git(
        w.repo, "update-ref", f"refs/heads/{BRANCH}", base
    )  # feature は基点へ戻す（保護 ref だけが動いた状態）
    res = w.finalize(started)
    assert res["state"] == "tampered"
    assert w.rev() == base


def test_tamper_feature_ref_moved_is_detected(w):
    started = w.started()
    other = _git(w.repo, "commit-tree", "-m", "x", f"{w.rev('develop')}^{{tree}}").strip()
    _git(w.repo, "update-ref", f"refs/heads/{BRANCH}", other)
    assert w.finalize(started)["state"] == "tampered"


def _alt_branch(w: World) -> str:
    """基点と同じ OID を指す別枝 alt を作る（symref の参照先）。"""
    _git(w.repo, "branch", "alt", w.rev())
    return w.rev("alt")


def test_tamper_feature_ref_symref_is_detected(w):
    started = w.started()
    base = _alt_branch(w)
    w.write("README.md", "changed\n")
    _git(w.repo, "symbolic-ref", f"refs/heads/{BRANCH}", "refs/heads/alt")
    res = w.finalize(started)
    assert res["state"] == "tampered", res
    assert w.rev("alt") == base and w.rev("develop") == base


def test_tamper_protected_ref_symref_is_detected(w):
    started = w.started()
    base = _alt_branch(w)
    w.write("README.md", "changed\n")
    _git(w.repo, "symbolic-ref", "refs/heads/develop", "refs/heads/alt")
    res = w.finalize(started)
    assert res["state"] == "tampered", res
    assert w.rev("alt") == base


def test_symref_swapped_just_before_update_ref_does_not_move_the_target(w):
    started = w.started()
    base = _alt_branch(w)
    w.write("README.md", "changed\n")
    # 照合の後・update-ref の直前に feature を symref へ置き換える
    res = w.finalize(
        started, hook=json.dumps(["symbolic-ref", f"refs/heads/{BRANCH}", "refs/heads/alt"])
    )
    assert w.rev("alt") == base and w.rev("develop") == base, res
    assert res["state"] != "committed" or w.rev("alt") == base


def test_preflight_rejects_feature_ref_that_is_a_symref(w):
    _alt_branch(w)
    _git(w.repo, "symbolic-ref", f"refs/heads/{BRANCH}", "refs/heads/alt")
    r = w.preflight()
    assert not r["ok"], r


def test_tamper_info_attributes_is_detected(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    (w.common / "info").mkdir(exist_ok=True)
    (w.common / "info" / "attributes").write_text("* filter=x text eol=crlf\n", encoding="utf-8")
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "tampered"
    assert w.rev() == base


def test_tamper_info_exclude_is_detected(w):
    started = w.started()
    (w.common / "info").mkdir(exist_ok=True)
    (w.common / "info" / "exclude").write_text("*\n", encoding="utf-8")
    w.write("README.md", "changed\n")
    assert w.finalize(started)["state"] == "tampered"


def test_tamper_admin_commondir_is_detected(w):
    started = w.started()
    (w.admin / "commondir").write_text("../../elsewhere\n", encoding="utf-8")
    assert w.finalize(started)["state"] == "tampered"


def test_tamper_common_config_external_code_is_detected(w):
    started = w.started()
    cfg = w.common / "config"
    cfg.write_text(
        cfg.read_text(encoding="utf-8") + '[filter "y"]\n\tclean = touch ' + str(w.marker) + "\n",
        encoding="utf-8",
    )
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "tampered" and not w.marker.exists()


def test_hooks_do_not_run_on_commit(w):
    """共通 .git の hooks（Fence から書けない設計だが、置かれても）は動かさない。"""
    started = w.started()
    hooks = w.common / "hooks"
    hooks.mkdir(exist_ok=True)
    for name in ("reference-transaction", "post-checkout", "post-commit", "pre-commit"):
        h = hooks / name
        h.write_text(f"#!/bin/sh\ntouch {w.marker}\n", encoding="utf-8")
        h.chmod(0o755)
    w.write("README.md", "changed\n")
    assert w.finalize(started)["state"] == "committed"
    assert not w.marker.exists()


def test_attribute_filter_in_worktree_is_not_run_while_building_tree(w):
    """worktree の .gitattributes が filter を指しても、設定（driver）が無ければ動かない。.gitattributes の変更は needs_review。"""
    started = w.started()
    w.write(".gitattributes", "* filter=x\n")
    w.write("README.md", "changed\n")
    res = w.finalize(started)
    assert res["state"] == "needs_review" and "risk_path" in res["reasons"]
    assert not w.marker.exists()


# ---------------------------------------------------------------- Q4・Q5（実 git で作った敵対的な変更）


def _review(w: World, reasons: set[str], **kw) -> dict:
    started = w.started()
    base = started["pre"]["baseOid"]
    kw.pop("prepare")()
    res = w.finalize(started, **kw)
    assert res["state"] == "needs_review", res
    assert reasons <= set(res["reasons"]), res
    assert w.rev() == base  # commit しない
    # 作業ツリーはそのまま（自動では戻さない）
    assert _git(w.wt, "status", "--porcelain", "--untracked-files=all") != ""
    return res


def test_symlink_is_not_committed(w):
    _review(w, {"unsupported_file"}, prepare=lambda: os.symlink("/etc/passwd", w.wt / "link"))


def test_symlink_replacing_a_file_is_not_committed(w):
    def prep():
        (w.wt / "README.md").unlink()
        os.symlink("other.txt", w.wt / "README.md")

    _review(w, {"unsupported_file"}, prepare=prep)


def test_executable_bit_is_not_committed(w):
    def prep():
        w.write("run.sh", "#!/bin/sh\n")
        (w.wt / "run.sh").chmod(0o755)

    _review(w, {"unsupported_file"}, prepare=prep)


def test_mode_change_of_tracked_file_is_not_committed(w):
    _review(w, {"unsupported_file"}, prepare=lambda: (w.wt / "README.md").chmod(0o755))


def test_embedded_repo_gitlink_is_not_committed(w):
    def prep():
        sub = w.wt / "vendor" / "lib"
        sub.mkdir(parents=True)
        _git(sub, "init", "-q")
        (sub / "f").write_text("x", encoding="utf-8")
        _git(sub, "add", "f")
        _git(sub, "-c", "user.name=a", "-c", "user.email=a@example.com", "commit", "-q", "-m", "x")

    _review(w, {"unsupported_file"}, prepare=prep)


def test_gitmodules_is_not_committed(w):
    _review(
        w,
        {"unsupported_file"},
        prepare=lambda: w.write(".gitmodules", '[submodule "a"]\n\tpath = a\n\turl = ../a\n'),
    )


@pytest.mark.parametrize("name", ["a\tb.txt", "a\nb.txt", "a\x1bb.txt", "a\x7fb.txt"])
def test_control_character_path_is_not_committed(w, name):
    _review(w, {"unsupported_file"}, prepare=lambda: w.write(name, "x\n"))


def test_nested_dot_git_named_directory_is_not_committed(w):
    """`.GIT` 相当の名前は、git の add が拒否する（取り込めず failed）か、許可しない名前として拒否される。commit はしない。"""
    started = w.started()
    base = started["pre"]["baseOid"]
    w.write("sub/.GIT/config", "[core]\n")
    res = w.finalize(started)
    assert res["state"] in ("needs_review", "failed"), res
    w.assert_untouched(base)


def test_too_many_files(w):
    def prep():
        for i in range(201):
            w.write(f"many/f{i}.txt", f"{i}\n")

    _review(w, {"too_many_files"}, prepare=prep)


def test_single_large_file(w):
    _review(w, {"too_large"}, prepare=lambda: w.write("big.txt", "x" * (1024 * 1024 + 1)))


def test_total_size_over_limit(w):
    def prep():
        for i in range(5):
            w.write(f"part{i}.txt", chr(97 + i) * (900 * 1024))

    _review(w, {"too_large"}, prepare=prep)


def test_exactly_at_the_size_limit_is_allowed(w):
    started = w.started()
    w.write("edge.txt", "x" * (1024 * 1024))
    res = w.finalize(started)
    assert res["state"] == "committed", res


def test_binary_file(w):
    _review(w, {"binary"}, prepare=lambda: w.write("img.dat", b"\x00\x01\x02binary\x00"))


def test_risk_path_match_needs_review(w):
    _review(w, {"risk_path"}, prepare=lambda: w.write("docs/secret/a.md", "x\n"))


def test_risk_config_unavailable_needs_review(w):
    _review(w, {"risk_config"}, prepare=lambda: w.write("docs/ok.md", "x\n"), risk=None)


def test_opencode_created_during_job_needs_review(w):
    _review(w, {"risk_path"}, prepare=lambda: w.write(".opencode/sandbox.toml", "x = 1\n"))


def test_nested_gitattributes_needs_review(w):
    _review(w, {"risk_path"}, prepare=lambda: w.write("sub/.gitattributes", "* text\n"))


def test_one_bad_file_blocks_the_whole_commit(w):
    def prep():
        w.write("fine.txt", "ok\n")
        os.symlink("x", w.wt / "link")

    _review(w, {"unsupported_file"}, prepare=prep)


# ---------------------------------------------------------------- Q4 の純粋関数


def _check(w: World, raw: str, **kw) -> dict:
    return w.js(
        """const e = C.parseRaw(arg.raw);
if (e === null) return null;
return C.checkChanges({
  entries: e, sizes: arg.sizes, binaryPaths: arg.bin,
  riskPaths: arg.risk === null ? null : arg.risk.map((s) => new RegExp(s)),
});""",
        {
            "raw": raw,
            "sizes": kw.get("sizes", {}),
            "bin": kw.get("bin", []),
            "risk": kw.get("risk", []),
        },
    )


OID_A = "a" * 40
OID_B = "b" * 40
ZERO = "0" * 40


def _raw(*entries: tuple[str, str, str, str]) -> str:
    """(旧モード, 新モード, 状態, パス) の列 → diff-tree の -z 出力。"""
    out = ""
    for om, nm, st, path in entries:
        oo = ZERO if om == "000000" else OID_A
        no = ZERO if nm == "000000" else OID_B
        out += f":{om} {nm} {oo} {no} {st}\0{path}\0"
    return out


def test_check_accepts_regular_changes(w):
    r = _check(
        w,
        _raw(
            ("000000", "100644", "A", "a.txt"),
            ("100644", "100644", "M", "b/c.txt"),
            ("100644", "000000", "D", "d.txt"),
        ),
        sizes={OID_B: 10},
    )
    assert r["verdict"] == "commit" and r["reasons"] == [] and len(r["files"]) == 3


@pytest.mark.parametrize(
    "entry",
    [
        ("000000", "120000", "A", "l"),
        ("000000", "160000", "A", "g"),
        ("000000", "100755", "A", "x"),
        ("100644", "100755", "M", "x"),
        ("100644", "120000", "T", "x"),
        ("100755", "000000", "D", "x"),
        ("120000", "000000", "D", "x"),
    ],
)
def test_check_rejects_unsupported_types(w, entry):
    r = _check(w, _raw(entry), sizes={OID_B: 1})
    assert r["verdict"] == "needs_review" and "unsupported_file" in r["reasons"]


@pytest.mark.parametrize(
    "path,reason",
    [
        (".git/config", "unsupported_file"),
        ("a/.git", "unsupported_file"),
        ("a/.GIT/x", "unsupported_file"),
        ("a/.git./x", "unsupported_file"),
        ("a/GIT~1/x", "unsupported_file"),
        (".gitmodules", "unsupported_file"),
        ("x/.GitModules", "unsupported_file"),
        ("a\x01b", "unsupported_file"),
        ("a" * 4097, "unsupported_file"),
        ("あ" * 1366, "unsupported_file"),  # 4098 バイト
        ("/etc/passwd", "outside"),
        ("../x", "outside"),
        ("a/../x", "outside"),
        ("a\\b", "outside"),
        ("C:/x", "outside"),
        ("a//b", "unsupported_file"),
        ("a/\ufffd", "unsupported_file"),
    ],
)
def test_check_rejects_adversarial_paths(w, path, reason):
    r = _check(w, _raw(("000000", "100644", "A", path)), sizes={OID_B: 1})
    assert r["verdict"] == "needs_review" and reason in r["reasons"], r


def test_check_path_boundaries_are_allowed(w):
    ok = ["a" * 4096, "あ" * 1365, ".gitignore", ".github/x.yml", "gitx/y", "a.git/x", "a/b.git"]
    for p in ok:
        r = _check(w, _raw(("000000", "100644", "A", p)), sizes={OID_B: 1})
        assert r["verdict"] == "commit", (p[:20], r)


def test_check_missing_size_is_treated_as_too_large(w):
    r = _check(w, _raw(("000000", "100644", "A", "a.txt")))
    assert "too_large" in r["reasons"]


def test_check_counts_and_size_limits(w):
    many = _raw(*[("000000", "100644", "A", f"f{i}") for i in range(201)])
    assert "too_many_files" in _check(w, many, sizes={OID_B: 1})["reasons"]
    r200 = _raw(*[("000000", "100644", "A", f"f{i}") for i in range(200)])
    assert _check(w, r200, sizes={OID_B: 1})["verdict"] == "commit"
    two = _raw(("000000", "100644", "A", "a"), ("100644", "100644", "M", "b"))
    # 同じ OID は 2 回数える（4 MiB 以内なら通る・超えたら too_large）
    assert _check(w, two, sizes={OID_B: 1024 * 1024})["verdict"] == "commit"
    assert _check(w, two, sizes={OID_B: 1024 * 1024 + 1})["verdict"] == "needs_review"
    five = _raw(*[("000000", "100644", "A", f"f{i}") for i in range(5)])
    assert "too_large" in _check(w, five, sizes={OID_B: 900 * 1024})["reasons"]


def test_check_binary_and_risk(w):
    r = _check(w, _raw(("000000", "100644", "A", "a.bin")), sizes={OID_B: 1}, bin=["a.bin"])
    assert "binary" in r["reasons"]
    r = _check(w, _raw(("000000", "100644", "A", "x/risky.txt")), sizes={OID_B: 1}, risk=[r"risky"])
    assert r["reasons"] == ["risk_path"]
    r = _check(w, _raw(("000000", "100644", "A", "a.txt")), sizes={OID_B: 1}, risk=None)
    assert r["reasons"] == ["risk_config"]


def test_parse_raw_rejects_malformed_output(w):
    for raw in [
        ":100644 100644 aaa bbb M\0",
        "garbage\0x\0",
        ":100644 100644 aaa bbb\0x\0",
        ":1 2 3 4 M\0x\0",
    ]:
        assert w.js("return C.parseRaw(arg.raw);", {"raw": raw}) is None, raw


def test_parse_numstat_binary(w):
    out = "-\t-\tbin.dat\0" + "1\t2\ttext.txt\0" + "-\t-\ta b\tc\0"
    assert w.js("return [...C.parseNumstatBinary(arg.out)];", {"out": out}) == ["bin.dat", "a b\tc"]
    assert w.js("return C.parseNumstatBinary(arg.out);", {"out": "oops\0"}) is None


# ---------------------------------------------------------------- Q6・Q7（CAS）


def test_cas_conflict_does_not_overwrite_a_moved_ref(w):
    started = w.started()
    base = started["pre"]["baseOid"]
    w.write("README.md", "changed\n")
    # update-ref の直前に、別の誰かが feature を進める
    other = _git(
        w.repo, "commit-tree", "-m", "someone else", f"{base}^{{tree}}", "-p", base
    ).strip()
    res = w.finalize(started, hook=json.dumps(["update-ref", f"refs/heads/{BRANCH}", other, base]))
    assert res["state"] == "failed" and "ref_moved" in res["reasons"], res
    assert w.rev() == other  # 競合した相手の更新を残す
    # 作業ツリーは reset されず、変更が残る
    assert (w.wt / "README.md").read_text(encoding="utf-8") == "changed\n"


def test_second_finalize_after_commit_is_a_cas_failure_not_a_second_commit(w):
    started = w.started()
    w.write("README.md", "changed\n")
    first = w.finalize(started)
    assert first["state"] == "committed"
    w.write("README.md", "changed again\n")
    second = w.finalize(started)  # 古い基点での再実行。ref は進んでいる
    assert second["state"] in ("tampered", "failed")
    assert w.rev() == first["resultOid"]


# ---------------------------------------------------------------- 構造


def test_job_git_reuses_run_git_and_has_no_own_executor():
    src = JOB_GIT.read_text(encoding="utf-8")
    assert re.search(r'from "\./merge-git\.ts"', src)
    assert "child_process" not in src and "spawn(" not in src
    assert not re.search(r"(?<![.\w])exec(?:Sync|File)?\(", src)
    chk = JOB_CHECK.read_text(encoding="utf-8")
    assert not re.search(r"^import ", chk, re.M)  # 純粋関数。依存を持たない
