"""PR ビューア（サーバの POST の共通規則・書き込みの範囲・レビュー状態の読み出し）の試験。

使い捨てのリポジトリ（tmp_path。名前・メールは架空）で node のサーバを起動し、HTTP で確かめる。
残る POST は統合（merge-plan・merge）だけなので、汎用の検査（ヘッダー・Origin・Host・サイズ・JSON）は merge-plan を乗り物にする。
レビューコメントの送信（comments・submit）は撤去した（docs/spec/pr-viewer.md）。
receipt や pi の返信などは、共有ライブラリの node スクリプトで直接追記して作る。
"""

from __future__ import annotations

import hashlib
import http.client
import itertools
import json
import re
import subprocess
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pi_review_git import PRELUDE
from test_pr_viewer_merge_api import _start as _start_merge_world
from test_pr_viewer_merge_api import post as merge_post
from test_pr_viewer_server import (
    APP,
    Server,
    _commit,
    _git,
    _init,
    _repo_id,
    _script,
    _web_dir,
)

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

_counter = itertools.count(1)


# ---------------------------------------------------------------- 道具


def call(server, path, method="POST", body=None, *, headers=None, raw=None, host="127.0.0.1"):
    """HTTP 呼び出し。headers の値が None のものは送らない。"""
    h = {"Host": host, "Content-Type": "application/json", "X-PRV": "1"}
    h.update(headers or {})
    h = {k: v for k, v in h.items() if v is not None}
    data = raw if raw is not None else json.dumps(body if body is not None else {}).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=60)
    conn.request(method, path, body=data, headers=h)
    resp = conn.getresponse()
    text = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(text)
    except ValueError:
        return resp.status, text


def run_js(tmp: Path, repo: Path, body: str, arg=None):
    """共有ライブラリ（review-log.ts・review-git.ts）を node で直接呼ぶ。"""
    script = tmp / f"s{next(_counter)}.mjs"
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
    return json.loads(proc.stdout) if proc.stdout else None


class World:
    pass


def _make_branch(repo: Path, name: str) -> None:
    """develop から、変更・追加・改名・削除を 1 つずつ含むブランチを作る。"""
    _git(repo, "switch", "-q", "-c", name, "develop")
    _git(repo, "mv", "old.txt", "renamed.txt")
    _git(repo, "rm", "-q", "gone.txt")
    _commit(
        repo,
        {
            "README.md": "hello\nbrave\nworld\n",
            "docs/new.txt": "new\n",
            "renamed.txt": "".join(f"古い行 {i}\n" for i in range(30)).replace(
                "古い行 3\n", "新しい行 3\n"
            ),
        },
        f"feat: {name}",
    )
    _git(repo, "switch", "-q", "develop")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("write")
    w = World()
    w.base = base
    w.repo = _init(base / "example-app")
    _commit(
        w.repo,
        {
            "README.md": "hello\nworld\n",
            "old.txt": "".join(f"古い行 {i}\n" for i in range(30)),
            "gone.txt": "bye\n",
            "keep.txt": "keep\n",
        },
        "init",
    )
    w.server = Server(["--repo", str(w.repo), "--port", "0", "--web-dir", str(_web_dir(base))])
    w.texts = []  # 応答の全文（パスの非漏洩の検査用）
    yield w
    w.server.stop()


@pytest.fixture(scope="module")
def mworld(tmp_path_factory):
    """--allow-merge つきのサーバ（汎用の POST の検査の乗り物は merge-plan）。"""
    w = _start_merge_world(tmp_path_factory.mktemp("write-merge"))
    yield w
    w.server.stop()


def new_pr(w: World) -> dict:
    """新しい PR（feature/tN）を作って、その PrSummary を返す。"""
    name = f"feature/t{next(_counter)}"
    _make_branch(w.repo, name)
    status, body = w.server.get("/api/prs")
    assert status == 200
    return next(p for p in body["prs"] if p["branch"] == name)


def review(w: World, pr: dict) -> dict:
    status, body = w.server.get(f"/api/prs/{pr['id']}/review")
    assert status == 200
    w.texts.append(json.dumps(body, ensure_ascii=False))
    return body


def refs_of(repo: Path) -> str:
    return _git(repo, "for-each-ref")


