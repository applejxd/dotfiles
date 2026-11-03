"""PR ビューア 段 A2 の S（統合の HTTP API）の試験。

使い捨てのリポジトリ（tmp_path。名前・メールは架空）で node のサーバを `--allow-merge` つきで起動し、HTTP で確かめる。
契約: .tmp/keep/prv-app/api-contract-merge.md。統合の権限の源は「ブラウザからの POST」だけで、ref の承認・保留は読まない（C1）。
反例（Origin・ヘッダー・expect・旧経路・競合）を先に固定し、正規の POST が通る対照を同じ fixture に置く。
"""

from __future__ import annotations

import http.client
import itertools
import json
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pi_review_git import PRELUDE
from test_pr_viewer_server import (
    APP,
    SERVER,
    Server,
    _commit,
    _git,
    _init,
    _pr_key,
    _web_dir,
)

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

_counter = itertools.count(1)
OID_A = "a" * 40


# ---------------------------------------------------------------- 道具


class W:
    """1 つの試験用の世界: リポジトリ・サーバ・feature/a の PR。"""

    base: Path
    repo: Path
    server: Server
    rules: Path
    pr: dict


def _start(
    tmp: Path,
    *,
    allow: bool = True,
    delay_ms: int = 0,
    default: str = "develop",
    rules: str | None = None,
) -> W:
    w = W()
    w.base = tmp
    w.trunk = default
    w.repo = _init(tmp / "example-app", default)
    _git(w.repo, "config", "user.name", "Example Dev")
    _git(w.repo, "config", "user.email", "you@example.com")
    _git(w.repo, "config", "gc.auto", "0")
    _git(w.repo, "config", "maintenance.auto", "false")
    _commit(w.repo, {"README.md": "hello\n", "keep.txt": "keep\n"}, "init")
    w.rules = tmp / "rules.json"
    if rules is not None:
        w.rules.write_text(rules, encoding="utf-8")
    args = [
        "--repo",
        str(w.repo),
        "--port",
        "0",
        "--web-dir",
        str(_web_dir(tmp)),
        "--rules-file",
        str(w.rules),
    ]
    if allow:
        args.append("--allow-merge")
    if delay_ms:
        args += ["--merge-test-delay-ms", str(delay_ms)]
    w.server = Server(args)
    w.pr = feature(w, "feature/a", {"a.txt": "a\n"})
    return w


def feature(w: W, name: str, files: dict[str, str]) -> dict:
    """統合先（develop。無ければ main）から枝を切ってコミットを 1 つ積み、その PrSummary を返す。"""
    trunk = w.trunk
    _git(w.repo, "switch", "-q", "-c", name, trunk)
    _commit(w.repo, files, f"feat: {name}")
    _git(w.repo, "switch", "-q", trunk)
    return pr_of(w, name)


def pr_of(w: W, branch: str) -> dict:
    status, body = w.server.get("/api/prs")
    assert status == 200
    return next(p for p in body["prs"] if p["branch"] == branch)


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


def own_origin(w: W) -> str:
    return f"http://127.0.0.1:{w.server.port}"


def post(w: W, path: str, body=None, *, headers=None, host=None, raw=None, origin="own"):
    """Origin・Host を正しく付けた POST。headers の値が None のものは送らない。origin=None で Origin 無し。"""
    h = {
        "Host": host or f"127.0.0.1:{w.server.port}",
        "Content-Type": "application/json",
        "X-PRV": "1",
    }
    if origin is not None:
        h["Origin"] = own_origin(w) if origin == "own" else origin
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


def plan(w: W, pr: dict | None = None, **kw):
    pr = pr or w.pr
    return post(w, f"/api/prs/{pr['id']}/merge-plan", {}, **kw)


def merge(w: W, pr: dict | None = None, *, body=None, **kw):
    pr = pr or w.pr
    if body is None:
        body = {
            "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
            "message": "feat: a を統合する\n",
            "cleanup": "none",
        }
    return post(w, f"/api/prs/{pr['id']}/merge", body, **kw)


def rev(w: W, ref: str = "develop") -> str:
    return _git(w.repo, "rev-parse", ref).strip()


def snapshot(w: W) -> dict:
    """統合が動かしてはいけないものの記録: 全 ref・作業ツリーの状態・HEAD。"""
    return {
        "refs": _git(w.repo, "for-each-ref"),
        "status": _git(w.repo, "status", "--porcelain=v1", "--ignored"),
        "head": _git(w.repo, "rev-parse", "HEAD"),
    }


def no_leak(w: W, *texts) -> None:
    joined = "\n".join(
        t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in texts
    )
    for needle in (str(w.base), str(w.repo.resolve()), str(w.base.resolve()), "/tmp/", "/home/"):
        assert needle not in joined
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


