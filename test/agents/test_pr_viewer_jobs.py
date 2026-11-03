"""PR ビューアのジョブ（変更を依頼 = pis -p の都度起動）の API 層の試験。

対象は job-api.ts と、server.ts・routes.ts・merge-api.ts・review-api.ts の配線。

使い捨てのリポジトリ（tmp_path。名前・メールは架空）と実 git・実サーバ・偽の pis（pr_viewer_fixtures/fake_pis.py）で確かめる。
契約: .tmp/keep/prv-app/api-contract-job.md。起動の権限は live の POST だけで、ref の記録（偽の submit・receipt・summary）は読まない。
反例（入口の検査・排他・改ざん・古い入力・上限）を先に置き、正規の起動が通る対照を同じ fixture に置く。本物の LLM・pis は呼ばない。
Linux 専用（/proc・プロセスグループ）。
"""

from __future__ import annotations

import contextlib
import http.client
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pi_review_git import PRELUDE
from test_pr_viewer_server import APP, SERVER, Server, _commit, _git, _init, _web_dir

pytestmark = [
    pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い"),
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc を使う（Linux 専用）"),
]

FAKE = Path(__file__).parent / "pr_viewer_fixtures" / "fake_pis.py"
_counter = itertools.count(1)
TERMINAL = {
    "succeeded",
    "no_change",
    "needs_review",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
}
RULES = {"judge": {"common": {"pi": {"integrate": {"risk_paths": ["docs/secret/**"]}}}}}
UUID0 = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------- 道具


class W:
    """1 つの試験用の世界: リポジトリ・サーバ・偽の pis・state dir。"""

    base: Path
    repo: Path
    state: Path
    pis: Path
    sidecar: Path
    args: list[str]
    server: Server


def _start(
    tmp: Path, *, extra: list[str] | None = None, rules: bool = True, allow: bool = True
) -> W:
    w = W()
    w.base = tmp.resolve()
    w.repo = _init(w.base / "example-app")
    _git(w.repo, "config", "user.name", "Example Dev")
    _git(w.repo, "config", "user.email", "you@example.com")
    _git(w.repo, "config", "gc.auto", "0")
    _git(w.repo, "config", "maintenance.auto", "false")
    _commit(w.repo, {"README.md": "hello\n", "keep.txt": "keep\n"}, "init")
    w.state = w.base / "state"
    bin_dir = w.base / "bin"
    bin_dir.mkdir()
    w.pis = bin_dir / "pis"
    w.sidecar = bin_dir / "pis.json"
    # 先頭に shebang を持つ python の薄い起動役。banner（ログの試験用）を出してから偽の pis へ exec する
    w.pis.write_text(
        f"#!{sys.executable}\nimport json, os, sys\n"
        f"cfg = json.load(open({str(w.sidecar)!r}, encoding='utf-8'))\n"
        "b = cfg.get('banner')\n"
        "if b:\n"
        "    sys.stdout.write(b.replace('@CWD@', os.getcwd()))\n"
        "    sys.stdout.flush()\n"
        f"os.execv(sys.executable, [sys.executable, {str(FAKE)!r}, {str(w.sidecar)!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    w.pis.chmod(0o755)
    mode(w, "noop")
    rules_file = w.base / "rules.json"
    if rules:
        rules_file.write_text(json.dumps(RULES), encoding="utf-8")
    w.rules = rules_file
    w.args = [
        "--repo",
        str(w.repo),
        "--port",
        "0",
        "--web-dir",
        str(_web_dir(w.base)),
        "--rules-file",
        str(rules_file),
        "--pis-command",
        str(w.pis),
        "--state-dir",
        str(w.state),
        *(["--allow-jobs"] if allow else []),
        *(extra or []),
    ]
    w.server = Server(w.args)
    return w


def mode(w: W, name: str, **kw) -> None:
    w.sidecar.write_text(json.dumps({"mode": name, **kw}), encoding="utf-8")


def pis_record(w: W) -> dict:
    return json.loads(
        w.sidecar.with_name(w.sidecar.name + ".record.json").read_text(encoding="utf-8")
    )


def pis_ran(w: W) -> bool:
    return w.sidecar.with_name(w.sidecar.name + ".record.json").exists()


@pytest.fixture
def w(tmp_path):
    world = _start(tmp_path)
    yield world
    world.server.stop()


@pytest.fixture
def make(tmp_path):
    made: list[W] = []

    def build(**kw) -> W:
        d = tmp_path / f"w{len(made)}"
        d.mkdir()
        world = _start(d, **kw)
        made.append(world)
        return world

    yield build
    for world in made:
        world.server.stop()
        for pid in getattr(world, "pids", []):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def origin_of(w: W) -> str:
    return f"http://127.0.0.1:{w.server.port}"


def post(w: W, path: str, body=None, *, headers=None, host=None, raw=None, origin="own"):
    """Origin・Host を正しく付けた POST。headers の値が None のものは送らない。origin=None で Origin 無し。"""
    h = {
        "Host": host or f"127.0.0.1:{w.server.port}",
        "Content-Type": "application/json",
        "X-PRV": "1",
    }
    if origin is not None:
        h["Origin"] = origin_of(w) if origin == "own" else origin
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    data = raw if raw is not None else json.dumps({} if body is None else body).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", w.server.port, timeout=60)
    conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        conn.putheader(k, v)
    conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    resp = conn.getresponse()
    text = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(text)
    except ValueError:
        return resp.status, text


def get(w: W, path: str, *, headers=None):
    """Host を付けた GET。headers の値が None のものは送らない。"""
    h = {"Host": f"127.0.0.1:{w.server.port}", **(headers or {})}
    conn = http.client.HTTPConnection("127.0.0.1", w.server.port, timeout=60)
    conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        if v is not None:
            conn.putheader(k, v)
    conn.endheaders()
    resp = conn.getresponse()
    text = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(text)
    except ValueError:
        return resp.status, text


def feature(w: W, name: str, files: dict[str, str] | None = None) -> dict:
    """worktree つきの feature を作り、コメント 1 つ + 送信（宛先はその worktree）まで済ませた PrSummary を返す。"""
    slug = name.replace("/", "-")
    wt = w.base / f"wt-{slug}"
    _git(w.repo, "worktree", "add", "-q", "-b", name, str(wt), "develop")
    _commit(wt, files or {f"{slug}.txt": "a\n"}, f"feat: {name}")
    pr = pr_of(w, name)
    pr["wt"] = wt
    comment_and_submit(w, pr, f"{name} の 1 行目を直してください")
    return pr


def pr_of(w: W, branch: str) -> dict:
    status, body = w.server.get("/api/prs")
    assert status == 200
    return next(p for p in body["prs"] if p["branch"] == branch)


def comment_and_submit(w: W, pr: dict, text: str, kind: str = "changes") -> str:
    status, c = post(w, f"/api/prs/{pr['id']}/comments", {"body": text})
    assert status == 201, c
    status, rv = get(w, f"/api/prs/{pr['id']}/review")
    dest = next(x for x in rv["worktrees"] if x["name"] == pr["wt"].name)
    status, s = post(
        w, f"/api/prs/{pr['id']}/submit", {"kind": kind, "dest": {"worktreeId": dest["worktreeId"]}}
    )
    assert status == 201, s
    return s["batchId"]


def job_input(w: W, pr: dict) -> dict:
    status, body = get(w, f"/api/prs/{pr['id']}/job-input")
    assert status == 200, body
    return body["input"]


def start(w: W, pr: dict, *, inp: dict | None = None, over: dict | None = None, **kw):
    inp = inp or job_input(w, pr)
    body = {
        "kind": "address_review",
        "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
        "batches": [b["batchId"] for b in inp["batches"]],
        "inputDigest": inp["inputDigest"],
    }
    body.update(over or {})
    return post(w, f"/api/prs/{pr['id']}/jobs", body, **kw)


def job_get(w: W, pr: dict, jid: str, frm: int = 0):
    return get(w, f"/api/prs/{pr['id']}/jobs/{jid}?from={frm}")


def wait_job(w: W, pr: dict, jid: str, secs: float = 40.0) -> dict:
    end = time.time() + secs
    last = None
    while time.time() < end:
        status, body = job_get(w, pr, jid)
        assert status == 200, body
        last = body
        if body["job"]["state"] in TERMINAL:
            return body
        time.sleep(0.1)
    raise AssertionError(f"ジョブが終わらない: {last}")


def wait_log(w: W, pr: dict, jid: str, text: str, secs: float = 20.0) -> None:
    end = time.time() + secs
    while time.time() < end:
        status, body = job_get(w, pr, jid)
        if status == 200 and text in body["log"]["text"]:
            return
        time.sleep(0.05)
    raise AssertionError(f"ログに {text!r} が出ない")


def rev(w: W, ref: str) -> str:
    return _git(w.repo, "rev-parse", ref).strip()


def job_files(w: W) -> list[dict]:
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(w.state.glob("*/jobs/*/job.json"))
    ]


