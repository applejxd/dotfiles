"""ローカル PR ビューアの最後の結合試験: アプリ (HTTP) と pi 側 (道具・注入) を、同じ git の ref でつなぐ。

アプリのサーバを実際に起動し、HTTP でコメントを書いて送信する。続けて、pi 側 (``pr-review.ts``) を、実際の git のリポジトリ
(主 worktree と、別の worktree) で動かし、(1) 宛先の作業ツリーの識別子 (worktreeId) がアプリと pi で一致すること、
(2) 宛先の違う作業ツリーには届かないこと、(3) 宛先には 1 回だけ届き、受領がアプリの画面の状態 (「pi が読んだ」) に反映されること、
(4) pi の返信が「pi が返信済み」として反映されること、(5) 未送信のコメントが pi に見えないことを確かめる。

see docs/spec/pr-viewer.md
"""

from __future__ import annotations

import http.client
import json
import subprocess

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pr_viewer_server import Server, _commit, _git, _init

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

HARNESS = ROOT / "home" / "dot_config" / "pi" / "harness"

PRELUDE = f"""
import * as P from {json.dumps((HARNESS / "pr-review.ts").as_uri())};
const cwd = process.argv[2];
const arg = JSON.parse(process.argv[3] || "null");
const out = (x) => process.stdout.write(JSON.stringify(x));
const handlers = {{}};
const tools = {{}};
const fakePi = {{ registerTool: (t) => (tools[t.name] = t), on: (ev, fn) => (handlers[ev] = fn) }};
const Type = {{
	Object: (p, o) => ({{ kind: "object", p, o }}),
	String: (o) => ({{ kind: "string", o }}),
	Array: (i, o) => ({{ kind: "array", i, o }}),
	Optional: (x) => ({{ kind: "optional", x }}),
}};
P.registerPr(fakePi, {{
	Type, prefix: "guarded_", child: false, hasTool: () => true,
	now: () => new Date().toISOString(), sessionId: () => "pi-session-1",
}});
const ctx = {{ cwd }};
const call = (name, params) => tools["guarded_" + name].execute("id", params, undefined, undefined, ctx);
const inject = () => handlers.before_agent_start({{ messageType: "user" }}, ctx);
"""


def run_pi(tmp_path, cwd, body, arg=None):
    """pi 側のコードを、作業ディレクトリ cwd で動かす (偽の pi に道具とハンドラを登録させる)。"""
    script = tmp_path / f"pi-{abs(hash(body)) % 10**8}.mjs"
    script.write_text(
        PRELUDE
        + "\n(async () => {\n"
        + body
        + "\n})().catch((e) => { console.error(e); process.exit(1); });\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_node(), str(script), str(cwd), json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout)


def post(server, path, payload):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={
            "Host": f"127.0.0.1:{server.port}",
            "Content-Type": "application/json",
            "X-PRV": "1",
        },
    )
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, data