def make_ref(w: W, ref: str, files: dict[str, str]) -> None:
    """tree が files だけの commit を作って ref を張る（旧経路の記録・ロックの再現用）。"""
    entries = []
    for name, text in files.items():
        p = w.base / f"blob{next(_counter)}"
        p.write_text(text, encoding="utf-8")
        oid = _git(w.repo, "hash-object", "-w", str(p)).strip()
        entries.append(f"100644 blob {oid}\t{name}")
    tree_in = w.base / f"tree{next(_counter)}"
    tree_in.write_text("\n".join(entries) + "\n", encoding="utf-8")
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=w.repo,
        stdin=tree_in.open(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    commit = _git(w.repo, "commit-tree", tree, "-m", "x").strip()
    _git(w.repo, "update-ref", ref, commit)


# ---------------------------------------------------------------- 1 正規の POST が通る（反例が空振りしないための対照）


def test_legit_plan_and_merge_succeed(w):
    before = rev(w)
    status, p = plan(w)
    assert (
        status == 200 and p["mergeable"] is True and p["refusal"] is None and p["blockers"] == []
    ), p
    assert p["plan"]["source"] == {"branch": "feature/a", "oid": w.pr["sourceOid"]}
    assert p["plan"]["target"] == {"branch": "develop", "oid": w.pr["targetOid"]}
    status, m = merge(w)
    assert status == 200, m
    r = m["merge"]
    assert r["targetOld"] == before and r["targetNew"] == rev(w) == r["commit"]
    assert r["cleanup"] == {"requested": "none", "done": []} and r["recorded"] is True
    parents = _git(w.repo, "rev-list", "--parents", "-n", "1", "develop").split()
    assert parents[1:] == [before, w.pr["sourceOid"]]
    assert (w.repo / "a.txt").read_text() == "a\n"  # 作業ツリーも更新される
    assert _git(w.repo, "log", "-1", "--format=%B", "develop").strip() == "feat: a を統合する"
    _git(w.repo, "fsck", "--no-dangling")


# ---------------------------------------------------------------- 2 偽の承認では統合されない（C1）


def test_fake_review_events_never_merge(w):
    """ref に承認・merge_request・merge_started を偽造しても、待っても、全 GET を叩いても、統合は起きない。"""
    before = snapshot(w)
    res = run_js(
        w,
        """
        const b = arg.branch;
        const vs = { source: arg.s, target: arg.t, base: arg.m };
        const mk = (t, d) => ({ v: 1, id: randomUUID(), t, by: "app", at: "2026-01-01T00:00:00Z", vs, d });
        const reqId = randomUUID();
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const r = await G.appendEvents(git, L.prKeyOf(b), meta, () => [
          mk("submit", { batchId: randomUUID(), kind: "approve", items: [], dest: { worktreeId: "x" } }),
          mk("merge_request", { requestId: reqId, sourceRef: "refs/heads/" + b, sourceOid: arg.s,
            targetRef: "refs/heads/develop", targetOid: arg.t, baseOid: arg.m, message: "feat: 偽\\n", cleanup: "none" }),
          mk("merge_started", { requestId: reqId, pendingId: "1" }),
        ], { current: vs });
        out(r);
        """,
        {
            "branch": "feature/a",
            "s": w.pr["sourceOid"],
            "t": w.pr["targetOid"],
            "m": w.pr["baseOid"],
        },
    )
    assert res["ok"] is True, res  # 偽造は実際に書けている（書けていないとこの試験は空振り）
    key = _pr_key("feature/a")
    kinds = [
        json.loads(ln)["t"]
        for ln in _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl").splitlines()
    ]
    assert kinds == ["submit", "merge_request", "merge_started"]
    fake = snapshot(w)
    time.sleep(1.0)
    for path in (
        f"/api/prs/{w.pr['id']}",
        f"/api/prs/{w.pr['id']}/review",
        "/api/prs",
        "/api/repos",
        "/api/capabilities",
    ):
        assert w.server.get(path)[0] == 200, path
    assert (
        w.server.get(f"/api/prs/{w.pr['id']}/review")[1]["review"] == "approve"
    )  # アプリもこの偽造を「承認」と読む
    assert (
        rev(w) == before["head"].strip() and snapshot(w) == fake
    )  # 偽造した記録以外に、何も動かない
    # 偽の承認があっても、Origin 無しの POST は 403 で、何も動かない
    status, resp = merge(w, origin=None)
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    assert snapshot(w) == fake
    # 偽の承認は、plan を断らせもしない（権限として読まない）
    assert plan(w)[1]["mergeable"] is True


def test_fake_pending_record_never_merges_and_does_not_block(w):
    """旧経路の保留を偽造しても、統合されない。旧経路は撤去済みなので、偽造しても統合を止めることもない。"""
    make_ref(
        w,
        "refs/pi/pending/001793000000000",
        {
            "record.json": json.dumps(
                {"schema": 1, "action": "git_integrate", "params": {"source": "feature/a"}}
            )
        },
    )
    fake = snapshot(w)
    time.sleep(1.0)
    assert w.server.get(f"/api/prs/{w.pr['id']}")[0] == 200
    assert snapshot(w) == fake
    status, resp = merge(w, origin=None)
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    status, p = plan(w)
    assert status == 200 and p["blockers"] == [] and p["mergeable"] is True, p
    assert snapshot(w) == fake


# ---------------------------------------------------------------- 3 --allow-merge


def test_merge_routes_are_disabled_without_allow_merge(make):
    w = make(allow=False)
    before = snapshot(w)
    for call in (plan, merge):
        status, resp = call(w)
        assert status == 403 and resp["error"]["code"] == "merge_disabled", (call, resp)
    # 起動の旗がないとき、ほかの検査（Origin 無し）より先に merge_disabled
    status, resp = merge(w, origin=None, headers={"X-PRV": None})
    assert status == 403 and resp["error"]["code"] == "merge_disabled"
    assert snapshot(w) == before
    status, caps = w.server.get("/api/capabilities")
    assert status == 200 and caps == {"merge": False, "targets": ["develop"]}


def test_allow_merge_takes_no_value_and_unknown_flags_are_refused(tmp_path):
    repo = _init(tmp_path / "r")
    _commit(repo, {"a": "a\n"}, "init")
    for extra in (["--allow-merge=1"], ["--allow-merge", "1"], ["--allow-mergee"]):
        proc = subprocess.run(
            [_node(), str(SERVER), "--repo", str(repo), "--port", "0", *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=ROOT,
            check=False,
        )
        assert proc.returncode == 2 and "使い方" in proc.stderr, (
            extra,
            proc.returncode,
            proc.stderr,
        )


def test_capabilities_has_no_paths_and_reports_merge(w):
    status, caps = w.server.get("/api/capabilities")
    assert status == 200 and caps == {"merge": True, "targets": ["develop"]}


# ---------------------------------------------------------------- 4 Origin（merge 経路だけ必須）


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "http://evil.example",
        "http://127.0.0.1.evil.example",
        "not a url",
        "",
        "ftp://127.0.0.1",
    ],
)
@pytest.mark.parametrize("which", ["plan", "merge"])
def test_origin_is_required_and_must_match(w, which, origin):
    before = snapshot(w)
    call = plan if which == "plan" else merge
    status, resp = call(w, origin=origin)
    assert status == 403 and resp["error"]["code"] == "forbidden_origin", resp
    assert snapshot(w) == before