def ref_events(repo: Path, pr: dict) -> list[dict]:
    text = _git(repo, "cat-file", "blob", f"refs/pi/review/{pr['prKey']}:events.jsonl")
    return [json.loads(line) for line in text.splitlines()]


def current_vs(pr: dict) -> dict:
    return {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}


def plan(m, **kw):
    """統合の計画（merge-plan）への POST。残る POST の代表。"""
    return merge_post(m, f"/api/prs/{m.pr['id']}/merge-plan", kw.pop("body", {}), **kw)


# ---------------------------------------------------------------- diff の応答


def test_diff_response_has_no_blob_fields(world):
    """行コメントの位置指定（blob）は撤去した。diff の応答は差分の閲覧に要るものだけ。"""
    pr = new_pr(world)
    status, body = world.server.get(f"/api/prs/{pr['id']}/diff?path=README.md")
    assert status == 200
    assert set(body) == {"path", "binary", "truncated", "hunks"}
    assert body["path"] == "README.md" and body["binary"] is False and body["hunks"]
    status, body = world.server.get(f"/api/prs/{pr['id']}/diff?path=gone.txt")
    assert status == 200 and set(body) == {"path", "binary", "truncated", "hunks"}


# ---------------------------------------------------------------- 書き込み（POST）の共通規則


@pytest.mark.parametrize(
    "headers",
    [
        {"X-PRV": None},
        {"X-PRV": "0"},
        {"Content-Type": None},
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/x-www-form-urlencoded"},
        {"Content-Type": "application/jsonx"},
    ],
)
def test_missing_or_wrong_headers_are_400_and_write_nothing(mworld, headers):
    before = refs_of(mworld.repo)
    for what in ("merge-plan", "merge"):
        status, resp = merge_post(mworld, f"/api/prs/{mworld.pr['id']}/{what}", {}, headers=headers)
        assert status == 400 and resp["error"]["code"] == "bad_request"
    assert refs_of(mworld.repo) == before


def test_charset_in_content_type_is_accepted(mworld):
    status, _ = plan(mworld, headers={"Content-Type": "application/json; charset=utf-8"})
    assert status == 200


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "http://127.0.0.1:1", "null", "http://localhost", "x"]
)
def test_foreign_origin_is_403_and_writes_nothing(mworld, origin):
    before = refs_of(mworld.repo)
    status, resp = plan(mworld, origin=origin)
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    assert refs_of(mworld.repo) == before


def test_own_origin_is_accepted_and_a_missing_origin_is_403(mworld):
    assert plan(mworld)[0] == 200
    status, resp = plan(mworld, origin=None)
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "10.0.0.1"])
def test_disallowed_host_is_403_for_post(mworld, host):
    before = refs_of(mworld.repo)
    status, resp = plan(mworld, host=host)
    assert status == 403 and resp["error"]["code"] == "forbidden_host"
    assert refs_of(mworld.repo) == before


def test_too_large_body_is_413(mworld):
    before = refs_of(mworld.repo)
    big = json.dumps({"message": "x" * (64 * 1024)}).encode("utf-8")
    status, resp = plan(mworld, raw=big)
    assert status == 413 and resp["error"]["code"] == "too_large"
    assert refs_of(mworld.repo) == before


@pytest.mark.parametrize("raw", [b"{", b"", b"not json", b'{"body": "x"', b"\xff\xfe"])
def test_broken_json_is_400(mworld, raw):
    before = refs_of(mworld.repo)
    status, resp = plan(mworld, raw=raw)
    assert status == 400 and resp["error"]["code"] == "bad_json"
    assert refs_of(mworld.repo) == before


@pytest.mark.parametrize("raw", [b"[]", b"1", b'"x"', b"null"])
def test_json_that_is_not_an_object_is_400(mworld, raw):
    for what in ("merge-plan", "merge"):
        status, resp = merge_post(mworld, f"/api/prs/{mworld.pr['id']}/{what}", None, raw=raw)
        assert status == 400 and resp["error"]["code"] == "bad_request"


