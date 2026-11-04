"""pr-review.ts (ローカル PR ビューアの pi 側: 道具 pr_summary) の試験。

偽の pi に道具を登録させ、ダミーのリポジトリ (名前・メールは架空) で実際の git の ref を読み書きして確かめる。
レビューコメントの送信 (pr_comments・次の入力の前の注入) は撤去した。

see docs/spec/pr-viewer.md
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

PRELUDE = f"""
import * as P from {json.dumps((HARNESS / "pr-review.ts").as_uri())};
import * as L from {json.dumps((HARNESS / "review-log.ts").as_uri())};
import * as G from {json.dumps((HARNESS / "review-git.ts").as_uri())};
import {{ randomUUID }} from "node:crypto";

const cwd = process.argv[2];
const arg = JSON.parse(process.argv[3] || "null");
const out = (x) => process.stdout.write(JSON.stringify(x));
const git = P.gitIn(cwd);
const handlers = {{}};
const tools = {{}};
const fakePi = {{ registerTool: (t) => (tools[t.name] = t), on: (ev, fn) => (handlers[ev] = fn) }};
const Type = {{
	Object: (p, o) => ({{ kind: "object", p, o }}),
	String: (o) => ({{ kind: "string", o }}),
	Array: (i, o) => ({{ kind: "array", i, o }}),
	Optional: (x) => ({{ kind: "optional", x }}),
}};
const baseDeps = {{
	Type, prefix: "guarded_", child: false, hasTool: () => true,
	now: () => "2026-01-01T00:00:00Z",
}};
const reg = (over = {{}}) => P.registerPr(fakePi, {{ ...baseDeps, ...over }});
const ctx = {{ cwd }};
const call = (name, params) => tools["guarded_" + name].execute("id", params, undefined, undefined, ctx);
const KEY = L.prKeyOf("feature/x");
const VS = async () => {{
	const rp = async (r) => (await git(["rev-parse", r])).stdout.trim();
	const source = await rp("refs/heads/feature/x");
	const target = await rp("refs/heads/develop");
	const base = (await git(["merge-base", target, source])).stdout.trim();
	return {{ source, target, base }};
}};
const ev = (t, d, vs, o = {{}}) => ({{ v: 1, id: o.id ?? randomUUID(), t, by: o.by ?? "app", at: "2026-01-01T00:00:00Z", vs, d }});
const state = async () => {{
	const r = await G.readPr(git, KEY);
	return r.kind === "ok" ? L.foldState(r.meta, r.events, r.events.at(-1)?.vs ?? await VS()) : r;
}};
"""


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    out = subprocess.run(
        [node, "--version"], capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    if not match:
        return None
    return node if (int(match.group(1)), int(match.group(2))) >= (22, 18) else None


pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

GENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def g(repo, *args, input=None):
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=GENV,
        check=False,
    )
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "example-app"
    r.mkdir()
    g(r, "init", "-q", "-b", "develop")
    (r / "a.txt").write_text("1\n", encoding="utf-8")
    g(r, "add", ".")
    g(r, "commit", "-q", "-m", "init")
    g(r, "switch", "-q", "-c", "feature/x")
    (r / "a.txt").write_text("1\n2\n", encoding="utf-8")
    g(r, "commit", "-q", "-am", "feat: x")
    g(r, "switch", "-q", "develop")
    return r


@pytest.fixture
def js(tmp_path):
    n = [0]

    def _js(repo, body, arg=None):
        n[0] += 1
        script = tmp_path / f"t{n[0]}.mjs"
        script.write_text(
            PRELUDE
            + "\n(async () => {\n"
            + body
            + "\n})().catch((e) => { console.error(e); process.exit(1); });\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [_node(), str(script), str(repo), json.dumps(arg)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        return json.loads(proc.stdout)

    return _js


def review_refs(repo):
    return g(repo, "for-each-ref", "--format=%(refname)", "refs/pi/review/")


def other_refs(repo):
    """refs/pi/review/ 以外の ref (ここが変わってはいけない)。"""
    out = g(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return "\n".join(line for line in out.splitlines() if not line.startswith("refs/pi/review/"))


def _key(branch="feature/x"):
    return "p" + hashlib.sha256(f"v1\0refs/heads/{branch}".encode()).hexdigest()[:16]


# ─── 登録 ───────────────────────────────────────────────────────────


def test_child_registers_nothing_and_missing_tools_are_not_registered(repo, js):
    r = js(
        repo,
        """
        reg({ child: true });
        const child = { tools: Object.keys(tools), handlers: Object.keys(handlers) };
        reg({ hasTool: () => false });
        const none = { tools: Object.keys(tools), handlers: Object.keys(handlers) };
        reg();
        out({ child, none, both: { tools: Object.keys(tools).sort(), handlers: Object.keys(handlers) } });
        """,
    )
    assert r["child"] == {"tools": [], "handlers": []}
    assert r["none"] == {"tools": [], "handlers": []}
    # pr_comments と、次の入力の前の注入 (before_agent_start) は撤去した
    assert r["both"] == {"tools": ["guarded_pr_summary"], "handlers": []}


# ─── pr_summary ─────────────────────────────────────────────────────


def test_pr_summary_writes_a_summary_event(repo, js):
    r = js(
        repo,
        """
        reg();
        const res = await call("pr_summary", { branch: "feature/x", done: "検索を足した", files: ["a.txt"],
          findings: [{ ref: "c1", reply: "直した" }], notes: "未確認あり", mergeMessage: "feat: x" });
        const s = await state();
        out({ res, summary: s.summary, by: s.summary?.by, count: s.count });
        """,
    )
    assert r["res"]["isError"] is False and "投稿" in r["res"]["content"][0]["text"]
    assert (
        r["summary"]["d"]["done"] == "検索を足した" and r["summary"]["d"]["notes"] == "未確認あり"
    )
    assert r["by"] == "pi" and r["count"] == 1


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "develop",
        "feature/../x",
        "feature/a b",
        "",
        "feature/x\nfeature/y",
        "refs/heads/feature/x",
    ],
)
def test_pr_summary_refuses_bad_branch_names(repo, js, branch):
    r = js(
        repo,
        """
        reg();
        out(await call("pr_summary", { branch: arg, done: "d", files: [] }));
        """,
        arg=branch,
    )
    assert r["isError"] is True
    assert review_refs(repo) == ""


def test_pr_summary_refuses_missing_branch_and_bad_arguments(repo, js):
    r = js(
        repo,
        """
        reg();
        const missing = await call("pr_summary", { branch: "feature/none", done: "d", files: [] });
        const emptyDone = await call("pr_summary", { branch: "feature/x", done: " ", files: [] });
        const manyFiles = await call("pr_summary", { branch: "feature/x", done: "d", files: Array(201).fill("f") });
        const badFinding = await call("pr_summary", { branch: "feature/x", done: "d", files: [], findings: [{ ref: 1 }] });
        out([missing, emptyDone, manyFiles, badFinding].map((x) => x.isError));
        """,
    )
    assert r == [True, True, True, True]
    assert review_refs(repo) == ""


def test_pr_summary_refuses_a_merged_pr(repo, js):
    r = js(
        repo,
        """
        reg();
        await call("pr_summary", { branch: "feature/x", done: "d", files: [] });
        const vs = await VS();
        const rid = randomUUID();
        await G.appendEvents(git, KEY, null, () => [
          ev("merge_request", { requestId: rid, sourceRef: "refs/heads/feature/x", sourceOid: vs.source, targetRef: "refs/heads/develop",
            targetOid: vs.target, baseOid: vs.base, message: "m", cleanup: "none" }, vs),
          ev("merge_result", { requestId: rid, outcome: "success" }, vs, { by: "pi" }),
        ]);
        out(await call("pr_summary", { branch: "feature/x", done: "もう一度", files: [] }));
        """,
    )
    assert r["isError"] is True and "統合済み" in r["content"][0]["text"]


# ─── 書き込みの範囲・hook・lazy fetch ──────────────────────────────────


def test_tools_write_only_under_refs_pi_review(repo, js):
    before = other_refs(repo)
    js(
        repo,
        """
        reg();
        await call("pr_summary", { branch: "feature/x", done: "d", files: ["a.txt"] });
        out(true);
        """,
    )
    assert review_refs(repo) != ""
    assert other_refs(repo) == before
    assert g(repo, "status", "--porcelain") == ""


def test_pr_review_is_thin_no_server_and_only_the_review_libraries():
    text = (HARNESS / "pr-review.ts").read_text(encoding="utf-8")
    imports = re.findall(r"""^\s*import\b[^;]*?from\s+["']([^"']+)["']""", text, re.M)
    assert imports, "import 文が読めていない"
    assert all(
        i.startswith("node:") or i in ("./review-git.ts", "./review-log.ts") for i in imports
    ), imports
    assert not re.search(
        r"node:(http|https|net|http2|dgram)|\bfetch\(|createServer|\.listen\(", text
    )


def test_pr_comments_and_the_injection_are_gone():
    """撤去したもの (pr_comments・注入・受領) が、pr-review.ts に残っていないこと。"""
    text = (HARNESS / "pr-review.ts").read_text(encoding="utf-8")
    assert not re.search(r"pr_comments|before_agent_start|collectInjection|receipt", text)


def test_tools_do_not_run_repository_hooks(repo, js, tmp_path):
    marker = tmp_path / "hook-ran"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    g(repo, "config", "core.hooksPath", str(hooks))
    # 前提: 素の git の ref 更新では hook が動く (これが成り立たなければ次の確認は何も確かめていない)
    g(repo, "update-ref", "refs/scratch/x", "HEAD")
    assert marker.exists(), "素の git で hook が動かない"
    marker.unlink()
    js(
        repo,
        """
        reg();
        await call("pr_summary", { branch: "feature/x", done: "d", files: [] });
        out(true);
        """,
    )
    assert review_refs(repo) != ""
    assert not marker.exists(), "道具の書き込みでリポジトリの hook が動いた"


def test_tools_do_not_start_lazy_fetches(repo, js, tmp_path):
    """partial clone で足りないオブジェクトを読むと、git は fetch (ssh) を起動する。道具では起動させない (C9)。"""
    marker = tmp_path / "ssh-ran"
    ssh = tmp_path / "fake-ssh.sh"
    ssh.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    ssh.chmod(0o755)
    js(
        repo,
        'reg(); await call("pr_summary", { branch: "feature/x", done: "d", files: [] }); out(true);',
    )
    events_blob = g(repo, "rev-parse", f"refs/pi/review/{_key()}:events.jsonl")
    (repo / ".git" / "objects" / events_blob[:2] / events_blob[2:]).unlink()
    for key, value in (
        ("core.repositoryformatversion", "1"),
        ("extensions.partialClone", "origin"),
        ("remote.origin.url", "ssh://example.invalid/x.git"),
        ("remote.origin.promisor", "true"),
        ("core.sshCommand", str(ssh)),
    ):
        g(repo, "config", key, value)
    # 前提: 素の git で足りない blob を読むと、ssh が起動して印ができる
    subprocess.run(
        ["git", "cat-file", "-p", events_blob], cwd=repo, env=GENV, capture_output=True, check=False
    )
    if not marker.exists():
        pytest.skip("この git では、足りないオブジェクトの読み取りが fetch を起動しない")
    marker.unlink()
    js(
        repo,
        """
        reg();
        await call("pr_summary", { branch: "feature/x", done: "e", files: [] });
        out(true);
        """,
    )
    assert not marker.exists(), "道具が、足りないオブジェクトの取得 (ssh) を起動した"