def test_origin_with_a_different_port_is_refused(w):
    before = snapshot(w)
    status, resp = merge(w, origin="http://127.0.0.1:1")
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    assert snapshot(w) == before


def test_tailnet_host_with_matching_origin_is_accepted_and_another_is_refused(w):
    host = "box.example.ts.net"
    status, _ = plan(w, host=host, origin=f"http://{host}")
    assert status == 200
    before = snapshot(w)
    status, resp = merge(w, host=host, origin="http://other.example.ts.net")
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    assert snapshot(w) == before


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "10.0.0.1"])
def test_disallowed_host_is_403(w, host):
    before = snapshot(w)
    status, resp = merge(w, host=host, origin=f"http://{host}")
    assert status == 403 and resp["error"]["code"] == "forbidden_host"
    assert snapshot(w) == before


# ---------------------------------------------------------------- 5 Funnel


@pytest.mark.parametrize("which", ["plan", "merge"])
def test_funnel_requests_are_refused_even_with_a_valid_origin(w, which):
    before = snapshot(w)
    call = plan if which == "plan" else merge
    status, resp = call(w, headers={"Tailscale-Funnel-Request": "?1"})
    assert status == 403 and resp["error"]["code"] == "forbidden_funnel", resp
    assert snapshot(w) == before
    assert call(w)[0] == 200  # ヘッダーが無ければ通る（対照）


# ---------------------------------------------------------------- 6 ヘッダー・本文の形


@pytest.mark.parametrize(
    "headers",
    [
        {"X-PRV": None},
        {"X-PRV": "0"},
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "multipart/form-data; boundary=x"},
        {"Content-Type": None},
    ],
)
def test_prv_header_and_json_content_type_are_required(w, headers):
    before = snapshot(w)
    status, resp = merge(w, headers=headers)
    assert status == 400 and resp["error"]["code"] == "bad_request", resp
    assert snapshot(w) == before


def test_options_is_405_without_cors_headers(w):
    status, headers, _ = w.server.request(
        f"/api/prs/{w.pr['id']}/merge", method="OPTIONS", host=f"127.0.0.1:{w.server.port}"
    )
    assert status == 405 and not [k for k in headers if k.startswith("access-control")]


@pytest.mark.parametrize("what", ["merge", "merge-plan"])
def test_get_on_merge_routes_is_404(w, what):
    status, _ = w.server.get(f"/api/prs/{w.pr['id']}/{what}")
    assert status == 404


def test_bad_json_and_non_object_bodies_are_400(w):
    before = snapshot(w)
    for raw in (b"{", b"[]", b"1", b"null"):
        status, _ = merge(w, raw=raw)
        assert status == 400, raw
    assert snapshot(w) == before


def test_merge_plan_body_must_be_an_empty_object(w):
    status, resp = plan(w, raw=b'{"x": 1}')
    assert status == 400 and resp["error"]["code"] == "bad_request"


def test_unknown_keys_in_merge_body_are_400(w):
    before = snapshot(w)
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": "feat: x\n",
        "cleanup": "none",
        "force": True,
    }
    status, resp = merge(w, body=body)
    assert status == 400 and resp["error"]["code"] == "bad_request", resp
    assert snapshot(w) == before


# ---------------------------------------------------------------- 7 expect


@pytest.mark.parametrize(
    "expect",
    [
        None,
        {},
        {"source": "a" * 40},
        {"source": "a" * 40, "target": "b" * 40, "base": "c" * 40},
        {"source": "A" * 40, "target": "b" * 40},
        {"source": "a" * 39, "target": "b" * 40},
        {"source": 1, "target": "b" * 40},
        {"source": "g" * 40, "target": "b" * 40},
        "x",
        [],
    ],
)
def test_expect_must_have_exactly_two_valid_oids(w, expect):
    before = snapshot(w)
    body = {"expect": expect, "message": "feat: x\n", "cleanup": "none"}
    if expect is None:
        del body["expect"]
    status, resp = merge(w, body=body)
    assert status == 400 and resp["error"]["code"] == "bad_expect", resp
    assert snapshot(w) == before


def test_stale_expect_is_409_and_nothing_moves(w):
    status, p = plan(w)
    assert status == 200
    _commit(w.repo, {"later.txt": "later\n"}, "別の人の変更")  # plan の後に統合先が進む
    before = snapshot(w)
    status, resp = merge(
        w,
        body={
            "expect": {"source": p["plan"]["source"]["oid"], "target": p["plan"]["target"]["oid"]},
            "message": "feat: x\n",
            "cleanup": "none",
        },
    )
    assert status == 409 and resp["error"]["code"] == "stale_view", resp
    assert snapshot(w) == before


def test_stale_source_expect_is_409(w):
    _git(w.repo, "switch", "-q", "feature/a")
    _commit(w.repo, {"a2.txt": "2\n"}, "feat: 追加")
    _git(w.repo, "switch", "-q", "develop")
    before = snapshot(w)
    status, resp = merge(w)  # w.pr は古い版
    assert status == 409 and resp["error"]["code"] == "stale_view"
    assert snapshot(w) == before


# ---------------------------------------------------------------- 8 メッセージ・cleanup


@pytest.mark.parametrize(
    "message",
    [
        "",
        "   \n本文\n",
        "\n本文",
        "件名\x00本文",
        "件名\x1b[31m",
        "x" * 4001,
        "件名\u202e偽装",
        "件名\u2066x",
        "件名\u200f",
        "件名\ud800",
        1,
        None,
        ["a"],
    ],
)
def test_bad_messages_are_400_and_write_nothing(w, message):
    before = snapshot(w)
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": message,
        "cleanup": "none",
    }
    raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
    status, resp = merge(w, raw=raw)
    assert status == 400 and resp["error"]["code"] == "bad_message", (message, resp)
    assert snapshot(w) == before


def test_message_boundary_and_crlf_normalization(w):
    msg = "feat: 境界\r\n\r\n" + "あ" * (4000 - len("feat: 境界\r\n\r\n"))
    assert len(msg) == 4000
    status, resp = merge(
        w,
        body={
            "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
            "message": msg,
            "cleanup": "none",
        },
    )
    assert status == 200, resp
    body = _git(w.repo, "log", "-1", "--format=%B", "develop")
    assert "\r" not in body and body.startswith("feat: 境界\n\n")