def test_chunked_body_over_the_limit_is_413_and_writes_nothing(mworld):
    """Content-Length が無い (chunked) でも、ストリームの実測で 64 KB を超えたら 413。"""
    before = refs_of(mworld.repo)
    payload = json.dumps({"message": "x" * (96 * 1024)}).encode("utf-8")
    chunks = [payload[i : i + 8192] for i in range(0, len(payload), 8192)]
    conn = http.client.HTTPConnection("127.0.0.1", mworld.server.port, timeout=60)
    conn.request(
        "POST",
        f"/api/prs/{mworld.pr['id']}/merge-plan",
        body=iter(chunks),
        headers={
            "Host": f"127.0.0.1:{mworld.server.port}",
            "Origin": f"http://127.0.0.1:{mworld.server.port}",
            "Content-Type": "application/json",
            "X-PRV": "1",
        },
        encode_chunked=True,
    )
    resp = conn.getresponse()
    status, text = resp.status, resp.read().decode("utf-8")
    conn.close()
    assert status == 413 and json.loads(text)["error"]["code"] == "too_large"
    assert refs_of(mworld.repo) == before


def test_only_the_known_posts_are_allowed(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    base = f"/api/prs/{pr['id']}"
    cases = [
        ("POST", "/api/repos"),
        ("POST", "/api/prs"),
        ("POST", base),
        ("POST", f"{base}/review"),
        ("POST", f"{base}/diff?path=README.md"),
        ("POST", f"{base}/merge/x"),
        # 撤去したレビューコメントの送信（comments・submit）は、POST の入口が無い
        ("POST", f"{base}/comments"),
        ("POST", f"{base}/submit"),
        ("POST", f"{base}/comments/x"),
        ("POST", "/"),
        ("POST", "/web/app.js"),
        ("PUT", f"{base}/comments"),
        ("DELETE", f"{base}/comments"),
        ("PATCH", f"{base}/submit"),
        ("PUT", f"{base}/submit"),
        ("DELETE", base),
    ]
    for method, path in cases:
        status, resp = call(
            world.server, path, method=method, body={"body": "x", "kind": "changes"}
        )
        assert status == 405 and resp["error"]["code"] == "method_not_allowed", (method, path)
    # 統合の POST は --allow-merge が無いと断る（この world は付けていない）
    for what in ("merge", "merge-plan"):
        status, resp = call(world.server, f"{base}/{what}", body={})
        assert status == 403 and resp["error"]["code"] == "merge_disabled", what
    assert refs_of(world.repo) == before


def test_get_on_removed_post_routes_is_404(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    for what in ("comments", "submit"):
        status, _ = world.server.get(f"/api/prs/{pr['id']}/{what}")
        assert status == 404
    assert refs_of(world.repo) == before


def test_get_review_has_no_side_effect_and_works_without_a_ref(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    body = review(world, pr)
    assert refs_of(world.repo) == before and pr["prKey"] not in refs_of(world.repo)
    assert body["schema"] == 1 and body["readonly"] is False and body["bad"] is None
    assert body["summary"] is None and body["merged"] is False and body["stale"] is False
    assert body["staleParts"] == {"source": False, "target": False, "base": False}
    # コメント・送信の状態（threads・batches・unsent・review・宛先の候補）は返さない
    for gone in (
        "threads",
        "batches",
        "unsent",
        "review",
        "reviewStale",
        "worktrees",
        "defaultDest",
    ):
        assert gone not in body, gone
    status, headers, _ = world.server.request(f"/api/prs/{pr['id']}/review")
    assert status == 200 and headers["cache-control"] == "no-store"
    assert world.server.get(f"/api/prs/{_repo_id(world.repo)}/p{'0' * 16}/review")[0] == 404
    assert world.server.get("/api/prs/r00000000/pzz/review")[0] == 400
    assert refs_of(world.repo) == before


def test_review_response_headers_are_safe(world):
    pr = new_pr(world)
    _status, headers, _ = world.server.request(f"/api/prs/{pr['id']}/review")
    assert (
        headers["content-type"].startswith("application/json")
        and headers["x-content-type-options"] == "nosniff"
    )
    assert "default-src 'self'" in headers["content-security-policy"]


# ---------------------------------------------------------------- 書き込みの範囲


GIT_WRITE_JS = f"""
const M = await import({json.dumps((APP / "git-view.ts").as_uri())});
const {{ openRepo, gitWrite }} = M;
const repo = await openRepo(arg.repo);
const results = [];
const input = arg.inputBytes === undefined ? undefined : "x".repeat(arg.inputBytes);
for (const argv of arg.argvs) {{
	try {{
		const r = await gitWrite(repo, argv, input);
		results.push({{ argv, ok: true, code: r.code }});
	}} catch (e) {{
		results.push({{ argv, ok: false, code: e.code ?? String(e) }});
	}}
}}
out(results);
"""


def test_git_write_allowlist(world, tmp_path):
    before_refs = refs_of(world.repo)
    oid = _git(world.repo, "rev-parse", "develop").strip()
    tree = _git(world.repo, "rev-parse", "develop^{tree}").strip()
    key = "refs/pi/review/p0123456789abcdef"
    denied = [
        ["log"],
        ["status"],
        ["diff", "develop"],
        ["config", "core.hooksPath", "/tmp/x"],
        ["push"],
        ["fetch"],
        ["gc"],
        ["checkout", "develop"],
        ["commit", "-m", "x"],
        ["worktree", "add", "x"],
        ["worktree", "list"],
        # 作業ツリーの一覧は、宛先の候補（撤去済み）のためだけの許可だった
        ["worktree", "list", "--porcelain"],
        ["worktree", "list", "--porcelain", "-z"],
        ["update-ref", "-d", key],
        ["update-ref", "--no-deref", "-d", key],
        ["update-ref", key, oid],  # --no-deref が無い
        # --no-deref が無く、引数の位置をずらすと、任意の ref を更新できてしまう形
        ["update-ref", "refs/heads/develop", key, oid],
        ["update-ref", "--no-deref", "refs/heads/develop", oid],
        ["update-ref", "--no-deref", "refs/heads/feature/x", oid],
        ["update-ref", "--no-deref", "HEAD", oid],
        ["update-ref", "--no-deref", "refs/pi/review/p0123456789abcde", oid],  # 15 桁
        ["update-ref", "--no-deref", "refs/pi/review/p0123456789abcdeg", oid],
        ["update-ref", "--no-deref", "refs/pi/review/p0123456789abcdef/x", oid],
        ["update-ref", "--no-deref", "refs/pi/review/../heads/develop", oid],
        ["update-ref", "--no-deref", "refs/pi/other/p0123456789abcdef", oid],
        ["update-ref", "--no-deref", key, "develop"],  # OID でない値
        ["update-ref", "--stdin"],
        ["hash-object", "/etc/hostname"],
        ["hash-object", "-w", "/etc/hostname"],
        ["hash-object", "-w", "--stdin", "--path=x"],
        ["cat-file", "--textconv", f"{oid}:README.md"],
        ["cat-file", "--filters", f"{oid}:README.md"],
        ["cat-file", "--batch"],
        ["commit-tree", tree, "-m", "x"],
        ["commit-tree", tree, "-S", "-F", "-"],
        ["commit-tree", "develop", "-F", "-"],
        ["-c", "core.hooksPath=/tmp/x", "rev-parse", "HEAD"],
        ["-c", "core.fsmonitor=/tmp/x", "rev-parse", "HEAD"],
        ["-c", "core.sshCommand=x", "rev-parse", "HEAD"],
        ["-c", "user.name=x", "log"],
        ["--exec-path=/tmp", "rev-parse", "HEAD"],
        ["-C", "/tmp", "rev-parse", "HEAD"],
        ["rev-parse", "--git-dir", "--show-cdup", "-q", "--exec"],
        ["for-each-ref", "--shell"],
        ["ls-tree", "--format=x", oid],
        ["merge-base", "--octopus", oid, oid],
        [],
        [""],
    ]
    allowed = [
        ["rev-parse", "--verify", "--quiet", "refs/heads/develop"],
        ["cat-file", "-t", oid],
        ["cat-file", "-s", oid],
        ["cat-file", "blob", f"{oid}:README.md"],
        ["ls-tree", "-z", oid],
        ["for-each-ref", "--format=%(refname)", "refs/pi/review/"],
        ["merge-base", oid, oid],
        [
            "-c",
            "user.name=a",
            "-c",
            "user.email=b@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "rev-parse",
            "HEAD",
        ],
    ]
    res = run_js(
        tmp_path,
        world.repo,
        GIT_WRITE_JS,
        {"repo": str(world.repo), "argvs": denied + allowed, "inputBytes": 0},
    )
    for r in res[: len(denied)]:
        assert r == {"argv": r["argv"], "ok": False, "code": "git_denied"}, r["argv"]
    for r in res[len(denied) :]:
        assert r["ok"] is True, r["argv"]
    assert refs_of(world.repo) == before_refs  # 断られた操作で ref は変わらない


def test_git_write_can_create_a_review_ref_and_cannot_touch_others(world, tmp_path):
    repo = _init(tmp_path / "scratch-app")
    _commit(repo, {"a.txt": "a\n"}, "init")
    oid = _git(repo, "rev-parse", "HEAD").strip()
    key = "refs/pi/review/p0123456789abcdef"
    res = run_js(
        tmp_path,
        repo,
        GIT_WRITE_JS,
        {
            "repo": str(repo),
            "argvs": [
                ["update-ref", "--no-deref", key, oid, "0" * 40],
                ["update-ref", "--no-deref", "refs/heads/develop", oid],
            ],
        },
    )
    assert res[0]["ok"] is True and res[0]["code"] == 0
    assert res[1] == {"argv": res[1]["argv"], "ok": False, "code": "git_denied"}
    assert _git(repo, "rev-parse", key).strip() == oid


def test_git_write_input_limit(world, tmp_path):
    res = run_js(
        tmp_path,
        world.repo,
        GIT_WRITE_JS,
        {
            "repo": str(world.repo),
            "argvs": [["hash-object", "-w", "--stdin"]],
            "inputBytes": 1024 * 1024 + 1,
        },
    )
    assert res[0] == {
        "argv": ["hash-object", "-w", "--stdin"],
        "ok": False,
        "code": "git_too_large",
    }


# ---------------------------------------------------------------- 状態


def test_pi_summary_is_returned(world, tmp_path):
    pr = new_pr(world)
    run_js(
        tmp_path,
        world.repo,
        """
        const key = L.prKeyOf(arg.branch);
        const r = await G.appendEvents(git, key, meta(arg.branch), () => [
            ev("summary", { done: "直した", files: ["README.md"], findings: [], notes: "メモ" }, { vs: arg.vs }),
        ]);
        out(r.ok);
        """,
        {"branch": pr["branch"], "vs": current_vs(pr)},
    )
    s = review(world, pr)["summary"]
    assert (
        s["done"] == "直した"
        and s["files"] == ["README.md"]
        and s["notes"] == "メモ"
        and s["by"] == "pi"
        and s["at"]
    )


def test_stale_follows_the_branch(world, tmp_path):
    pr = new_pr(world)
    run_js(
        tmp_path,
        world.repo,
        """
        const key = L.prKeyOf(arg.branch);
        const r = await G.appendEvents(git, key, meta(arg.branch), () => [
            ev("summary", { done: "古くなる", files: [], findings: [] }, { vs: arg.vs }),
        ]);
        out(r.ok);
        """,
        {"branch": pr["branch"], "vs": current_vs(pr)},
    )
    rv = review(world, pr)
    assert (rv["stale"], rv["merged"]) == (False, False) and rv["summary"]["done"] == "古くなる"
    _git(world.repo, "switch", "-q", pr["branch"])
    _commit(world.repo, {"keep.txt": "keep\nmore\n"}, "feat: more")
    _git(world.repo, "switch", "-q", "develop")
    rv = review(world, pr)
    assert rv["stale"] is True and rv["staleParts"]["source"] is True
    assert rv["staleParts"]["target"] is False and rv["staleParts"]["base"] is False
    assert rv["summary"]["done"] == "古くなる"  # 表示は残る


# ---------------------------------------------------------------- 統合済み・壊れた記録

MERGE_JS = """
const key = L.prKeyOf(arg.branch);
const rid = randomUUID();
const r = await G.appendEvents(git, key, meta(arg.branch), () => [
    ev("merge_request", { requestId: rid, sourceRef: "refs/heads/" + arg.branch, sourceOid: arg.vs.source, targetRef: "refs/heads/develop",
        targetOid: arg.vs.target, baseOid: arg.vs.base, message: "m", cleanup: "keep" }, { vs: arg.vs }),
    ev("merge_result", { requestId: rid, outcome: arg.outcome }, { vs: arg.vs }),
]);
out(r.ok);
"""


def test_a_merge_record_marks_the_pr_merged(world, tmp_path):
    pr = new_pr(world)
    assert (
        run_js(
            tmp_path,
            world.repo,
            MERGE_JS,
            {"branch": pr["branch"], "vs": current_vs(pr), "outcome": "success"},
        )
        is True
    )
    assert review(world, pr)["merged"] is True


def test_a_failed_merge_does_not_mark_the_pr_merged(world, tmp_path):
    pr = new_pr(world)
    assert (
        run_js(
            tmp_path,
            world.repo,
            MERGE_JS,
            {"branch": pr["branch"], "vs": current_vs(pr), "outcome": "refused"},
        )
        is True
    )
    assert review(world, pr)["merged"] is False


def _plant(repo: Path, pr: dict, entries: list[tuple[str, str, str, str]]) -> str:
    lines = ""
    for mode, typ, content, name in entries:
        proc = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=repo,
            input=content,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        lines += f"{mode} {typ} {proc.stdout.strip()}\t{name}\n"
    tree = subprocess.run(
        ["git", "mktree"],
        cwd=repo,
        input=lines,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    env_user = ["-c", "user.name=Example", "-c", "user.email=you@example.com"]
    commit = subprocess.run(
        ["git", *env_user, "commit-tree", tree, "-m", "planted"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    _git(repo, "update-ref", f"refs/pi/review/{pr['prKey']}", commit)
    return commit


def _good_meta(pr: dict, **kw) -> str:
    m = {
        "schema": 1,
        "pr": pr["prKey"],
        "branch": pr["branch"],
        "target": "develop",
        "createdAt": "2026-01-01T00:00:00Z",
    }
    return json.dumps({**m, **kw})


def test_selfcheck_failure_is_reported_as_bad(world):
    pr = new_pr(world)
    _plant(
        world.repo,
        pr,
        [
            ("100644", "blob", _good_meta(pr), "meta.json"),
            ("100644", "blob", "", "events.jsonl"),
            ("100644", "blob", "x", "evil.sh"),  # tree に余計なファイル
        ],
    )
    before = refs_of(world.repo)
    rv = review(world, pr)
    assert isinstance(rv["bad"], str) and rv["bad"] and rv["summary"] is None
    assert rv["readonly"] is False
    assert refs_of(world.repo) == before


def test_invalid_event_log_is_reported_as_bad(world):
    pr = new_pr(world)
    _plant(
        world.repo,
        pr,
        [
            ("100644", "blob", _good_meta(pr), "meta.json"),
            ("100644", "blob", "{not json}\n", "events.jsonl"),
        ],
    )
    assert review(world, pr)["bad"]


def test_newer_schema_is_readonly(world):
    pr = new_pr(world)
    _plant(
        world.repo,
        pr,
        [
            ("100644", "blob", _good_meta(pr, schema=3), "meta.json"),
            ("100644", "blob", "", "events.jsonl"),
        ],
    )
    before = refs_of(world.repo)
    rv = review(world, pr)
    assert rv["readonly"] is True and rv["summary"] is None and rv["bad"] is None
    assert refs_of(world.repo) == before


def test_old_comment_and_submit_events_are_still_readable(world, tmp_path):
    """撤去前に書かれた comment・submit・receipt は、壊れた記録として扱わず、読み取れる（互換）。"""
    pr = new_pr(world)
    res = run_js(
        tmp_path,
        world.repo,
        """
        const key = L.prKeyOf(arg.branch);
        const c = cm("古いコメント", { by: "app", vs: arg.vs });
        const sub = ev("submit", { batchId: randomUUID(), kind: "changes", items: [c.id], dest: { worktreeId: "w1" } }, { vs: arg.vs });
        const r = await G.appendEvents(git, key, meta(arg.branch), () => [c, sub]);
        out(r.ok);
        """,
        {"branch": pr["branch"], "vs": current_vs(pr)},
    )
    assert res is True
    rv = review(world, pr)
    assert rv["bad"] is None and rv["readonly"] is False and rv["merged"] is False


def _prkey(branch: str) -> str:
    return "p" + hashlib.sha256(f"v1\0refs/heads/{branch}".encode()).hexdigest()[:16]


RECORD_JS = """
const key = L.prKeyOf(arg.branch);
const r = await G.appendEvents(git, key, meta(arg.branch), () => [cm("記録", { by: "app", vs: arg.vs })]);
out(r.ok);
"""


def test_zero_commit_branch_is_listed_only_when_it_has_a_review_record(world, tmp_path):
    repo = world.repo
    hidden, reviewed = "feature/zero-hidden", "feature/zero-reviewed"
    for n in (hidden, reviewed):
        _git(repo, "branch", n, "develop")  # develop と同じ先頭 (差分無し・0 コミット)
    try:
        listed = {p["branch"] for p in world.server.get("/api/prs")[1]["prs"]}
        assert hidden not in listed and reviewed not in listed  # 記録が無いのでどちらも出ない
        # ID を直接指定すれば読める (一覧に出さないだけ)
        status, body = world.server.get(f"/api/prs/{_repo_id(repo)}/{_prkey(hidden)}")
        assert status == 200 and body["pr"]["state"] == "merged" and body["pr"]["commits"] == 0
        # レビューの記録 (refs/pi/review/<prKey>) が付くと、統合済みとして出る
        tip = _git(repo, "rev-parse", "develop").strip()
        vs = {"source": tip, "target": tip, "base": tip}
        assert run_js(tmp_path, repo, RECORD_JS, {"branch": reviewed, "vs": vs}) is True
        listed = {p["branch"]: p for p in world.server.get("/api/prs")[1]["prs"]}
        assert hidden not in listed  # 他の PR の記録では出ない
        assert reviewed in listed and listed[reviewed]["state"] == "merged"
        assert listed[reviewed]["commits"] == 0
    finally:
        for n in (hidden, reviewed):
            _git(repo, "branch", "-D", n)


# ---------------------------------------------------------------- 敵対的な設定


@pytest.fixture(scope="module")
def hostile(tmp_path_factory):
    base = tmp_path_factory.mktemp("hostile-write")
    h = World()
    h.base = base
    h.marks = base / "marks"
    h.marks.mkdir()
    repo = _init(base / "example-app")
    h.repo = repo
    tools = base / "tools"
    tools.mkdir()
    hooks = base / "hooks"
    hooks.mkdir()
    fsmonitor = _script(tools / "fsmonitor.sh", f"touch {h.marks}/fsmonitor\nexit 1")
    _script(hooks / "reference-transaction", f"touch {h.marks}/hooks")
    _script(hooks / "post-commit", f"touch {h.marks}/post-commit")
    _script(hooks / "pre-commit", f"touch {h.marks}/pre-commit")
    _commit(repo, {"README.md": "hello\nworld\n", "tracked.md": "t\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/hostile")
    _commit(repo, {"README.md": "hello\nbrave\nworld\n"}, "feat: hostile")
    _git(repo, "switch", "-q", "develop")
    _git(repo, "config", "core.fsmonitor", str(fsmonitor))
    _git(repo, "config", "core.hooksPath", str(hooks))
    h.server = Server(["--repo", str(repo), "--port", "0", "--web-dir", str(_web_dir(base))])
    yield h
    h.server.stop()


def _clear(marks: Path) -> None:
    for m in marks.iterdir():
        m.unlink()


def test_premise_plain_git_runs_the_planted_hook_and_fsmonitor(hostile):
    """前提: 素の git の update-ref・status で、仕込んだ hook と fsmonitor が動く。"""
    _clear(hostile.marks)
    _git(hostile.repo, "update-ref", "refs/scratch/x", "HEAD")
    _git(hostile.repo, "update-ref", "-d", "refs/scratch/x")
    assert (hostile.marks / "hooks").exists()
    (hostile.repo / "tracked.md").write_text("t\nchanged\n", encoding="utf-8")
    _git(hostile.repo, "status", "--porcelain", check=False)
    _git(hostile.repo, "checkout", "--", "tracked.md")
    assert (hostile.marks / "fsmonitor").exists()
    _clear(hostile.marks)


RECORD_MERGE_JS = f"""
const V = await import({json.dumps((APP / "git-view.ts").as_uri())});
const R = await import({json.dumps((APP / "review-api.ts").as_uri())});
const repo = await V.openRepo(arg.repo);
const ok = await R.recordMerge(
	{{ repo, prKey: arg.pr.prKey, branch: arg.pr.branch, target: "develop",
		sourceOid: arg.pr.sourceOid, targetOid: arg.pr.targetOid, baseOid: arg.pr.baseOid }},
	{{ requestId: randomUUID(), message: "m", cleanup: "none", commit: arg.pr.sourceOid }},
);
out(ok);
"""


def test_reads_and_the_merge_record_never_run_planted_commands(hostile, tmp_path):
    _clear(hostile.marks)
    status, body = hostile.server.get("/api/prs")
    assert status == 200 and len(body["prs"]) == 1
    pr = body["prs"][0]
    assert hostile.server.get(f"/api/prs/{pr['id']}/diff?path=README.md")[0] == 200
    assert call(hostile.server, f"/api/prs/{pr['id']}/review", method="GET")[0] == 200
    # 残る書き込み（統合の記録）は、アプリの git アダプタ（appendEvents）で ref を書く
    assert (
        run_js(tmp_path, hostile.repo, RECORD_MERGE_JS, {"repo": str(hostile.repo), "pr": pr})
        is True
    )
    assert sorted(p.name for p in hostile.marks.iterdir()) == []  # 印ができていない
    assert "refs/pi/review/" in _git(hostile.repo, "for-each-ref")  # 書き込み自体は行われた
    assert [e["t"] for e in ref_events(hostile.repo, pr)] == ["merge_request", "merge_result"]
    assert call(hostile.server, f"/api/prs/{pr['id']}/review", method="GET")[1]["merged"] is True


# ---------------------------------------------------------------- パスの非漏洩・import 境界


def test_no_absolute_path_in_any_response(world, mworld):
    pr = new_pr(world)
    review(world, pr)
    # 失敗の応答（壊れた JSON・別の Origin）にも、パスや内部の情報を含めない
    texts = list(world.texts)
    for kw in ({"raw": b"{"}, {"origin": "http://evil.example"}, {"host": "evil.example"}):
        status, resp = plan(mworld, **kw)
        assert status in (400, 403), kw
        texts.append(json.dumps(resp, ensure_ascii=False))
    assert len(texts) >= 4
    joined = "\n".join(texts)
    for needle in (
        str(world.base),
        str(world.repo.resolve()),
        str(world.base.resolve()),
        str(mworld.base),
        "/tmp/",
        "/home/",
    ):
        assert needle not in joined
    assert "node:" not in joined and "Error:" not in joined and "at async" not in joined


ALLOWED_HARNESS = {"review-log.ts", "review-git.ts"}


def test_app_imports_only_the_two_shared_review_libraries():
    sources = [p for p in APP.glob("*.ts")]
    assert {p.name for p in sources} >= {"server.ts", "routes.ts", "git-view.ts", "review-api.ts"}
    imported: set[str] = set()
    for p in sources:
        text = p.read_text(encoding="utf-8")
        # 先頭の from/import だけを拾う（`query.get("from")` のような文字列リテラルを import と誤認しない）
        for m in re.finditer(r"""(?:\bfrom\s+|\bimport\s*\(?\s*)["']([^"']+)["']""", text):
            spec = m.group(1)
            if "harness" in spec:
                assert spec.startswith("../../home/dot_config/pi/harness/"), (p.name, spec)
                imported.add(spec.rsplit("/", 1)[1])
            else:
                assert spec.startswith(("./", "node:")), (p.name, spec)  # npm の依存を足さない
        for forbidden in (
            "pending-",
            "integrate-",
            "exclusive-lock",
            "native-action",
            "board-collect",
            "worktree.ts",
        ):
            assert forbidden not in "\n".join(
                re.findall(r"""["'][^"'\n]*harness[^"'\n]*["']""", text)
            ), (p.name, forbidden)
    assert imported == ALLOWED_HARNESS
    harness_deps = set()
    for name in ALLOWED_HARNESS:
        text = (ROOT / "home" / "dot_config" / "pi" / "harness" / name).read_text(encoding="utf-8")
        harness_deps |= set(re.findall(r"""from\s+["'](\./[^"']+)["']""", text))
    assert harness_deps <= {"./review-log.ts"}  # 共有ライブラリがさらに別の harness を引かない
    # review-git.ts への書き込みは appendEvents だけ: アプリが ref を直接更新する git の呼び出しを持たない
    api = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sources
        if p.name in ("review-api.ts", "routes.ts", "server.ts")
    )
    assert "update-ref" not in api and "commit-tree" not in api and "hash-object" not in api