def locks(w: W) -> list[Path]:
    return list(w.state.glob("*/locks/*.lock"))


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (ProcessLookupError, FileNotFoundError, PermissionError):
        return False
    return state != "Z"


def wait_dead(pid: int, secs: float = 10.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


def receipts(w: W, pr: dict) -> list[dict]:
    key = pr["prKey"]
    text = _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl")
    return [json.loads(ln) for ln in text.splitlines() if json.loads(ln)["t"] == "receipt"]


def no_leak(w: W, *texts) -> None:
    joined = "\n".join(
        t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in texts
    )
    for needle in (str(w.base), str(w.repo), "/tmp/", "/home/", str(FAKE)):
        assert needle not in joined, needle
    assert "node:" not in joined and "Error:" not in joined and "at async" not in joined


def run_js(w: W, body: str, arg=None):
    script = w.base / f"s{next(_counter)}.mjs"
    script.write_text(
        PRELUDE
        + "\n(async () => {\n"
        + body
        + "\n})().catch((e) => { console.error(e); process.exit(1); });\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_node(), str(script), str(w.repo), json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout) if proc.stdout else None


def snapshot(w: W) -> dict:
    return {"refs": _git(w.repo, "for-each-ref"), "jobs": job_files(w)}


# ---------------------------------------------------------------- 1 正規の起動が通る（反例が空振りしないための対照）


def test_legit_job_commits_and_claims_the_batch_with_a_receipt(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    assert inp["blockers"] == [] and len(inp["batches"]) == 1
    assert inp["batches"][0]["comments"][0]["body"] == "feature/a の 1 行目を直してください"
    assert inp["notice"] == {"timeoutMin": 10, "writes": "worktree", "commit": "app"}
    assert inp["limits"] == {"maxComments": 50, "maxBodyChars": 4000, "maxTotalBytes": 24576}
    mode(w, "edit")
    base = rev(w, "feature/a")
    status, resp = start(w, pr, inp=inp)
    assert status == 202, resp
    job = resp["job"]
    assert job["kind"] == "address_review" and job["baseOid"] == base
    assert job["batchIds"] == [b["batchId"] for b in inp["batches"]]
    done = wait_job(w, pr, job["id"])["job"]
    assert done["state"] == "succeeded", done
    assert done["resultOid"] == rev(w, "feature/a") != base
    assert _git(w.repo, "rev-parse", f"{done['resultOid']}^").strip() == base
    assert {f["path"]: f["status"] for f in done["files"]} == {
        "src/a.txt": "A",
        "docs/new.txt": "A",
    }
    # pis は固定の引数・feature の worktree で動いた。環境の許可リストは runner 側で試験済み（ここは配線だけ）
    rec = pis_record(w)
    assert (
        rec["argv"][:4] == ["--role", "worker", "--allowlist", "-p"]
        and rec["argv"][-1].count("PRV-DATA-BEGIN-") >= 1
    )
    assert "feature/a の 1 行目を直してください" in rec["argv"][-1]
    assert rec["cwd"] == str(pr["wt"].resolve()) and not any(
        k.startswith("GIT_") for k in rec["env"]
    )
    # receipt は app-job:<id> の sessionId で、受領済みになる。同じ batch はもう渡せない
    rc = receipts(w, pr)
    assert [r["d"] for r in rc] == [
        {"batchId": inp["batches"][0]["batchId"], "sessionId": f"app-job:{job['id']}"}
    ]
    _, rv = get(w, f"/api/prs/{pr['id']}/review")
    assert rv["batches"][0]["received"] is True
    assert locks(w) == []
    st, lst = get(w, f"/api/prs/{pr['id']}/jobs")
    assert st == 200 and [j["id"] for j in lst["jobs"]] == [job["id"]]
    no_leak(w, resp, done, lst, rv)
    # 作業場所と保存先の権限
    job_dir = next(w.state.glob("*/jobs/*"))
    assert (
        oct(job_dir.stat().st_mode & 0o777) == "0o700"
        and oct((job_dir / "job.json").stat().st_mode & 0o777) == "0o600"
    )


def test_job_model_is_passed_to_pis(make):
    w = make(extra=["--job-model", "prov-x/model-1"])
    pr = feature(w, "feature/a")
    mode(w, "noop")
    status, resp = start(w, pr)
    assert status == 202
    wait_job(w, pr, resp["job"]["id"])
    argv = pis_record(w)["argv"]
    assert argv[argv.index("--model") + 1] == "prov-x/model-1"


# ---------------------------------------------------------------- 2 既定は無効・旗・能力


def test_every_job_route_is_403_without_allow_jobs(make):
    w = make(allow=False)
    pr = feature(w, "feature/a")
    before = snapshot(w)
    for method, path in (
        ("GET", f"/api/prs/{pr['id']}/job-input"),
        ("GET", f"/api/prs/{pr['id']}/jobs"),
        ("GET", f"/api/prs/{pr['id']}/jobs/{UUID0}"),
        ("POST", f"/api/prs/{pr['id']}/jobs"),
        ("POST", f"/api/prs/{pr['id']}/jobs/{UUID0}/cancel"),
    ):
        status, body = get(w, path) if method == "GET" else post(w, path, {})
        assert status == 403 and body["error"]["code"] == "jobs_disabled", (path, body)
    assert snapshot(w) == before and not pis_ran(w) and not w.state.exists()


def test_capabilities_report_jobs_and_limits_without_paths(make):
    w = make()
    status, caps = get(w, "/api/capabilities")
    assert status == 200 and caps["merge"] is False and caps["targets"] == ["develop"]
    assert caps["jobs"] is True and caps["jobsReason"] is None
    assert caps["jobLimits"] == {"timeoutMin": 10, "concurrent": 1, "daily": 30}
    no_leak(w, caps)
    off = make(allow=False)
    caps = get(off, "/api/capabilities")[1]
    assert caps["jobs"] is False and caps["jobsReason"] is None and caps["merge"] is False


def test_missing_pis_is_reported_and_refused(make):
    w = make(extra=["--pis-command", "/nonexistent/pis"])
    caps = get(w, "/api/capabilities")[1]
    assert caps["jobs"] is False and caps["jobsReason"] == "pis_missing"
    pr = feature(w, "feature/a")
    status, body = get(w, f"/api/prs/{pr['id']}/job-input")
    assert status == 503 and body["error"]["code"] == "pis_missing"
    status, body = start(w, pr, inp={"batches": [], "inputDigest": "0" * 64})
    assert status == 503 and body["error"]["code"] == "pis_missing"
    no_leak(w, body)


def test_unsupported_platform_is_refused_at_startup_and_reported_without_the_flag(make, tmp_path):
    proc = subprocess.run(
        [
            _node(),
            str(SERVER),
            "--repo",
            str(ROOT),
            "--port",
            "0",
            "--allow-jobs",
            "--test-platform",
            "darwin",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 2 and "Linux" in proc.stderr
    w = make(allow=False, extra=["--test-platform", "darwin"])
    caps = get(w, "/api/capabilities")[1]
    assert caps["jobs"] is False and caps["jobsReason"] == "unsupported_platform"


@pytest.mark.parametrize(
    "flags",
    [
        ["--allow-jobs=1"],
        ["--job-model", "no-slash"],
        ["--job-model", "-x/y"],
        ["--state-dir", "relative/dir"],
        ["--pis-command", "pis"],
        ["--job-timeout-ms", "0"],
        ["--job-timeout-ms", "99999999"],
        ["--test-platform", "Linux!"],
    ],
)
def test_bad_flags_are_refused_with_exit_code_2(flags, tmp_path):
    repo = _init(tmp_path / "r")
    _commit(repo, {"a": "a\n"}, "init")
    proc = subprocess.run(
        [_node(), str(SERVER), "--repo", str(repo), "--port", "0", *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr


@pytest.mark.parametrize("where", [".git/state", "state"])
def test_state_dir_inside_the_repository_is_refused_with_exit_code_2(where, tmp_path):
    repo = _init(tmp_path / "r")
    _commit(repo, {"a": "a\n"}, "init")
    target = repo / where
    proc = subprocess.run(
        [
            _node(),
            str(SERVER),
            "--repo",
            str(repo),
            "--port",
            "0",
            "--allow-jobs",
            "--state-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 2 and "--state-dir" in proc.stderr, proc.stderr
    assert not target.exists()  # 何も作られていない


# ---------------------------------------------------------------- 3 入口の検査（統合と同じ）


@pytest.mark.parametrize("which", ["jobs", "cancel"])
@pytest.mark.parametrize("origin", [None, "null", "http://evil.example", "http://127.0.0.1:1"])
def test_origin_is_required_and_must_match_for_posts(w, which, origin):
    pr = feature(w, "feature/a")
    path = f"/api/prs/{pr['id']}/jobs" + (f"/{UUID0}/cancel" if which == "cancel" else "")
    before = snapshot(w)
    status, body = post(w, path, {}, origin=origin)
    assert status == 403 and body["error"]["code"] == "forbidden_origin"
    assert snapshot(w) == before and not pis_ran(w)


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_funnel_requests_are_refused_even_with_a_valid_origin(w, method):
    pr = feature(w, "feature/a")
    h = {"Tailscale-Funnel-Request": "?1"}
    if method == "GET":
        status, body = get(w, f"/api/prs/{pr['id']}/job-input", headers=h)
    else:
        status, body = post(w, f"/api/prs/{pr['id']}/jobs", {}, headers=h)
    assert status == 403 and body["error"]["code"] == "forbidden_funnel"
    assert not pis_ran(w)


def test_get_with_a_foreign_origin_is_refused_but_without_origin_is_fine(w):
    pr = feature(w, "feature/a")
    status, body = get(w, f"/api/prs/{pr['id']}/jobs", headers={"Origin": "http://evil.example"})
    assert status == 403 and body["error"]["code"] == "forbidden_origin"
    assert get(w, f"/api/prs/{pr['id']}/jobs", headers={"Origin": origin_of(w)})[0] == 200
    assert get(w, f"/api/prs/{pr['id']}/jobs")[0] == 200


@pytest.mark.parametrize(
    "headers",
    [{"X-PRV": None}, {"Content-Type": "text/plain"}, {"Content-Type": None}],
)
def test_prv_header_and_json_content_type_are_required(w, headers):
    pr = feature(w, "feature/a")
    status, body = start(w, pr, headers=headers)
    assert status == 400 and body["error"]["code"] == "bad_request"
    assert not pis_ran(w)


def test_oversized_and_malformed_bodies(w):
    pr = feature(w, "feature/a")
    path = f"/api/prs/{pr['id']}/jobs"
    status, body = post(w, path, raw=b'{"x":"' + b"a" * 70000 + b'"}')
    assert status == 413 and body["error"]["code"] == "too_large"
    assert post(w, path, raw=b"{")[1]["error"]["code"] == "bad_json"
    assert post(w, path, raw=b"[]")[1]["error"]["code"] == "bad_request"
    assert not pis_ran(w) and job_files(w) == []


def test_unknown_keys_and_bad_kind_are_400(w):
    pr = feature(w, "feature/a")
    for over in ({"extra": 1}, {"kind": "resolve_conflict"}, {"kind": None}):
        status, body = start(w, pr, over=over)
        assert status == 400 and body["error"]["code"] == "bad_request", over
    status, body = post(w, f"/api/prs/{pr['id']}/jobs/{UUID0}/cancel", {"x": 1})
    assert status == 400 and body["error"]["code"] == "bad_request"
    assert job_files(w) == [] and not pis_ran(w)


@pytest.mark.parametrize(
    "expect",
    [
        None,
        {},
        {"source": "a" * 40},
        {"source": "a" * 40, "target": "b" * 40, "base": "c" * 40},
        {"source": "A" * 40, "target": "b" * 40},
    ],
)
def test_expect_must_have_exactly_two_valid_oids(w, expect):
    pr = feature(w, "feature/a")
    status, body = start(w, pr, over={"expect": expect})
    assert status == 400 and body["error"]["code"] == "bad_expect"
    assert job_files(w) == []


@pytest.mark.parametrize(
    "batches",
    [
        [],
        "x",
        ["nope"],
        [UUID0, UUID0],
        [f"00000000-0000-4000-8000-{i:012d}" for i in range(11)],
        [1],
    ],
)
def test_batches_must_be_one_to_ten_distinct_uuids(w, batches):
    pr = feature(w, "feature/a")
    status, body = start(w, pr, over={"batches": batches})
    assert status == 400 and body["error"]["code"] == "bad_batches"


@pytest.mark.parametrize("digest", [None, "", "abc", "G" * 64, "0" * 63])
def test_digest_must_be_64_hex(w, digest):
    pr = feature(w, "feature/a")
    status, body = start(w, pr, over={"inputDigest": digest})
    assert status == 400 and body["error"]["code"] == "bad_digest"


def test_unknown_pr_is_404_and_bad_id_is_400(w):
    pr = feature(w, "feature/a")
    status, body = post(w, f"/api/prs/r00000000/{pr['prKey']}/jobs", {})
    assert status == 404
    status, body = post(w, "/api/prs/zzz/yyy/jobs", {})
    assert status == 400 and body["error"]["code"] == "bad_id"
    assert get(w, f"/api/prs/{pr['repoId']}/pdeadbeefdeadbeef/job-input")[0] == 404


# ---------------------------------------------------------------- 4 古い入力・受領済み・起動しないもの


def test_stale_view_is_409_and_nothing_starts(w):
    pr = feature(w, "feature/a")
    before = snapshot(w)
    for key in ("source", "target"):
        expect = {"source": pr["sourceOid"], "target": pr["targetOid"], key: "f" * 40}
        status, body = start(w, pr, over={"expect": expect})
        assert status == 409 and body["error"]["code"] == "stale_view", key
    assert snapshot(w) == before and not pis_ran(w)


def test_a_changed_digest_is_409_stale_input_and_leaves_no_receipt(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    before = snapshot(w)
    status, body = start(w, pr, inp=inp, over={"inputDigest": "0" * 64})
    assert status == 409 and body["error"]["code"] == "stale_input"
    assert snapshot(w) == before and receipts(w, pr) == [] and not pis_ran(w) and locks(w) == []


def test_an_unknown_batch_is_400_and_a_received_one_is_409_nothing_to_do(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    status, body = start(w, pr, inp=inp, over={"batches": [UUID0]})
    assert status == 400 and body["error"]["code"] == "bad_batches"
    mode(w, "noop")
    status, resp = start(w, pr, inp=inp)
    assert status == 202
    wait_job(w, pr, resp["job"]["id"])
    n = len(job_files(w))
    status, body = start(w, pr, inp=inp)  # 同じ batch をもう一度（受領済み）
    assert status == 409 and body["error"]["code"] == "nothing_to_do"
    assert len(job_files(w)) == n and len(receipts(w, pr)) == 1
    # 受領済みの batch は、job-input にも出ない（空になり、nothing_to_do の blocker が付く）
    again = job_input(w, pr)
    assert again["batches"] == [] and [b["code"] for b in again["blockers"]] == ["nothing_to_do"]


def test_a_batch_for_another_worktree_is_not_offered_or_accepted(w):
    pr = feature(w, "feature/a")
    # 宛先を主 worktree にした送信は、この feature の worktree へのジョブには含まれない
    status, rv = get(w, f"/api/prs/{pr['id']}/review")
    main = next(x for x in rv["worktrees"] if x["isMain"])
    post(w, f"/api/prs/{pr['id']}/comments", {"body": "主の worktree 宛て"})
    status, s = post(
        w,
        f"/api/prs/{pr['id']}/submit",
        {"kind": "comment", "dest": {"worktreeId": main["worktreeId"]}},
    )
    assert status == 201
    inp = job_input(w, pr)
    assert [b["comments"][0]["body"] for b in inp["batches"]] == [
        "feature/a の 1 行目を直してください"
    ]
    status, body = start(w, pr, inp=inp, over={"batches": [s["batchId"]]})
    assert status == 400 and body["error"]["code"] == "bad_batches"
    assert not pis_ran(w)


def test_forged_events_never_start_a_job_and_do_not_grant_anything(w):
    """偽の submit・receipt・summary を ref に置いても、ジョブは起動しない（起動は live の POST だけ）。"""
    pr = feature(w, "feature/a")
    before = rev(w, "feature/a")
    res = run_js(
        w,
        """
        const b = arg.branch;
        const vs = { source: arg.s, target: arg.t, base: arg.m };
        const mk = (t, d) => ({ v: 1, id: randomUUID(), t, by: "app", at: "2026-01-01T00:00:00Z", vs, d });
        const batchId = randomUUID();
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const r = await G.appendEvents(git, L.prKeyOf(b), meta, () => [
          mk("submit", { batchId, kind: "changes", items: [], dest: { worktreeId: arg.wt } }),
          mk("summary", { done: "偽", files: [], findings: [], mergeMessage: "feat: 偽\\n" }),
          mk("receipt", { batchId, sessionId: "app-job:" + arg.fake }),
        ], { current: vs });
        out(r);
        """,
        {
            "branch": "feature/a",
            "s": pr["sourceOid"],
            "t": pr["targetOid"],
            "m": pr["baseOid"],
            "wt": get(w, f"/api/prs/{pr['id']}/review")[1]["worktrees"][1]["worktreeId"],
            "fake": UUID0,
        },
    )
    assert res["ok"] is True, res  # 偽造は実際に書けている（書けていないとこの試験は空振り）
    time.sleep(1.0)
    for path in (
        f"/api/prs/{pr['id']}",
        f"/api/prs/{pr['id']}/review",
        f"/api/prs/{pr['id']}/jobs",
        "/api/capabilities",
    ):
        assert get(w, path)[0] == 200, path
    assert job_files(w) == [] and not pis_ran(w) and locks(w) == []
    assert rev(w, "feature/a") == before
    # 偽の受領・空の送信は、本物のコメントの batch を邪魔しない（読み取りは入力データとして扱うだけ）
    inp = job_input(w, pr)
    assert len(inp["batches"]) == 1 and inp["blockers"] == []
    # Origin の無い・ヘッダーの足りない POST は、偽の記録があっても 403/400 のまま
    assert start(w, pr, inp=inp, origin=None)[0] == 403
    assert start(w, pr, inp=inp, headers={"X-PRV": None})[0] == 400
    assert job_files(w) == [] and not pis_ran(w)


# ---------------------------------------------------------------- 5 起動前の検査（blockers・409）


def test_dirty_worktree_blocks_and_starts_nothing(w):
    pr = feature(w, "feature/a")
    (pr["wt"] / "stray.txt").write_text("手元の変更\n", encoding="utf-8")
    inp = job_input(w, pr)
    assert "dirty" in [b["code"] for b in inp["blockers"]]
    before = snapshot(w)
    status, body = start(w, pr, inp=inp)
    assert status == 409 and body["error"]["code"] == "dirty"
    assert snapshot(w) == before and receipts(w, pr) == [] and not pis_ran(w) and locks(w) == []
    no_leak(w, body, inp)


def test_opencode_in_the_worktree_blocks(w):
    pr = feature(w, "feature/a")
    (pr["wt"] / ".opencode").mkdir()
    (pr["wt"] / ".opencode" / "sandbox.toml").write_text("x = 1\n", encoding="utf-8")
    status, body = start(w, pr)
    assert status == 409 and body["error"]["code"] == "fence_request_present"
    assert not pis_ran(w) and job_files(w) == []


def test_missing_worktree_and_wrong_head_block(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    _git(pr["wt"], "switch", "-q", "--detach")
    status, body = start(w, pr, inp=inp)
    assert status == 409 and body["error"]["code"] in ("no_worktree", "head_mismatch")
    _git(w.repo, "worktree", "remove", "--force", str(pr["wt"]))
    status, body = start(w, pr, inp=inp)
    assert status == 409 and body["error"]["code"] == "no_worktree"
    blockers = [b["code"] for b in job_input(w, pr)["blockers"]]
    assert "no_worktree" in blockers
    assert not pis_ran(w) and job_files(w) == []


def test_a_merged_pr_is_409_merged(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    _git(w.repo, "merge", "-q", "--ff-only", "feature/a")
    merged = pr_of(w, "feature/a")
    merged["wt"] = pr["wt"]
    assert merged["state"] == "merged"
    assert "merged" in [b["code"] for b in job_input(w, merged)["blockers"]]
    status, body = start(w, merged, inp=inp)
    assert status == 409 and body["error"]["code"] == "merged"
    assert job_files(w) == [] and not pis_ran(w)


def test_prompt_overflow_is_413_and_leaves_no_receipt(w):
    pr = feature(w, "feature/a")
    for i in range(3):
        post(w, f"/api/prs/{pr['id']}/comments", {"body": f"{i} " + "あ" * 3990})
    _, rv = get(w, f"/api/prs/{pr['id']}/review")
    dest = next(x for x in rv["worktrees"] if x["name"] == pr["wt"].name)
    post(
        w,
        f"/api/prs/{pr['id']}/submit",
        {"kind": "comment", "dest": {"worktreeId": dest["worktreeId"]}},
    )
    inp = job_input(w, pr)
    assert "too_large" in [b["code"] for b in inp["blockers"]]
    status, body = start(w, pr, inp=inp)
    assert status == 413 and body["error"]["code"] == "too_large"
    assert not pis_ran(w) and job_files(w) == [] and len(receipts(w, pr)) == 0


def test_daily_quota_is_429_and_job_input_says_so(make):
    w = make()
    pr = feature(w, "feature/a")
    w.state.mkdir(mode=0o700, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    (w.state / "daily.json").write_text(json.dumps({"day": today, "count": 30}), encoding="utf-8")
    assert "quota" in [b["code"] for b in job_input(w, pr)["blockers"]]
    status, body = start(w, pr)
    assert status == 429 and body["error"]["code"] == "quota"
    assert not pis_ran(w) and job_files(w) == [] and receipts(w, pr) == []


def test_a_refused_start_does_not_burn_the_daily_quota(w):
    pr = feature(w, "feature/a")
    (pr["wt"] / "stray.txt").write_text("x\n", encoding="utf-8")
    for _ in range(3):
        assert start(w, pr)[0] == 409
    daily = w.state / "daily.json"
    assert not daily.exists() or json.loads(daily.read_text(encoding="utf-8"))["count"] == 0


# ---------------------------------------------------------------- 6 失敗系の終端（配線: pre・record・risk・時間切れ）


def test_a_risk_path_edit_is_needs_review_and_the_ref_does_not_move(w):
    pr = feature(w, "feature/a")
    mode(w, "risk")
    base = rev(w, "feature/a")
    status, resp = start(w, pr)
    assert status == 202
    done = wait_job(w, pr, resp["job"]["id"])["job"]
    assert (
        done["state"] == "needs_review"
        and "risk_path" in done["reasons"]
        and done["resultOid"] is None
    )
    assert rev(w, "feature/a") == base and locks(w) == []


def test_an_unreadable_risk_config_is_needs_review_not_a_free_pass(make):
    w = make(rules=False)
    pr = feature(w, "feature/a")
    mode(w, "edit")
    base = rev(w, "feature/a")
    status, resp = start(w, pr)
    assert status == 202
    done = wait_job(w, pr, resp["job"]["id"])["job"]
    assert done["state"] == "needs_review" and "risk_config" in done["reasons"]
    assert rev(w, "feature/a") == base


def test_tampering_with_the_worktree_pointer_is_failed_tampered(w):
    pr = feature(w, "feature/a")
    mode(w, "tamper", what="pointer")
    base = rev(w, "feature/a")
    status, resp = start(w, pr)
    assert status == 202
    done = wait_job(w, pr, resp["job"]["id"])["job"]
    assert done["state"] == "failed" and "tampered" in done["reasons"] and done["resultOid"] is None
    assert rev(w, "feature/a") == base
    no_leak(w, done)


def test_a_failing_pis_is_failed_exit_nonzero_and_commits_nothing(w):
    pr = feature(w, "feature/a")
    mode(w, "fail")
    base = rev(w, "feature/a")
    status, resp = start(w, pr)
    assert status == 202
    done = wait_job(w, pr, resp["job"]["id"])["job"]
    assert (
        done["state"] == "failed" and done["reasons"] == ["exit_nonzero"] and done["exitCode"] == 3
    )
    assert rev(w, "feature/a") == base


def test_a_job_that_runs_too_long_is_timed_out(make):
    w = make(extra=["--job-timeout-ms", "800"])
    pr = feature(w, "feature/a")
    mode(w, "hang")
    status, resp = start(w, pr)
    assert status == 202
    done = wait_job(w, pr, resp["job"]["id"])["job"]
    assert done["state"] == "timed_out" and done["reasons"] == ["timeout"]
    assert locks(w) == [] and wait_dead(pis_record(w)["pid"])


# ---------------------------------------------------------------- 7 排他（同じ PR・別の PR・統合中・ジョブ中の統合）


def _running(w: W, pr: dict) -> str:
    mode(w, "hang")
    status, resp = start(w, pr)
    assert status == 202, resp
    jid = resp["job"]["id"]
    wait_log(w, pr, jid, "hang started")
    w.pids = [pis_record(w)["pid"]]
    return jid


def test_the_same_pr_cannot_start_twice_and_another_pr_is_busy(make):
    w = make()
    a = feature(w, "feature/a")
    b = feature(w, "feature/b")
    ia, ib = job_input(w, a), job_input(w, b)
    jid = _running(w, a)
    before = snapshot(w)
    status, body = start(w, a, inp=ia)
    assert status == 409 and body["error"]["code"] == "job_running"
    status, body = start(w, b, inp=ib)  # 同時実行は 1
    assert status == 409 and body["error"]["code"] == "busy"
    assert "busy" in [x["code"] for x in job_input(w, b)["blockers"]]
    assert "job_running" in [x["code"] for x in job_input(w, a)["blockers"]]
    assert (
        snapshot(w)["refs"] == before["refs"]
        and len(job_files(w)) == 1
        and len(receipts(w, b)) == 0
    )
    # 終わったら、別の PR も起動できる
    assert post(w, f"/api/prs/{a['id']}/jobs/{jid}/cancel", {})[0] == 200
    mode(w, "noop")
    assert start(w, b)[0] == 202


def test_a_running_job_blocks_the_merge_plan_and_the_merge(make):
    w = make(extra=["--allow-merge"])
    a = feature(w, "feature/a")
    b = feature(w, "feature/b")
    _running(w, a)
    for pr in (a, b):  # リポジトリ単位（保護 ref の照合を乱さないため）
        status, plan = post(w, f"/api/prs/{pr['id']}/merge-plan", {})
        assert status == 200 and plan["mergeable"] is False
        assert "job_running" in [x["code"] for x in plan["blockers"]]
    before = rev(w, "develop")
    body = {
        "expect": {"source": b["sourceOid"], "target": b["targetOid"]},
        "message": "feat: b を統合する\n",
        "cleanup": "none",
    }
    status, resp = post(w, f"/api/prs/{b['id']}/merge", body)
    assert status == 409 and resp["error"]["code"] == "job_running"
    assert rev(w, "develop") == before


def test_a_running_merge_blocks_a_job_start(make):
    w = make(extra=["--allow-merge", "--merge-test-delay-ms", "2500"])
    a = feature(w, "feature/a")
    b = feature(w, "feature/b")
    inp = job_input(w, a)
    results: list = []
    body = {
        "expect": {"source": b["sourceOid"], "target": b["targetOid"]},
        "message": "feat: b を統合する\n",
        "cleanup": "none",
    }
    t = threading.Thread(target=lambda: results.append(post(w, f"/api/prs/{b['id']}/merge", body)))
    t.start()
    try:
        time.sleep(1.0)  # 遅延の間、統合は実行中（gated）
        status, resp = start(w, a, inp=inp)
        assert status == 409 and resp["error"]["code"] == "merge_running"
        assert not pis_ran(w) and job_files(w) == [] and receipts(w, a) == []
    finally:
        t.join(timeout=30)
    assert results and results[0][0] == 200, results


def test_a_concurrent_double_post_starts_exactly_one_job(w):
    pr = feature(w, "feature/a")
    inp = job_input(w, pr)
    mode(w, "hang")
    out: list = []
    ts = [threading.Thread(target=lambda: out.append(start(w, pr, inp=inp))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    codes = sorted(s for s, _ in out)
    assert codes.count(202) == 1 and all(c == 409 for c in codes if c != 202), out
    assert len(job_files(w)) == 1 and len(receipts(w, pr)) == 1
    jid = next(b["job"]["id"] for s, b in out if s == 202)
    wait_log(w, pr, jid, "hang started")
    w.pids = [pis_record(w)["pid"]]
    assert post(w, f"/api/prs/{pr['id']}/jobs/{jid}/cancel", {})[0] == 200


# ---------------------------------------------------------------- 8 キャンセル


def test_cancel_stops_the_job_and_a_second_cancel_is_409(make):
    w = make()
    pr = feature(w, "feature/a")
    jid = _running(w, pr)
    base = rev(w, "feature/a")
    status, resp = post(w, f"/api/prs/{pr['id']}/jobs/{jid}/cancel", {})
    assert status == 200 and resp["job"]["id"] == jid
    done = wait_job(w, pr, jid)["job"]
    assert done["state"] == "cancelled" and done["reasons"] == ["cancelled"]
    assert wait_dead(pis_record(w)["pid"]) and locks(w) == [] and rev(w, "feature/a") == base
    status, body = post(w, f"/api/prs/{pr['id']}/jobs/{jid}/cancel", {})
    assert status == 409 and body["error"]["code"] == "not_cancellable"


@pytest.mark.parametrize("jid", [UUID0, "not-a-uuid", "../../etc"])
def test_cancel_of_an_unknown_job_is_404(w, jid):
    pr = feature(w, "feature/a")
    status, body = post(w, f"/api/prs/{pr['id']}/jobs/{jid.replace('/', '%2F')}/cancel", {})
    assert status == 404 and body["error"]["code"] == "not_found"


def test_a_job_of_another_pr_is_not_visible_or_cancellable(make):
    w = make()
    a = feature(w, "feature/a")
    b = feature(w, "feature/b")
    jid = _running(w, a)
    assert get(w, f"/api/prs/{b['id']}/jobs/{jid}")[0] == 404
    assert post(w, f"/api/prs/{b['id']}/jobs/{jid}/cancel", {})[0] == 404
    assert get(w, f"/api/prs/{b['id']}/jobs")[1] == {"jobs": []}
    assert [j["id"] for j in get(w, f"/api/prs/{a['id']}/jobs")[1]["jobs"]] == [jid]
    assert post(w, f"/api/prs/{a['id']}/jobs/{jid}/cancel", {})[0] == 200


# ---------------------------------------------------------------- 9 ログ（衛生化・上限・範囲）


def test_log_is_sanitized_before_it_is_returned(w):
    pr = feature(w, "feature/a")
    banner = "cwd=@CWD@/src/a.txt\nhome=/home/someone/.config/x\n\x1b[31mred\x1b[0m\x07bell\x00nul\n\u202eRLO\nurl=https://example.com/a/b\nrel=src/x.ts:3\n"
    # 絶対パスの正規表現の直前の文字の制約（:）をすり抜ける形。既知の根の置換だけが落とす
    banner += "at=file:@CWD@/src/b.txt\n"
    mode(w, "noop", banner=banner)
    status, resp = start(w, pr)
    assert status == 202
    jid = resp["job"]["id"]
    body = wait_job(w, pr, jid)
    text = body["log"]["text"]
    assert (
        "<path>" in text
        and str(pr["wt"]) not in text
        and "/home/someone" not in text
        and "/src/a.txt" not in text
    )
    assert "\x1b" not in text and "\x07" not in text and "\x00" not in text and "\u202e" not in text
    assert (
        "red" in text
        and "bell" in text
        and "https://example.com/a/b" in text
        and "rel=src/x.ts:3" in text
    )
    no_leak(w, body)


def test_log_is_returned_in_16kb_line_aligned_windows(w):
    pr = feature(w, "feature/a")
    line = "x" * 99 + "\n"
    mode(w, "noop", banner=line * 500)  # 50 KB
    status, resp = start(w, pr)
    assert status == 202
    jid = resp["job"]["id"]
    wait_job(w, pr, jid)
    got, frm = "", 0
    for _ in range(10):
        status, body = job_get(w, pr, jid, frm)
        assert status == 200
        log = body["log"]
        assert (
            log["from"] == frm
            and len(log["text"].encode("utf-8")) <= 16 * 1024
            and log["next"] >= frm
        )
        if log["text"] == "":
            break
        assert log["text"].endswith("\n")
        got += log["text"]
        frm = log["next"]
    assert got == line * 500


def test_a_long_line_and_a_mid_line_start_never_leak_path_pieces(w):
    pr = feature(w, "feature/a")
    long_line = (
        "a" * 20000 + "@CWD@/src/secret.txt"
    )  # 上限内に改行がない長い 1 行（末尾も改行なし）
    mode(w, "noop", banner="head @CWD@/src/a.txt\nnext line\n" + long_line)
    status, resp = start(w, pr)
    assert status == 202
    jid = resp["job"]["id"]
    wait_job(w, pr, jid)
    _, whole = job_get(w, pr, jid, 0)
    text = whole["log"]["text"]
    assert "secret" not in text and "src/" not in text and "aaaa" not in text
    assert "長すぎる行を省略" in text and "next line" in text
    # 絶対パスの途中（「cwd の中」）を指す from でも、断片は返さない
    start_off = len("head ") + len(str(w.base)) // 2
    _, mid = job_get(w, pr, jid, start_off)
    assert mid["log"]["from"] > start_off and mid["log"]["text"].startswith("next line")
    assert str(w.base)[len(str(w.base)) // 2 :] not in mid["log"]["text"]
    no_leak(w, whole, mid)


@pytest.mark.parametrize("frm", ["-1", "abc", "1.5", "99999999999"])
def test_bad_from_is_400(w, frm):
    pr = feature(w, "feature/a")
    status, resp = start(w, pr)
    assert status == 202
    status, body = get(w, f"/api/prs/{pr['id']}/jobs/{resp['job']['id']}?from={frm}")
    assert status == 400 and body["error"]["code"] == "bad_request"


def test_unknown_job_is_404(w):
    pr = feature(w, "feature/a")
    assert get(w, f"/api/prs/{pr['id']}/jobs/{UUID0}")[0] == 404
    assert get(w, f"/api/prs/{pr['id']}/jobs/zzz")[0] == 404
    assert get(w, f"/api/prs/{pr['id']}/job-input/{UUID0}")[0] == 404


def test_the_list_returns_the_latest_five_newest_first(w):
    pr = feature(w, "feature/a")
    mode(w, "noop")
    ids = []
    for i in range(6):
        post(w, f"/api/prs/{pr['id']}/comments", {"body": f"c{i}"})
        _, rv = get(w, f"/api/prs/{pr['id']}/review")
        dest = next(x for x in rv["worktrees"] if x["name"] == pr["wt"].name)
        post(
            w,
            f"/api/prs/{pr['id']}/submit",
            {"kind": "comment", "dest": {"worktreeId": dest["worktreeId"]}},
        )
        status, resp = start(w, pr)
        assert status == 202, resp
        ids.append(resp["job"]["id"])
        wait = wait_job(w, pr, resp["job"]["id"])
        assert wait["job"]["state"] == "no_change"
    lst = get(w, f"/api/prs/{pr['id']}/jobs")[1]["jobs"]
    assert [j["id"] for j in lst] == ids[::-1][:5]


# ---------------------------------------------------------------- 10 停止・再起動


def test_sigterm_interrupts_a_running_job_and_the_server_exits(make):
    w = make()
    pr = feature(w, "feature/a")
    jid = _running(w, pr)
    pid = pis_record(w)["pid"]
    w.server.proc.send_signal(signal.SIGTERM)
    assert w.server.proc.wait(timeout=30) == 0
    assert wait_dead(pid)
    (rec,) = job_files(w)
    assert rec["id"] == jid and rec["state"] == "interrupted" and rec["reasons"] == ["shutdown"]
    assert locks(w) == []


def test_after_kill_9_a_restart_interrupts_and_never_reruns_the_job(make):
    w = make()
    pr = feature(w, "feature/a")
    jid = _running(w, pr)
    pid = pis_record(w)["pid"]
    w.server.proc.kill()
    w.server.proc.wait(timeout=10)
    assert alive(pid)  # アプリが落ちても、pis は残る（回復が止める）
    w.server = Server(w.args)  # 起動時に recover
    assert wait_dead(pid)
    (rec,) = job_files(w)
    assert rec["id"] == jid and rec["state"] == "interrupted" and rec["reasons"] == ["shutdown"]
    assert pis_record(w)["pid"] == pid  # 自動では再開しない（起動は 1 回だけ）
    assert locks(w) == []
    status, body = get(w, f"/api/prs/{pr['id']}/jobs/{jid}")
    assert status == 200 and body["job"]["state"] == "interrupted"


# ---------------------------------------------------------------- 10b 同じ state root の 2 つ目のサーバ


def _second(w: W, port: str) -> subprocess.CompletedProcess:
    args = list(w.args)
    args[args.index("--port") + 1] = port
    return subprocess.run(
        [_node(), str(SERVER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("same_port", [True, False])
def test_a_second_server_on_the_same_state_dir_is_refused_and_the_first_job_continues(
    make, same_port
):
    w = make()
    pr = feature(w, "feature/a")
    jid = _running(w, pr)
    pid = pis_record(w)["pid"]
    res = _second(w, str(w.server.port) if same_port else "0")
    assert res.returncode == 2 and "--state-dir" in res.stderr, res.stderr
    assert alive(pid), "先発の健全なジョブを止めない"
    (rec,) = job_files(w)
    assert rec["id"] == jid and rec["state"] == "running"  # interrupted にしない
    assert len(locks(w)) == 1
    status, body = job_get(w, pr, jid)
    assert status == 200 and body["job"]["state"] == "running"


# ---------------------------------------------------------------- 11 境界（import・git を直接動かさない）


def test_job_api_imports_only_allowed_modules_and_never_runs_git():
    src = (APP / "job-api.ts").read_text(encoding="utf-8")
    specs = set(re.findall(r'from "([^"]+)"', src))
    allowed = {
        "node:fs",
        "node:http",
        "node:os",
        "node:path",
        "./git-view.ts",
        "./job-git.ts",
        "./job-prompt.ts",
        "./job-runner.ts",
        "./job-store.ts",
        "./merge-api.ts",
        "./review-api.ts",
    }
    assert specs <= allowed, specs - allowed
    assert not any(
        "harness" in s or "home/dot_config" in s for s in specs
    )  # review-log・review-git も直接は読まない
    for needle in (
        "child_process",
        "spawn(",
        "execFile",
        "runGit",
        "gitWrite",
        "gitCapped",
        "git(",
    ):
        assert needle not in src, needle


def test_merge_api_exports_what_the_job_api_uses():
    src = (APP / "merge-api.ts").read_text(encoding="utf-8")
    for name in ("strictOriginOk", "loadRiskPatterns", "mergeRunning", "setJobProbe"):
        assert re.search(rf"export function {name}\b", src), name


def test_harness_imports_of_review_api_are_still_limited():
    src = (APP / "review-api.ts").read_text(encoding="utf-8")
    harness = set(re.findall(r'from "\.\./\.\./home/dot_config/pi/harness/([^"]+)"', src))
    assert harness == {"review-git.ts", "review-log.ts"}