@pytest.mark.parametrize("cleanup", ["all", "", 1, None, ["branch"], "BRANCH"])
def test_bad_cleanup_is_400(w, cleanup):
    before = snapshot(w)
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": "feat: x\n",
        "cleanup": cleanup,
    }
    status, resp = merge(w, body=body)
    assert status == 400 and resp["error"]["code"] == "bad_cleanup", resp
    assert snapshot(w) == before


def test_cleanup_defaults_to_none(w):
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": "feat: x\n",
    }
    status, resp = merge(w, body=body)
    assert status == 200 and resp["merge"]["cleanup"] == {"requested": "none", "done": []}
    assert _git(w.repo, "branch", "--list", "feature/a").strip() != ""


# ---------------------------------------------------------------- 9 統合先の policy


def test_target_other_than_develop_is_refused(make):
    w = make(default="main")
    status, p = plan(w)
    assert status == 200 and p["mergeable"] is False and p["refusal"]["code"] == "policy_target", p
    before = snapshot(w)
    status, resp = merge(w)
    assert status == 403 and resp["error"]["code"] == "policy_target"
    assert snapshot(w) == before


# ---------------------------------------------------------------- 10 旧経路の残骸（撤去済み）


def test_legacy_refs_left_behind_do_not_block_a_merge(w):
    """refs/pi/{pending,lock,running} の残骸（壊れたものを含む）があっても、plan は通り、統合できる。"""
    make_ref(
        w,
        "refs/pi/pending/001793000000000",
        {
            "record.json": json.dumps(
                {"schema": 1, "action": "git_integrate", "params": {"source": "feature/a"}}
            )
        },
    )
    make_ref(w, "refs/pi/pending/001793000000001", {"record.json": "これは JSON ではない"})
    make_ref(w, "refs/pi/pending/0017930+odd", {"other.txt": "x"})
    make_ref(w, "refs/pi/lock/abcdef0123456789", {"x": "x"})
    make_ref(w, "refs/pi/running/001793000000003", {"attempt.json": "{}"})
    status, p = plan(w)
    assert status == 200 and p["blockers"] == [] and p["mergeable"] is True, p
    status, resp = merge(w)
    assert status == 200, resp


# ---------------------------------------------------------------- 11 失敗しても ref が動かない・パスを漏らさない


def test_conflict_is_reported_with_paths_and_moves_nothing(w):
    _git(w.repo, "switch", "-q", "-c", "feature/c", "develop")
    _commit(w.repo, {"README.md": "feature 側\n"}, "feat: c")
    _git(w.repo, "switch", "-q", "develop")
    _commit(w.repo, {"README.md": "develop 側\n"}, "develop 側の変更")
    pr = pr_of(w, "feature/c")
    status, p = plan(w, pr)
    assert status == 200 and p["mergeable"] is False and p["plan"] is None, p
    assert p["refusal"]["code"] == "conflict" and p["refusal"]["conflicts"] == ["README.md"], p
    before = snapshot(w)
    status, resp = merge(w, pr)
    assert (
        status == 409
        and resp["error"]["code"] == "conflict"
        and resp["error"]["conflicts"] == ["README.md"]
    ), resp
    assert snapshot(w) == before
    no_leak(w, p, resp)


def test_dirty_target_worktree_is_refused_and_untouched(w):
    _git(w.repo, "switch", "-q", "-c", "feature/d", "develop")
    _commit(w.repo, {"keep.txt": "feature 側\n"}, "feat: d")
    _git(w.repo, "switch", "-q", "develop")
    (w.repo / "keep.txt").write_text("手元の変更\n", encoding="utf-8")
    pr = pr_of(w, "feature/d")
    before = snapshot(w)
    status, resp = merge(w, pr)
    assert status == 409 and resp["error"]["code"] == "dirty", resp
    assert snapshot(w) == before and (w.repo / "keep.txt").read_text() == "手元の変更\n"
    no_leak(w, resp)


def test_recover_needed_is_409_and_keeps_the_state(w):
    state = w.repo / ".git" / "pr-viewer-merge.state"
    state.write_text("壊れた状態", encoding="utf-8")
    before = snapshot(w)
    status, resp = merge(w)
    assert status == 409 and resp["error"]["code"] == "recover_needed", resp
    assert state.read_text(encoding="utf-8") == "壊れた状態" and snapshot(w) == before
    no_leak(w, resp)


def test_already_merged_is_409(w):
    assert merge(w)[0] == 200
    before = snapshot(w)
    status, resp = merge(w)
    assert status == 409 and resp["error"]["code"] in ("already_merged", "stale_view"), resp
    assert snapshot(w) == before


def test_unknown_pr_is_404_and_bad_id_is_400(w):
    status, resp = post(w, "/api/prs/r00000000/p0000000000000000/merge-plan", {})
    assert status == 404
    status, resp = post(w, "/api/prs/zz/zz/merge", {})
    assert status == 400 and resp["error"]["code"] == "bad_id"


# ---------------------------------------------------------------- 12 merge-plan は副作用が無い・中身


def test_merge_plan_does_not_touch_refs_worktree_or_config(w):
    before = snapshot(w)
    config = _git(w.repo, "config", "-l")
    index = (w.repo / ".git" / "index").read_bytes()
    for _ in range(3):
        assert plan(w)[0] == 200
    assert snapshot(w) == before
    assert (
        _git(w.repo, "config", "-l") == config and (w.repo / ".git" / "index").read_bytes() == index
    )
    assert not (w.repo / ".git" / "pr-viewer-merge.lock").exists()


