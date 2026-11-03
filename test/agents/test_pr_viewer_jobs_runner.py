"""PR ビューアのジョブの実行器（job-runner.ts）の試験。

偽の pis（pr_viewer_fixtures/fake_pis.py）と実 git の使い捨てリポジトリ・worktree で、起動の形（argv・cwd・環境・プロセスグループ）・
正常 commit・各失敗・時間切れ・キャンセル・取り残しの掃除・アプリ停止（shutdown と SIGTERM）を固定する。反例（環境の漏れ・
出力の暴走・SIGTERM を無視する子・改ざん）を先に置く。本物の LLM・pis は呼ばない。名前・メールは架空。Linux 専用（/proc）。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_pi_judge_ts import _node
from test_pr_viewer_server import APP, _commit, _git, _init

pytestmark = [
    pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い"),
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc を使う（Linux 専用）"),
]

FAKE = Path(__file__).parent / "pr_viewer_fixtures" / "fake_pis.py"
JOB_GIT = APP / "job-git.ts"
JOB_STORE = APP / "job-store.ts"
JOB_RUNNER = APP / "job-runner.ts"
BRANCH = "feature/x"
BATCH_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
REPO_ID = "r12345678"
PROMPT = "コメントに対応してください"

SCRIPT = """import fs from "node:fs";
import {{ execFileSync }} from "node:child_process";
const G = await import({git});
const S = await import({store});
const R = await import({runner});
const arg = JSON.parse(process.argv[2]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const t0 = Date.now();
let extra = {{}};
let finalizeDeps;
const store = S.openStore(arg.state, arg.repoId);
const pf = await G.preflight({{ repo: arg.repo, source: "feature/x", expectOid: arg.expect, protectedRefs: ["develop", "main"] }});
if (!pf.ok) throw new Error("preflight: " + JSON.stringify(pf));
const job = S.createJob(store, {{ kind: "address_review", branch: "feature/x", baseOid: pf.pre.baseOid, batchIds: [arg.batch] }});
if (!S.acquireLock(store, "feature/x", job.id).ok) throw new Error("lock");
S.writePrompt(store, job.id, arg.prompt);
const waitLog = async (text, ms = 8000) => {{
  const end = Date.now() + ms;
  while (Date.now() < end) {{
    if (S.readLog(store, job.id, 0).text.includes(text)) return true;
    await sleep(20);
  }}
  return false;
}};
{pre}
const h = R.runJob({{
  store, job, pre: pf.pre, record: pf.record, pisCommand: arg.pis,
  argvTail: {{ prompt: arg.prompt, model: arg.model }},
  timeoutMs: arg.timeoutMs, outputLimitBytes: arg.limit, riskPaths: [/^docs\\/secret/],
  deps: {{ graceMs: arg.grace, drainMs: arg.drain, env: {{ ...process.env, ...arg.extraEnv }}, finalize: finalizeDeps }},
}});
{body}
const rec = await h.done;
console.log(JSON.stringify({{ job: rec, elapsed: Date.now() - t0, extra, locks: fs.readdirSync(store.locksDir) }}));
"""


def alive(pid: int) -> bool:
    """生きているか（ゾンビは死んだ扱い）。"""
    try:
        os.kill(pid, 0)
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (ProcessLookupError, FileNotFoundError, PermissionError):
        return False
    return state != "Z"


def wait_dead(pids: list[int], secs: float = 3.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if not any(alive(p) for p in pids):
            return True
        time.sleep(0.05)
    return not any(alive(p) for p in pids)


class World:
    """基準のリポジトリ（develop）・feature/x の worktree・偽の pis・node の呼び出し口。"""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp.resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.repo = _init(self.tmp / "repo")
        _git(self.repo, "config", "user.name", "Example Dev")
        _git(self.repo, "config", "user.email", "you@example.com")
        _git(self.repo, "config", "gc.auto", "0")
        _git(self.repo, "config", "maintenance.auto", "false")
        _commit(self.repo, {"README.md": "base\n", "src/a.txt": "a\n"}, "base")
        self.wt = self.tmp / "wt"
        _git(self.repo, "worktree", "add", "-q", "-b", BRANCH, str(self.wt), "develop")
        self.state = self.tmp / "state"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.pis = self.bin / "pis"
        self.sidecar = self.bin / "pis.json"
        self.record_path = self.bin / "pis.json.record.json"
        # 先頭に shebang を持つ python の薄い起動役（sh を挟むと PWD などが環境に足されるため）
        self.pis.write_text(
            f"#!{sys.executable}\nimport os, sys\n"
            f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, {str(self.sidecar)!r}, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        self.pis.chmod(0o755)
        self.mode("noop")

    @property
    def common(self) -> Path:
        return (self.repo / ".git").resolve()

    def mode(self, mode: str, **kw) -> None:
        self.sidecar.write_text(json.dumps({"mode": mode, **kw}), encoding="utf-8")

    def record(self) -> dict:
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    def rev(self, ref: str = BRANCH) -> str:
        return _git(self.repo, "rev-parse", ref).strip()

    def env(self) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def args(self, **kw) -> dict:
        base = {
            "repo": str(self.repo),
            "state": str(self.state),
            "repoId": REPO_ID,
            "expect": self.rev(),
            "pis": str(self.pis),
            "prompt": PROMPT,
            "model": None,
            "timeoutMs": 20000,
            "limit": 8 * 1024 * 1024,
            "grace": 300,
            "drain": 300,
            "batch": BATCH_ID,
            "extraEnv": {},
        }
        return {**base, **kw}

    def script(self, pre: str = "", body: str = "") -> Path:
        path = self.tmp / "run.mjs"
        path.write_text(
            SCRIPT.format(
                git=json.dumps(JOB_GIT.as_uri()),
                store=json.dumps(JOB_STORE.as_uri()),
                runner=json.dumps(JOB_RUNNER.as_uri()),
                pre=pre,
                body=body,
            ),
            encoding="utf-8",
        )
        return path

    def run(self, pre: str = "", body: str = "", **kw) -> dict:
        path = self.script(pre, body)
        proc = subprocess.run(
            [_node(), str(path), json.dumps(self.args(**kw))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
            cwd=self.tmp,
            check=False,
            timeout=90,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def popen(self, pre: str = "", body: str = "", **kw) -> subprocess.Popen:
        path = self.script(pre, body)
        return subprocess.Popen(
            [_node(), str(path), json.dumps(self.args(**kw))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self.env(),
            cwd=self.tmp,
        )

    def wt_status(self) -> str:
        return _git(self.wt, "status", "--porcelain", "--untracked-files=all")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def _wait_file(p: Path, secs: float = 10.0) -> None:
    end = time.time() + secs
    while time.time() < end and not p.exists():
        time.sleep(0.02)
    assert p.exists(), p


# ---- 正常系と起動の形 ----


def test_edit_is_committed_by_the_app(w):
    base = w.rev()
    w.mode("edit")
    res = w.run()
    job = res["job"]
    assert job["state"] == "succeeded", job
    assert job["exitCode"] == 0 and job["reasons"] == []
    assert job["resultOid"] == w.rev() != base
    assert {(f["path"], f["status"]) for f in job["files"]} == {
        ("src/a.txt", "M"),
        ("docs/new.txt", "A"),
    }
    assert _git(w.repo, "rev-parse", f"{BRANCH}~1").strip() == base
    assert w.wt_status() == ""  # index も新しい HEAD に揃う
    assert res["locks"] == []  # 排他は解除済み
    assert job["endedAt"] and job["startedAt"] and job["pid"]
    assert w.rev("develop") == base  # 保護 ref は動かない


def test_noop_is_no_change(w):
    base = w.rev()
    res = w.run()
    job = res["job"]
    assert job["state"] == "no_change" and job["resultOid"] is None and job["exitCode"] == 0
    assert w.rev() == base and res["locks"] == []


def test_argv_is_fixed_and_process_is_isolated(w):
    w.run()
    rec = w.record()
    assert rec["argv"] == ["--role", "worker", "--allowlist", "-p", PROMPT]
    assert rec["cwd"] == str(w.wt)
    assert rec["pgid"] == rec["pid"]  # 新しいプロセスグループ（detached）
    assert rec["stdin_is_null"] is True


def test_model_goes_before_the_prompt(w):
    w.run(model="github-copilot/claude-sonnet-5.5")
    assert w.record()["argv"] == [
        "--role", "worker", "--allowlist", "-p", "--model", "github-copilot/claude-sonnet-5.5", PROMPT,
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("kw", "label"),
    [
        ({"model": "x"}, "スラッシュ無し"),
        ({"model": "a b/c"}, "空白"),
        ({"model": "a/b c"}, "空白"),
        ({"model": "a/b/c"}, "スラッシュが 2 つ"),
        ({"model": "a/b\n"}, "末尾の改行"),
        ({"model": ""}, "空"),
        ({"model": "-x/y"}, "先頭が - で旗に見える"),
        ({"model": "--model/y"}, "先頭が -- で旗に見える"),
        ({"prompt": "--help"}, "プロンプトがフラグに見える"),
        ({"prompt": ""}, "空のプロンプト"),
    ],
)
def test_bad_argv_is_refused_before_spawn(w, kw, label):
    res = w.run(**kw)
    assert res["job"]["state"] == "failed" and res["job"]["reasons"] == ["bad_argv"], label
    assert not w.record_path.exists()  # pis は起動していない
    assert res["locks"] == []


def test_env_is_an_allowlist(w):
    extra = {
        "GIT_PAGER": "evil",
        "GIT_SSH_COMMAND": "evil",
        "GIT_DIR": "/nonexistent",
        "GIT_CONFIG_COUNT": "1",
        "PIS_EXTRA_ARGS": "--no-sandbox",
        "PIS_EXTRA_RO": "/",
        "GITHUB_TOKEN": "ghp_secret",
        "OPENAI_API_KEY": "sk-secret",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "USER": "tester",
        "XDG_CONFIG_HOME": "/x/config",
        "XDG_STATE_HOME": "/x/state",
        "HTTPS_PROXY": "http://proxy.invalid:3128",
        "no_proxy": "localhost",
        "SSL_CERT_FILE": "/x/ca.pem",
        "PI_CODING_AGENT_DIR": "/x/agent",
        "PR_VIEWER_JOB_ID": "spoofed",  # 偽の印は上書きされる
    }
    res = w.run(extraEnv=extra)
    env = w.record()["env"]
    for k in (
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "HTTPS_PROXY",
        "no_proxy",
    ):
        assert env[k] == (extra.get(k) or env[k]), k
    for k in ("SSL_CERT_FILE", "PI_CODING_AGENT_DIR"):
        assert env[k] == extra[k]
    assert env["PR_VIEWER_JOB_ID"] == res["job"]["id"]
    assert env["TERM"] == "dumb" and env["NO_COLOR"] == "1"
    for k in (
        "GIT_PAGER",
        "GIT_SSH_COMMAND",
        "GIT_DIR",
        "GIT_CONFIG_COUNT",
        "PIS_EXTRA_ARGS",
        "PIS_EXTRA_RO",
    ):
        assert k not in env, k
    for k in ("GITHUB_TOKEN", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"):
        assert k not in env, k
    import re

    allowed = [
        r"PATH|HOME|USER|LANG|SSL_CERT_FILE|PI_CODING_AGENT_DIR|PR_VIEWER_JOB_ID|TERM|NO_COLOR",
        r"LC_.*",
        r"XDG_.*",
        r"(?i).*_PROXY",
    ]
    stray = [k for k in env if not any(re.fullmatch(p, k) for p in allowed)]
    assert stray == [], stray


# ---- 失敗 ----


def test_nonzero_exit_fails_without_commit(w):
    base = w.rev()
    w.mode("fail")
    res = w.run()
    job = res["job"]
    assert job["state"] == "failed" and job["reasons"] == ["exit_nonzero"] and job["exitCode"] == 3
    assert w.rev() == base  # commit しない
    assert "docs/new.txt" in w.wt_status()  # 作業ツリーは自動で戻さない
    assert res["locks"] == []


def test_spawn_failure(w):
    res = w.run(pis=str(w.tmp / "no-such-pis"))
    assert res["job"]["state"] == "failed" and res["job"]["reasons"] == ["spawn_failed"]
    assert res["locks"] == []


def test_relative_pis_command_is_refused(w):
    res = w.run(pis="pis")
    assert res["job"]["state"] == "failed" and res["job"]["reasons"] == ["spawn_failed"]
    assert not w.record_path.exists()


def test_pis_not_executable_is_spawn_failed(w):
    w.pis.chmod(0o644)
    res = w.run()
    assert res["job"]["state"] == "failed" and res["job"]["reasons"] == ["spawn_failed"]


def test_output_flood_is_killed_with_output_limit(w):
    base = w.rev()
    w.mode("flood")
    res = w.run(limit=2 * 1024 * 1024)
    job = res["job"]
    assert job["state"] == "failed" and job["reasons"] == ["output_limit"], job
    assert res["elapsed"] < 15000
    assert wait_dead([w.record()["pid"]])
    log = w.state / REPO_ID / "jobs" / job["id"] / "log.txt"
    assert log.stat().st_size <= 1024 * 1024 + 4096  # ログは先頭 1 MiB だけ
    assert w.rev() == base


# ---- 時間切れ・キャンセル・掃除 ----


def test_timeout_kills_a_pis_that_ignores_sigterm_and_all_descendants(w):
    base = w.rev()
    w.mode("slow", children=True)
    res = w.run(timeoutMs=700, grace=400)
    job = res["job"]
    assert job["state"] == "timed_out" and job["reasons"] == ["timeout"], job
    rec = w.record()
    assert res["elapsed"] >= 700 + 300  # SIGTERM を無視したので、猶予の後に SIGKILL
    assert wait_dead([rec["pid"], *rec["children"]])  # setsid で抜けた子も止まる
    assert w.rev() == base and res["locks"] == []


def test_timeout_with_sigterm_aware_pis_stops_fast(w):
    w.mode("hang")
    res = w.run(timeoutMs=500, grace=10000)
    assert res["job"]["state"] == "timed_out"
    assert w.record()["signals"] == [signal.SIGTERM]  # まず SIGTERM
    assert res["elapsed"] < 5000  # 猶予を使い切らない


def test_cancel_sends_sigterm_to_the_group(w):
    w.mode("hang")
    res = w.run(
        body='await waitLog("hang started"); extra.ok = h.cancel(); extra.again = h.cancel();',
        grace=10000,
    )
    assert res["extra"] == {"ok": True, "again": True}
    assert res["job"]["state"] == "cancelled" and res["job"]["reasons"] == ["cancelled"]
    assert w.record()["signals"] == [signal.SIGTERM]
    assert res["locks"] == []


def test_cancel_kills_stubborn_descendants(w):
    w.mode("slow", children=True)
    res = w.run(body='await waitLog("slow started"); h.cancel();', grace=300)
    assert res["job"]["state"] == "cancelled"
    rec = w.record()
    assert wait_dead([rec["pid"], *rec["children"]])


def test_cancel_is_refused_while_finalizing(w):
    w.mode("edit")
    pre = "finalizeDeps = { beforeUpdateRef: async () => { extra.cancelDuring = h.cancel(); await sleep(200); } };"
    res = w.run(pre=pre)
    assert res["extra"]["cancelDuring"] is False
    assert res["job"]["state"] == "succeeded"  # finalizing は止めない
    assert w.rev() == res["job"]["resultOid"]


def test_cancel_after_done_is_false(w):
    res = w.run(body="await h.done; extra.late = h.cancel();")
    assert res["extra"]["late"] is False and res["job"]["state"] == "no_change"


def test_leftover_descendants_are_killed_after_normal_exit(w):
    other = subprocess.Popen(
        ["sleep", "300"],
        start_new_session=True,
        env={**os.environ, "PR_VIEWER_JOB_ID": "other-job"},
    )
    try:
        w.mode("leftover")
        res = w.run()
        assert res["job"]["state"] == "succeeded"
        rec = w.record()
        assert wait_dead(rec["children"])  # 検査の前に掃除される
        assert alive(other.pid)  # 別のジョブの印を持つものは触らない
    finally:
        other.kill()
        other.wait()


def _unmarked_sleeper(cwd: Path) -> subprocess.Popen:
    """印なし・別セッションで、cwd を指定した sleep（無関係なプロセスの代用）。"""
    env = {k: v for k, v in os.environ.items() if k != "PR_VIEWER_JOB_ID"}
    return subprocess.Popen(["sleep", "300"], cwd=cwd, start_new_session=True, env=env)


def test_unmarked_descendant_in_the_worktree_is_killed_but_lookalikes_are_not(w):
    near = w.tmp / "wt2"  # 接頭辞が似た別の作業場所（wt と取り違えない）
    near.mkdir()
    outside = w.tmp / "elsewhere"
    outside.mkdir()
    decoys = [_unmarked_sleeper(near), _unmarked_sleeper(outside)]
    try:
        w.mode("leftover_unmarked")
        res = w.run()
        assert res["job"]["state"] == "succeeded"
        assert wait_dead(w.record()["children"])  # 印がなくても cwd が worktree の子孫は止まる
        assert res["elapsed"] < 8000  # 消えればポーリングを打ち切る（上限 10 秒を使わない）
        assert all(alive(p.pid) for p in decoys)  # wt2 と外は止めない
    finally:
        for p in decoys:
            p.kill()
            p.wait()


def test_confirm_wait_is_bounded_and_does_not_block_when_nothing_remains(w):
    # 即時に消えるものしか無いとき、消滅確認の待ち（既定 10 秒）を使わない
    w.mode("noop")
    res = w.run()
    assert res["job"]["state"] == "no_change" and res["elapsed"] < 8000


# ---- 検査の結果（commit しない経路） ----


def test_outside_write_is_not_committed(w):
    target = w.tmp / "outside.txt"
    w.mode("outside", target=str(target))
    res = w.run()
    assert res["job"]["state"] == "succeeded"
    assert (
        target.exists()
    )  # 外への書き込み自体は runner では防げない（sandbox の領分）。commit には入らない
    tree = _git(w.repo, "ls-tree", "-r", "--name-only", BRANCH).split()
    assert "outside.txt" not in tree and sorted(f["path"] for f in res["job"]["files"]) == [
        "docs/new.txt",
        "src/a.txt",
    ]


@pytest.mark.parametrize(
    ("kw", "expect"),
    [
        ({"mode": "risk"}, "risk_path"),
        ({"mode": "binary"}, "binary"),
        ({"mode": "symlink"}, "unsupported_file"),
    ],
)
def test_risky_results_need_review_and_are_not_committed(w, kw, expect):
    base = w.rev()
    w.mode(**kw)
    res = w.run()
    job = res["job"]
    assert job["state"] == "needs_review" and expect in job["reasons"], job
    assert job["resultOid"] is None and w.rev() == base
    assert w.wt_status() != ""  # 作業ツリーは残す
    assert res["locks"] == []


def test_tamper_git_pointer(w):
    base = w.rev()
    w.mode("tamper", what="pointer")
    job = w.run()["job"]
    assert job["state"] == "failed" and "tampered" in job["reasons"], job
    assert w.rev() == base and job["resultOid"] is None


def test_tamper_protected_ref(w):
    base = w.rev()
    develop = w.rev("develop")
    # develop を feature と違う場所へ動かす（feature に 1 コミット足した後の OID）
    _git(w.repo, "branch", "other", "develop")
    _commit_on_other = w.tmp / "other"
    _git(w.repo, "worktree", "add", "-q", str(_commit_on_other), "other")
    (_commit_on_other / "z.txt").write_text("z\n", encoding="utf-8")
    _git(_commit_on_other, "add", "-A")
    _git(
        _commit_on_other,
        "-c",
        "user.name=Example Dev",
        "-c",
        "user.email=you@example.com",
        "commit",
        "-q",
        "-m",
        "z",
    )
    moved = _git(w.repo, "rev-parse", "other").strip()
    w.mode("tamper", what="ref", common=str(w.common), oid=moved)
    job = w.run(expect=base)["job"]
    assert job["state"] == "failed" and "tampered" in job["reasons"], job
    assert w.rev() == base and w.rev("develop") == moved != develop


def test_tamper_head(w):
    base = w.rev()
    w.mode("tamper", what="head", admin=str(w.common / "worktrees" / "wt"))
    job = w.run()["job"]
    assert job["state"] == "failed" and "tampered" in job["reasons"], job
    assert w.rev() == base


# ---- アプリの停止 ----


def test_shutdown_interrupts_and_kills_running_job(w):
    w.mode("slow", children=True)
    res = w.run(
        body='await waitLog("slow started"); await R.shutdown(); extra.after = S.readJob(store, job.id).state;',
        grace=300,
    )
    assert res["extra"]["after"] == "interrupted"  # shutdown の解決時には終端が書かれている
    assert res["job"]["state"] == "interrupted" and res["job"]["reasons"] == ["shutdown"]
    rec = w.record()
    assert wait_dead([rec["pid"], *rec["children"]])
    assert res["locks"] == []


def test_shutdown_waits_for_finalizing(w):
    w.mode("edit")
    pre = (
        "finalizeDeps = { beforeUpdateRef: async () => {"
        " extra.sd = R.shutdown().then(() => { extra.sdDone = Date.now(); });"
        " await sleep(500); extra.hookEnd = Date.now(); } };"
    )
    res = w.run(pre=pre, body="")
    assert res["job"]["state"] == "succeeded", res["job"]  # kill せず最後まで待つ
    assert w.rev() == res["job"]["resultOid"]


def test_sigterm_interrupts_running_job(w):
    w.mode("slow", children=True)
    ready = w.tmp / "ready"
    body = (
        'process.on("SIGTERM", () => { R.shutdown(); });'
        ' await waitLog("slow started"); fs.writeFileSync(arg.ready, "1");'
    )
    proc = w.popen(body=body, ready=str(ready), grace=300)
    try:
        _wait_file(ready)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err
    res = json.loads(out.strip().splitlines()[-1])
    assert res["job"]["state"] == "interrupted" and res["job"]["reasons"] == ["shutdown"]
    rec = w.record()
    assert wait_dead([rec["pid"], *rec["children"]])
    assert res["locks"] == []


def test_sigterm_during_finalizing_still_commits(w):
    w.mode("edit")
    ready = w.tmp / "ready"
    pre = "finalizeDeps = { beforeUpdateRef: async () => { fs.writeFileSync(arg.ready, '1'); await sleep(1500); } };"
    body = 'process.on("SIGTERM", () => { R.shutdown(); });'
    proc = w.popen(pre=pre, body=body, ready=str(ready))
    try:
        _wait_file(ready)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, err
    res = json.loads(out.strip().splitlines()[-1])
    assert res["job"]["state"] == "succeeded", res["job"]  # finalizing は待って、commit を完了する
    assert w.rev() == res["job"]["resultOid"]
    assert res["locks"] == []


def test_job_json_is_terminal_on_disk(w):
    w.mode("edit")
    res = w.run()
    on_disk = json.loads(
        (w.state / REPO_ID / "jobs" / res["job"]["id"] / "job.json").read_text(encoding="utf-8")
    )
    assert on_disk["state"] == "succeeded" and on_disk["resultOid"] == w.rev()
    assert (w.state / REPO_ID / "jobs" / res["job"]["id"] / "prompt.txt").read_text(
        encoding="utf-8"
    ) == PROMPT


def test_runner_imports_are_node_builtins_and_local_only():
    import re

    src = JOB_RUNNER.read_text(encoding="utf-8")
    for spec in re.findall(r'from "([^"]+)"', src):
        assert spec.startswith(("node:", "./")), spec


# ---- worktree の所有の表明（git worktree lock。scripts/wt_owner.py と同じ規則） ----

_WT_LIST = 'execFileSync("git", ["-C", arg.repo, "worktree", "list", "--porcelain"], {{ encoding: "utf8" }})'


def _lock_reason(w: World) -> str | None:
    cur = None
    for line in _git(w.repo, "worktree", "list", "--porcelain", "-z").split("\0"):
        if line.startswith("worktree "):
            cur = Path(line[9:]).resolve()
        elif cur == w.wt.resolve() and (line == "locked" or line.startswith("locked ")):
            return line[6:].strip()
    return None


def test_job_claims_the_worktree_while_running_and_releases_it_after(w):
    w.mode("slow")
    body = f'await waitLog("slow started");\nextra.during = {_WT_LIST.format()};\nh.cancel();'
    res = w.run(body=body)
    job = res["job"]
    assert f"locked owner=job id={job['id']} pid=" in res["extra"]["during"]
    assert job["state"] == "cancelled"
    assert _lock_reason(w) is None  # 終了後に lock が残らない


def test_job_releases_the_lock_after_success_and_failure(w):
    w.mode("edit")
    assert w.run()["job"]["state"] == "succeeded"
    assert _lock_reason(w) is None
    w.mode("fail")
    assert w.run()["job"]["state"] == "failed"
    assert _lock_reason(w) is None


def test_job_is_refused_when_another_live_owner_took_the_worktree(w):
    other = f"owner=worker id=w1 pid={os.getpid()} started=1"
    pre = (
        'execFileSync("git", ["-C", arg.repo, "worktree", "lock", "--reason", '
        f'"{other}", {json.dumps(str(w.wt))}]);'
    )
    res = w.run(pre=pre)
    job = res["job"]
    assert job["state"] == "failed" and job["reasons"] == ["worktree_busy"]
    assert job["pid"] is None  # pis は起動していない
    assert _lock_reason(w) == other  # 他人の lock は解除しない


def test_job_takes_over_a_stale_lock_and_releases_it(w):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    other = f"owner=worker id=w1 pid={p.pid} started=1"
    _git(w.repo, "worktree", "lock", "--reason", other, str(w.wt))
    w.mode("edit")
    assert w.run()["job"]["state"] == "succeeded"
    assert _lock_reason(w) is None


def test_shutdown_during_a_job_releases_the_lock(w):
    w.mode("slow")
    body = 'await waitLog("slow started");\nawait R.shutdown();'
    res = w.run(body=body)
    assert res["job"]["state"] == "interrupted"
    assert _lock_reason(w) is None