def other_refs(repo):
    """refs/pi/review/ 以外の ref (アプリも pi 側も、ここを変えてはいけない)。"""
    out = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return "\n".join(line for line in out.splitlines() if not line.startswith("refs/pi/review/"))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("loop")
    repo = _init(base / "example-app")
    _commit(repo, {"src/app.ts": "export const a = 1;\nexport const b = 2;\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/add-search")
    _commit(repo, {"src/app.ts": "export const a = 1;\nexport const b = 3;\n"}, "feat: 検索")
    _git(repo, "switch", "-q", "develop")
    linked = base / "worktrees" / "add-search"
    _git(repo, "worktree", "add", "-q", str(linked), "feature/add-search")
    server = Server(["--repo", str(repo), "--port", "0"])
    yield {"base": base, "repo": repo, "linked": linked, "server": server}
    server.stop()


def test_review_loop_between_the_app_and_the_pi_side(world):
    base, repo, linked, server = world["base"], world["repo"], world["linked"], world["server"]
    refs_before = other_refs(repo)

    # 1. 画面側: コメント (行・PR 全体) を書いて、送る
    status, prs = server.get("/api/prs")
    assert status == 200 and len(prs["prs"]) == 1
    pr_id = prs["prs"][0]["id"]
    status, diff = server.get(f"/api/prs/{pr_id}/diff?path=src/app.ts")
    anchor = {"path": "src/app.ts", "side": "new", "blob": diff["newBlob"], "line": 2, "lineEnd": 2}
    status, line_comment = post(
        server, f"/api/prs/{pr_id}/comments", {"body": "この定数の理由を教えて", "anchor": anchor}
    )
    assert status == 201, line_comment
    status, _ = post(
        server, f"/api/prs/{pr_id}/comments", {"body": "全体として、テストを足してください"}
    )
    assert status == 201
    status, review = server.get(f"/api/prs/{pr_id}/review")
    assert {t["status"] for t in review["threads"]} == {"unsent"} and review["unsent"] == 2

    # 未送信のコメントは、pi 側に見えない (道具の list にも、注入にも出ない)
    hidden = run_pi(
        base,
        repo,
        'out({ list: await call("pr_comments", { branch: "feature/add-search", action: "list" }), inj: (await inject()) ?? null });',
    )
    # 送信前は、レビューの ref はあっても、pi 側に見えるスレッドは無い (下書きの本文も出ない)
    text = hidden["list"]["content"][0]["text"]
    assert (
        '"threads": []' in text and "この定数の理由を教えて" not in text and hidden["inj"] is None
    )

    status, sent = post(server, f"/api/prs/{pr_id}/submit", {"kind": "changes"})
    assert status == 201 and len(sent["items"]) == 2, sent

    # 2. 宛先の識別子 (worktreeId) が、アプリと pi 側で一致する。既定の宛先は主 worktree
    status, review = server.get(f"/api/prs/{pr_id}/review")
    main_id = review["defaultDest"]["worktreeId"]
    ids = run_pi(
        base,
        repo,
        "out({ main: P.worktreeIdOf(cwd), linked: P.worktreeIdOf(arg) });",
        arg=str(linked),
    )
    assert ids["main"] == main_id, "pi 側の worktreeId がアプリと食い違う (宛先に届かない)"
    assert {w["worktreeId"] for w in review["worktrees"]} == {ids["main"], ids["linked"]}
    assert {t["status"] for t in review["threads"]} == {"sent"}

    # 3. 宛先でない作業ツリー (feature の worktree) の pi には届かず、受領も記録されない
    other = run_pi(base, linked, "out((await inject()) ?? null);")
    assert other is None
    status, review = server.get(f"/api/prs/{pr_id}/review")
    assert review["batches"][0]["received"] is False

    # 4. 宛先 (主 worktree の親の pi) には 1 回だけ届き、受領が画面の状態に反映される
    got = run_pi(
        base,
        repo,
        "const a = await inject(); const b = await inject(); out({ a: a ?? null, b: b ?? null });",
    )
    content = got["a"]["message"]["content"]
    assert "この定数の理由を教えて" in content and "全体として、テストを足してください" in content
    assert "変更を依頼" in content and "src/app.ts:2" in content
    assert got["b"] is None
    status, review = server.get(f"/api/prs/{pr_id}/review")
    assert (
        review["batches"][0]["received"] is True
        and review["batches"][0]["sessionId"] == "pi-session-1"
    )
    assert {t["status"] for t in review["threads"]} == {"read"}

    # 5. pi の返信とサマリーが、画面の状態 (「pi が返信済み」・サマリー) に反映される
    thread_id = line_comment["comment"]["thread"]
    replied = run_pi(
        base,
        repo,
        """
        const reply = await call("pr_comments", {
          branch: "feature/add-search", action: "reply", thread: arg, body: "初期値を揃えるためです",
        });
        const summary = await call("pr_summary", { branch: "feature/add-search", done: "定数を直した", files: ["src/app.ts"],
          findings: [{ ref: arg, reply: "理由を返信した" }], notes: "未確認: 実機" });
        out({ reply: reply.isError, summary: summary.isError });
        """,
        arg=thread_id,
    )
    assert replied == {"reply": False, "summary": False}
    status, review = server.get(f"/api/prs/{pr_id}/review")
    by_id = {t["id"]: t for t in review["threads"]}
    assert (
        by_id[thread_id]["status"] == "replied" and by_id[thread_id]["comments"][-1]["by"] == "pi"
    )
    assert review["summary"] is not None and review["summary"]["done"] == "定数を直した"

    # 6. その後に画面で足した未送信のコメントは、pi 側に見えない
    status, draft = post(
        server, f"/api/prs/{pr_id}/comments", {"body": "DRAFT-AFTER", "thread": thread_id}
    )
    assert status == 201
    listed = run_pi(
        base,
        repo,
        'out(await call("pr_comments", { branch: "feature/add-search", action: "list" }));',
    )
    text = listed["content"][0]["text"]
    assert (
        "この定数の理由を教えて" in text
        and "初期値を揃えるためです" in text
        and "DRAFT-AFTER" not in text
    )
    status, review = server.get(f"/api/prs/{pr_id}/review")
    assert review["unsent"] == 1
    # 次の送信に入るのは、画面で足したコメントだけ (pi の返信や、送信済みの項目は入らない)
    status, second = post(server, f"/api/prs/{pr_id}/submit", {"kind": "comment"})
    assert status == 201 and second["items"] == [draft["comment"]["id"]], second

    # 7. アプリも pi 側も、refs/pi/review/ 以外の ref を変えていない。作業ツリーも汚れていない
    assert other_refs(repo) == refs_before
    assert _git(repo, "status", "--porcelain").strip() == ""