def test_merge_plan_shape(w):
    status, p = plan(w)
    assert status == 200
    pl = p["plan"]
    assert set(p) == {"mergeable", "refusal", "blockers", "plan", "defaults", "warnings"}
    assert set(pl) == {
        "source", "target", "mergeBase", "commits", "files", "fileCount", "additions", "deletions",
        "risks", "risksTruncated", "riskConfig", "touchesApp",
    }  # fmt: skip
    assert pl["mergeBase"] == w.pr["baseOid"] and pl["commits"] == 1
    assert pl["files"] == [{"status": "A", "path": "a.txt"}] and pl["fileCount"] == 1
    assert (pl["additions"], pl["deletions"]) == (1, 0)
    assert pl["risks"] == [] and pl["risksTruncated"] is False and pl["touchesApp"] is False
    assert pl["riskConfig"] == "unavailable"  # rules.json が無い
    d = p["defaults"]
    assert (
        set(d) == {"message", "messageSource", "summaryStale", "cleanup"} and d["cleanup"] == "none"
    )
    assert d["messageSource"] == "generated" and d["summaryStale"] is False
    no_leak(w, p)


def test_generated_default_message_follows_the_repository_conventions(w):
    _, p = plan(w)
    msg = p["defaults"]["message"]
    assert msg.splitlines()[0] == "feat: feature/a"  # 枝の最新コミットの件名
    assert len(msg.splitlines()) <= 4 and "Merge branch" not in msg
    assert (
        merge(
            w,
            body={
                "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
                "message": msg,
                "cleanup": "none",
            },
        )[0]
        == 200
    )


def test_summary_message_is_used_and_marked_stale_when_the_branch_moved(w):
    vs = {"source": w.pr["sourceOid"], "target": w.pr["targetOid"], "base": w.pr["baseOid"]}
    run_js(
        w,
        """
        const b = "feature/a";
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const e = { v: 1, id: randomUUID(), t: "summary", by: "pi", at: "2026-01-01T00:00:00Z", vs: arg,
          d: { done: "直した", files: ["a.txt"], findings: [], mergeMessage: "feat: 下書きの文面\\n\\n本文" } };
        out(await G.appendEvents(git, L.prKeyOf(b), meta, () => [e], { current: arg }));
        """,
        vs,
    )
    _, p = plan(w)
    d = p["defaults"]
    assert (
        d["message"] == "feat: 下書きの文面\n\n本文"
        and d["messageSource"] == "summary"
        and d["summaryStale"] is False
    )
    _git(w.repo, "switch", "-q", "feature/a")
    _commit(w.repo, {"a2.txt": "2\n"}, "feat: 追加")
    _git(w.repo, "switch", "-q", "develop")
    _, p = plan(w)
    d = p["defaults"]
    assert d["message"] == "feat: 下書きの文面\n\n本文" and d["summaryStale"] is True


def test_a_summary_draft_is_stale_when_only_the_target_moved(w):
    vs = {"source": w.pr["sourceOid"], "target": w.pr["targetOid"], "base": w.pr["baseOid"]}
    run_js(
        w,
        """
        const b = "feature/a";
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const e = { v: 1, id: randomUUID(), t: "summary", by: "pi", at: "2026-01-01T00:00:00Z", vs: arg,
          d: { done: "直した", files: [], findings: [], mergeMessage: "feat: 下書き\\n" } };
        out(await G.appendEvents(git, L.prKeyOf(b), meta, () => [e], { current: arg }));
        """,
        vs,
    )
    assert plan(w)[1]["defaults"]["summaryStale"] is False
    _commit(w.repo, {"later.txt": "later\n"}, "別の人の変更")  # 統合先だけが進む
    d = plan(w, pr_of(w, "feature/a"))[1]["defaults"]
    assert d["messageSource"] == "summary" and d["summaryStale"] is True


def test_a_summary_message_that_fails_validation_falls_back_to_the_generated_one(w):
    """pi が書いた下書きに双方向制御文字があっても、画面には出さない（見た目の偽装を避ける）。"""
    vs = {"source": w.pr["sourceOid"], "target": w.pr["targetOid"], "base": w.pr["baseOid"]}
    run_js(
        w,
        """
        const b = "feature/a";
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const e = { v: 1, id: randomUUID(), t: "summary", by: "pi", at: "2026-01-01T00:00:00Z", vs: arg,
          d: { done: "直した", files: [], findings: [], mergeMessage: "feat: 下書き\\u202e偽装" } };
        out(await G.appendEvents(git, L.prKeyOf(b), meta, () => [e], { current: arg }));
        """,
        vs,
    )
    _, p = plan(w)
    d = p["defaults"]
    assert d["messageSource"] == "generated" and "\u202e" not in d["message"], d


def test_risks_come_from_all_touched_paths_and_touches_app_is_independent_of_config(make):
    rules = json.dumps(
        {
            "judge": {
                "common": {
                    "pi": {
                        "integrate": {"risk_paths": ["AGENTS.md", "scripts/verify*.py", "docs/**"]}
                    }
                }
            }
        }
    )
    w = make(rules=rules)
    files = {f"docs/f{i:03}.md": "x\n" for i in range(250)}
    files.update({"AGENTS.md": "x\n", "scripts/verify_x.py": "x\n", "apps/pr-viewer/x.ts": "x\n"})
    pr = feature(w, "feature/big", files)
    status, p = plan(w, pr)
    pl = p["plan"]
    assert status == 200 and pl["riskConfig"] == "loaded" and pl["touchesApp"] is True
    assert pl["fileCount"] == 253 and len(pl["files"]) == 200
    assert (
        len(pl["risks"]) == 50 and pl["risksTruncated"] is True
    )  # 表示の上限は 50。判定は全件に対して行う
    assert all(set(r) == {"path", "reason"} for r in pl["risks"])
    # 表示に出る 200 件の外にだけあるリスクのパスも見逃さない: a000〜a249 の 250 件の後ろ（パス順）にあるパスだけがリスク
    rules2 = json.dumps({"judge": {"common": {"pi": {"integrate": {"risk_paths": ["zzz/**"]}}}}})
    w2 = make(rules=rules2)
    files2 = {f"a{i:03}.md": "x\n" for i in range(250)}
    files2.update({"zzz/risk.md": "x\n", "zzz/app.txt": "x\n"})
    pr2 = feature(w2, "feature/tail", files2)
    status, p2 = plan(w2, pr2)
    pl2 = p2["plan"]
    assert pl2["fileCount"] == 252 and len(pl2["files"]) == 200
    assert all(
        not f["path"].startswith("zzz/") for f in pl2["files"]
    )  # 表示の 200 件には入っていない
    assert (
        sorted(r["path"] for r in pl2["risks"]) == ["zzz/app.txt", "zzz/risk.md"]
        and pl2["risksTruncated"] is False
    )
    # touchesApp も同じ（apps/pr-viewer/ は a### の後ろ）
    w3 = make(rules=rules2)
    files3 = {f"a{i:03}.md": "x\n" for i in range(250)}
    files3["apps/pr-viewer/x.ts"] = "x\n"
    status, p3 = plan(w3, feature(w3, "feature/app2", files3))
    assert (
        all(not f["path"].startswith("apps/") for f in p3["plan"]["files"])
        and p3["plan"]["touchesApp"] is True
    )


@pytest.mark.parametrize(
    "rules",
    [
        None,
        "{",
        '{"judge": 1}',
        '{"judge": {"common": {"pi": {"integrate": {"risk_paths": "x"}}}}}',
        '{"judge": {"common": {"pi": {"integrate": {"risk_paths": ["docs/**", 1]}}}}}',
    ],
)
def test_unreadable_risk_config_is_reported_not_treated_as_no_risk(make, rules):
    w = make(rules=rules)
    pr = feature(w, "feature/app", {"apps/pr-viewer/x.ts": "x\n"})
    status, p = plan(w, pr)
    assert status == 200 and p["plan"]["riskConfig"] == "unavailable" and p["plan"]["risks"] == []
    assert p["plan"]["touchesApp"] is True


def test_review_warnings_are_shown_but_do_not_block(w):
    vs = {"source": w.pr["sourceOid"], "target": w.pr["targetOid"], "base": w.pr["baseOid"]}
    run_js(
        w,
        """
        const b = "feature/a";
        const mk = (t, d, v) => ({ v: 1, id: randomUUID(), t, by: "app", at: "2026-01-01T00:00:00Z", vs: v, d });
        const old = { ...arg, source: "e".repeat(40) };
        const cid = randomUUID();
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        out(await G.appendEvents(git, L.prKeyOf(b), meta, () => [
          { ...mk("comment", { thread: cid, anchor: null, body: "直して" }, arg), id: cid },
          mk("submit", { batchId: randomUUID(), kind: "changes", items: [], dest: { worktreeId: "x" } }, old),
          { ...mk("comment", { thread: "t2", anchor: null, body: "未送信" }, arg), id: randomUUID() },
        ], { current: arg }));
        """,
        vs,
    )
    status, p = plan(w)
    codes = {x["code"] for x in p["warnings"]}
    assert (
        status == 200
        and p["mergeable"] is True
        and {"review_changes", "review_stale", "unsent_comments"} <= codes
    ), p
    assert all(set(x) == {"code", "message"} for x in p["warnings"])
    assert merge(w)[0] == 200  # 警告は拒否の根拠にしない


# ---------------------------------------------------------------- 13 成功の記録（C6）


def test_success_is_recorded_as_request_and_result_and_the_pr_is_merged(w):
    assert merge(w)[0] == 200
    status, rv = w.server.get(f"/api/prs/{w.pr['id']}/review")
    assert status == 200 and rv["merged"] is True and rv["bad"] is None
    key = _pr_key("feature/a")
    events = [
        json.loads(line)
        for line in _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl").splitlines()
    ]
    assert [e["t"] for e in events] == ["merge_request", "merge_result"]
    req, res = events
    assert req["d"]["requestId"] == res["d"]["requestId"] and res["d"]["outcome"] == "success"
    assert (
        res["d"]["doneOid"] == rev(w)
        and req["by"] == "app"
        and req["d"]["message"].startswith("feat: a を統合する")
    )
    assert (req["d"]["sourceOid"], req["d"]["targetOid"]) == (w.pr["sourceOid"], w.pr["targetOid"])
    # 統合済みの PR にはコメントを書けない（既存の挙動）
    status, resp = post(w, f"/api/prs/{w.pr['id']}/comments", {"body": "x"})
    assert status == 409 and resp["error"]["code"] == "merged"


def test_recording_failure_still_reports_the_merge_as_a_success(w):
    key = _pr_key("feature/a")
    make_ref(w, f"refs/pi/review/{key}", {"meta.json": "壊れている", "events.jsonl": "壊れている"})
    status, rv = w.server.get(f"/api/prs/{w.pr['id']}/review")
    assert status == 200 and rv["bad"]
    status, resp = merge(w)
    assert status == 200 and resp["merge"]["recorded"] is False, resp
    assert rev(w) == resp["merge"]["commit"]


def test_a_reserved_events_area_refuses_the_pair_and_leaves_no_lone_request(w):
    """レビュー記録が上限の予約領域に近いとき、merge_request（終端用の余裕に書けない）を含むペア全体が断られる。"""
    vs = {"source": w.pr["sourceOid"], "target": w.pr["targetOid"], "base": w.pr["baseOid"]}
    res = run_js(
        w,
        """
        const b = "feature/a";
        const meta = { schema: 1, pr: L.prKeyOf(b), branch: b, target: "develop", createdAt: "2026-01-01T00:00:00Z" };
        const mk = (body) => ({ v: 1, id: randomUUID(), t: "comment", by: "app", at: "2026-01-01T00:00:00Z", vs: arg,
          d: { thread: "t", anchor: null, body } });
        const size = (es) => Buffer.byteLength(L.serializeEvents(es), "utf8");
        const events = [];
        for (let i = 0; i < 30; i++) events.push(mk("x".repeat(16000)));
        const fill = 491200 - size(events) - size([mk("")]);
        events.push(mk("x".repeat(fill)));
        out(await G.appendEvents(git, L.prKeyOf(b), meta, () => events, { current: arg }));
        """,
        vs,
    )
    assert res["ok"] is True, res
    status, resp = merge(w)
    assert status == 200 and resp["merge"]["recorded"] is False, resp
    key = _pr_key("feature/a")
    kinds = {
        json.loads(ln)["t"]
        for ln in _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl").splitlines()
    }
    assert kinds == {"comment"}  # request だけが残らない


def test_failed_merges_are_not_recorded(w):
    key = _pr_key("feature/a")
    state = w.repo / ".git" / "pr-viewer-merge.state"
    state.write_text("壊れた状態", encoding="utf-8")
    assert merge(w)[0] == 409
    state.unlink()
    assert _git(w.repo, "for-each-ref", f"refs/pi/review/{key}").strip() == ""


# ---------------------------------------------------------------- 14 cleanup


def test_cleanup_branch_removes_the_branch_and_the_pr_disappears(w):
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": "feat: x\n",
        "cleanup": "branch",
    }
    status, resp = merge(w, body=body)
    assert status == 200 and resp["merge"]["cleanup"] == {
        "requested": "branch",
        "done": ["branch"],
    }, resp
    assert _git(w.repo, "branch", "--list", "feature/a").strip() == ""
    assert all(p["branch"] != "feature/a" for p in w.server.get("/api/prs")[1]["prs"])
    assert resp["merge"]["recorded"] is True  # 枝を消しても、レビュー記録は残る
    assert _git(w.repo, "for-each-ref", f"refs/pi/review/{_pr_key('feature/a')}").strip() != ""


def test_cleanup_branch_and_worktree_removes_a_clean_linked_worktree(w):
    wt = w.base / "wt-a"
    _git(w.repo, "worktree", "add", "-q", str(wt), "feature/a")
    body = {
        "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
        "message": "feat: x\n",
        "cleanup": "branch_and_worktree",
    }
    status, resp = merge(w, body=body)
    assert status == 200 and resp["merge"]["cleanup"]["done"] == ["worktree", "branch"], resp
    assert not wt.exists()
    no_leak(w, resp)


# ---------------------------------------------------------------- 15 同時実行


def _start_merge(w: W, pr: dict | None = None):
    """統合を別スレッドで始め、統合器の状態ファイルができる（ff の直前。ここで --merge-test-delay-ms の間待つ）まで待つ。"""
    box: dict = {}
    t = threading.Thread(target=lambda: box.update(r=merge(w, pr)))
    t.start()
    state = w.repo / ".git" / "pr-viewer-merge.state"
    assert _wait(state.exists), "統合が始まらなかった"
    return t, box


def _send_merge_raw(w: W, pr: dict | None = None) -> socket.socket:
    """merge を生のソケットで送る（応答を読まず、呼び出し側で切る）。"""
    pr = pr or w.pr
    body = json.dumps(
        {
            "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
            "message": "feat: x\n",
            "cleanup": "none",
        }
    ).encode()
    head = (
        f"POST /api/prs/{pr['id']}/merge HTTP/1.1\r\nHost: 127.0.0.1:{w.server.port}\r\n"
        f"Origin: {own_origin(w)}\r\nContent-Type: application/json\r\nX-PRV: 1\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode()
    s = socket.create_connection(("127.0.0.1", w.server.port), timeout=10)
    s.sendall(head + body)
    return s


def _merge_count(w: W) -> str:
    return _git(w.repo, "rev-list", "--merges", "--count", "develop").strip()


def test_two_concurrent_merges_in_a_repo_run_at_most_one_at_a_time(make):
    w = make(delay_ms=800)
    b = feature(w, "feature/b", {"b.txt": "b\n"})
    first, box = _start_merge(w, w.pr)
    status, resp = merge(w, b)  # 実行中に、別の PR の 2 つ目
    assert status == 409 and resp["error"]["code"] == "busy", resp
    first.join(timeout=30)
    assert box["r"][0] == 200, box
    assert _merge_count(w) == "1" and _git(w.repo, "status", "--porcelain").strip() == ""
    _git(w.repo, "fsck", "--no-dangling")
    assert not (w.repo / ".git" / "pr-viewer-merge.lock").exists()
    assert not (w.repo / ".git" / "pr-viewer-merge.state").exists()
    # 負けた側は、勝った側が終わった後、最新の版で再試行すれば統合できる（gate が解放されている）
    status, resp = merge(w, pr_of(w, "feature/b"))
    assert status == 200, resp
    assert _merge_count(w) == "2"


def test_the_same_pr_cannot_be_merged_twice_concurrently(make):
    w = make(delay_ms=600)
    first, box = _start_merge(w)
    status, resp = merge(w)
    assert status == 409 and resp["error"]["code"] == "busy", resp
    first.join(timeout=30)
    assert box["r"][0] == 200 and _merge_count(w) == "1"
    _git(w.repo, "fsck", "--no-dangling")


# ---------------------------------------------------------------- 16 停止の扱い・通信断


def _wait(cond, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _assert_merged_and_recorded(w: W, before: str) -> None:
    state = w.repo / ".git" / "pr-viewer-merge.state"
    assert rev(w) != before and not state.exists()
    assert not (w.repo / ".git" / "pr-viewer-merge.lock").exists()
    key = _pr_key("feature/a")
    assert "merge_result" in _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl")
    _git(w.repo, "fsck", "--no-dangling")


def test_sigterm_waits_for_the_running_merge_and_records_it(make):
    w = make(delay_ms=1500)
    before = rev(w)
    t, box = _start_merge(w)
    w.server.proc.send_signal(signal.SIGTERM)  # ff の直前に止めようとする
    time.sleep(0.1)
    w.server.proc.send_signal(signal.SIGTERM)  # 重複しても、実行中の統合は止まらない
    t.join(timeout=30)
    status, resp = box["r"]
    assert status == 200, resp
    assert w.server.proc.wait(timeout=20) == 0
    assert rev(w) == resp["merge"]["commit"]
    _assert_merged_and_recorded(w, before)


def test_a_dropped_connection_does_not_stop_the_merge(make):
    w = make(delay_ms=600)
    before = rev(w)
    s = _send_merge_raw(w)
    state = w.repo / ".git" / "pr-viewer-merge.state"
    assert _wait(state.exists), "統合が始まらなかった"
    s.close()  # 統合が始まってから切る
    assert _wait(lambda: rev(w) != before), "切断の後も統合は続く"
    key = _pr_key("feature/a")
    assert _wait(
        lambda: (
            "merge_result"
            in _git(w.repo, "show", f"refs/pi/review/{key}:events.jsonl", check=False)
        )
    )
    _assert_merged_and_recorded(w, before)
    assert w.server.get("/api/repos")[0] == 200  # サーバは生きている


@pytest.mark.parametrize("order", ["drop_then_sigterm", "sigterm_then_drop"])
def test_a_dropped_connection_and_sigterm_together_still_finish_the_merge(make, order):
    """通信が切れた統合の途中で SIGTERM を受けても、統合・記録を終えるまでプロセスは終わらない。"""
    w = make(delay_ms=1500)
    before = rev(w)
    s = _send_merge_raw(w)
    state = w.repo / ".git" / "pr-viewer-merge.state"
    assert _wait(state.exists), "統合が始まらなかった"
    if order == "drop_then_sigterm":
        s.close()
        time.sleep(0.2)
        w.server.proc.send_signal(signal.SIGTERM)
    else:
        w.server.proc.send_signal(signal.SIGTERM)
        time.sleep(0.2)
        s.close()
    assert w.server.proc.poll() is None, "統合の途中でプロセスが終わった"
    assert w.server.proc.wait(timeout=30) == 0
    _assert_merged_and_recorded(w, before)


def test_new_requests_are_refused_while_stopping(make):
    w = make(delay_ms=1500)
    late = feature(
        w, "feature/late", {"late.txt": "x\n"}
    )  # 統合を始める前に用意する（統合中に HEAD を動かさない）
    t, box = _start_merge(w)
    w.server.proc.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    try:
        status, resp = merge(w, late)
    except OSError:
        status, resp = (
            0,
            None,
        )  # すでに接続を受け付けない
    assert status in (0, 503, 409), (status, resp)
    t.join(timeout=30)
    assert box["r"][0] == 200 and w.server.proc.wait(timeout=30) == 0
    assert _merge_count(w) == "1"


# ---------------------------------------------------------------- 17 診断ログ


def test_diagnostic_log_has_one_json_line_per_merge_without_message_or_paths(make):
    w = make()
    assert (
        merge(
            w,
            body={
                "expect": {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]},
                "message": "feat: 秘密の文面 SECRET-MSG\n",
                "cleanup": "none",
            },
        )[0]
        == 200
    )
    assert merge(w, origin=None)[0] == 403
    w.server.proc.terminate()
    w.server.proc.wait(timeout=20)
    err = w.server.proc.stderr.read()
    lines = [ln for ln in err.splitlines() if ln.strip()]
    logs = [json.loads(ln) for ln in lines if ln.startswith("{")]
    merges = [x for x in logs if x.get("t") == "merge"]
    assert len(merges) == 1 and merges[0]["result"] == "ok" and merges[0]["recorded"] is True, err
    assert (
        merges[0]["pr"] == w.pr["prKey"]
        and merges[0]["commit"] == rev(w)
        and re.fullmatch(r"[0-9a-f-]{36}", merges[0]["req"])
        and merges[0]["repo"] == w.pr["repoId"]
        and merges[0]["expect"] == {"source": w.pr["sourceOid"], "target": w.pr["targetOid"]}
    )
    assert "SECRET-MSG" not in err and str(w.base) not in err and "X-PRV" not in err


# ---------------------------------------------------------------- 18 既存の経路への影響・静的な規則


def test_existing_review_posts_do_not_need_allow_merge(make):
    w = make(allow=False)
    status, resp = post(w, f"/api/prs/{w.pr['id']}/comments", {"body": "x"}, origin=None)
    assert status == 201, resp  # 既存の経路は Origin 無しを許す（変えない）


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in APP.glob("*.ts")}


def test_merge_api_import_boundary_and_no_direct_ref_writes():
    src = _sources()
    api = src["merge-api.ts"]
    imports = set(re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", api))
    assert all(
        s.startswith(("./", "node:", "../../home/dot_config/pi/harness/")) for s in imports
    ), imports
    assert {s.rsplit("/", 1)[1] for s in imports if "harness" in s} <= {
        "review-log.ts",
        "review-git.ts",
    }
    # HTTP 側は git を直接動かさない（子プロセス・ref の書き込みは持たない）
    for forbidden in (
        "child_process",
        "update-ref",
        "commit-tree",
        "hash-object",
        "spawn(",
        "execFile",
    ):
        assert forbidden not in api, forbidden
    # 統合器は merge-api.ts からだけ使う（server.ts・routes.ts は直接 import しない）
    for name in ("server.ts", "routes.ts", "review-api.ts", "git-view.ts"):
        assert "./merge.ts" not in src[name] and "./merge-git.ts" not in src[name], name
    assert "./merge.ts" in api
    # 統合器と git 実行器は、node: と同じ階層だけを import する
    for name in ("merge.ts", "merge-git.ts"):
        for s in re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", src[name]):
            assert s.startswith(("./", "node:")), (name, s)
    # child_process を使うのは git-view.ts と merge-git.ts だけ
    users = {n for n, t in src.items() if "child_process" in t}
    assert users == {"git-view.ts", "merge-git.ts"}, users


def test_merge_api_never_reads_the_approval_state_as_authority():
    """統合の権限は live の HTTP リクエストだけ。承認・レビュー状態を読む部品（foldState など）を merge-api.ts は持たない。

    レビュー状態の表示用の読み出し（警告・下書き）は review-api.ts が担い、merge-api.ts はその結果を表示に使うだけ。
    旧経路の保留・ロックは、拒否のためにだけ列挙する。
    """
    api = _sources()["merge-api.ts"]
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", api, flags=re.S)  # コメントは除く
    for token in (
        "foldState",
        "reviewVs",
        ".review ===",
        '"approve"',
        "'approve'",
        "merge_started",
        "readPr",
        "appendEvents",
    ):
        assert token not in code, token
