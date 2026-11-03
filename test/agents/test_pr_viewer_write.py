"""PR ビューア 段 2（サーバの書き込み API）の試験。

使い捨てのリポジトリ（tmp_path。名前・メールは架空）で node のサーバを起動し、HTTP で確かめる。
契約: .tmp/keep/prv-app/api-contract-write.md。receipt や pi の返信は、共有ライブラリの node スクリプトで直接追記して作る。
"""

from __future__ import annotations

import hashlib
import http.client
import itertools
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pi_review_git import PRELUDE
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
SECRET = "leak-leak-leak-leak"


# ---------------------------------------------------------------- 道具


def call(server, path, method="POST", body=None, *, headers=None, raw=None, host="127.0.0.1"):
    """書き込み用の HTTP 呼び出し。headers の値が None のものは送らない。"""
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
    _git(w.repo, "worktree", "add", "-q", str(base / "wt-two"), "-b", "scratch/wt")
    w.server = Server(["--repo", str(w.repo), "--port", "0", "--web-dir", str(_web_dir(base))])
    w.texts = []  # 応答の全文（パスの非漏洩の検査用）
    yield w
    w.server.stop()


def new_pr(w: World) -> dict:
    """新しい PR（feature/tN）を作って、その PrSummary を返す。"""
    name = f"feature/t{next(_counter)}"
    _make_branch(w.repo, name)
    status, body = w.server.get("/api/prs")
    assert status == 200
    return next(p for p in body["prs"] if p["branch"] == name)


def blobs_of(w: World, pr: dict, path: str) -> dict:
    status, body = w.server.get(f"/api/prs/{pr['id']}/diff?path={path}")
    assert status == 200
    return body


def post(w: World, pr: dict, what: str, body, **kw):
    status, resp = call(w.server, f"/api/prs/{pr['id']}/{what}", body=body, **kw)
    w.texts.append(json.dumps(resp, ensure_ascii=False))
    return status, resp


def review(w: World, pr: dict) -> dict:
    status, body = w.server.get(f"/api/prs/{pr['id']}/review")
    assert status == 200
    w.texts.append(json.dumps(body, ensure_ascii=False))
    return body


def anchor_of(w: World, pr: dict, path="README.md", side="new", line=2, line_end=None) -> dict:
    d = blobs_of(w, pr, path)
    return {
        "path": path,
        "side": side,
        "blob": d["newBlob" if side == "new" else "oldBlob"],
        "line": line,
        "lineEnd": line_end or line,
    }


def refs_of(repo: Path) -> str:
    return _git(repo, "for-each-ref")


def ref_events(repo: Path, pr: dict) -> list[dict]:
    text = _git(repo, "cat-file", "blob", f"refs/pi/review/{pr['prKey']}:events.jsonl")
    return [json.loads(line) for line in text.splitlines()]


def current_vs(pr: dict) -> dict:
    return {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}


def uuid_like() -> str:
    return "00000000-0000-4000-8000-" + f"{next(_counter):012d}"


# ---------------------------------------------------------------- diff の blob


def test_diff_has_old_and_new_blob_for_each_status(world):
    pr = new_pr(world)
    base, src = pr["baseOid"], pr["sourceOid"]

    def rp(rev: str) -> str:
        return _git(world.repo, "rev-parse", rev).strip()

    m = blobs_of(world, pr, "README.md")
    assert (m["oldBlob"], m["newBlob"]) == (rp(f"{base}:README.md"), rp(f"{src}:README.md"))
    a = blobs_of(world, pr, "docs/new.txt")
    assert (a["oldBlob"], a["newBlob"]) == (None, rp(f"{src}:docs/new.txt"))
    d = blobs_of(world, pr, "gone.txt")
    assert (d["oldBlob"], d["newBlob"]) == (rp(f"{base}:gone.txt"), None)
    r = blobs_of(world, pr, "renamed.txt")
    assert (r["oldBlob"], r["newBlob"]) == (rp(f"{base}:old.txt"), rp(f"{src}:renamed.txt"))
    assert (
        m["path"] == "README.md" and m["binary"] is False and m["truncated"] is False and m["hunks"]
    )  # 段 1 のフィールド


# ---------------------------------------------------------------- 書き込みの共通規則


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
def test_missing_or_wrong_headers_are_400_and_write_nothing(world, headers):
    pr = new_pr(world)
    before = refs_of(world.repo)
    for what, body in (("comments", {"body": "x"}), ("submit", {"kind": "changes"})):
        status, resp = post(world, pr, what, body, headers=headers)
        assert status == 400 and resp["error"]["code"] == "bad_request"
    assert refs_of(world.repo) == before


def test_charset_in_content_type_is_accepted(world):
    pr = new_pr(world)
    status, _ = post(
        world,
        pr,
        "comments",
        {"body": "x"},
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert status == 201


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "http://127.0.0.1:1", "null", "http://localhost", "x"]
)
def test_foreign_origin_is_403_and_writes_nothing(world, origin):
    pr = new_pr(world)
    before = refs_of(world.repo)
    status, resp = post(world, pr, "comments", {"body": "x"}, headers={"Origin": origin})
    assert status == 403 and resp["error"]["code"] == "forbidden_origin"
    assert refs_of(world.repo) == before


def test_same_origin_and_no_origin_are_accepted(world):
    pr = new_pr(world)
    own = f"http://127.0.0.1:{world.server.port}"
    assert (
        post(
            world,
            pr,
            "comments",
            {"body": "a"},
            headers={"Origin": own},
            host=f"127.0.0.1:{world.server.port}",
        )[0]
        == 201
    )
    assert post(world, pr, "comments", {"body": "b"})[0] == 201


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "10.0.0.1"])
def test_disallowed_host_is_403_for_post(world, host):
    pr = new_pr(world)
    before = refs_of(world.repo)
    status, resp = post(world, pr, "comments", {"body": "x"}, host=host)
    assert status == 403 and resp["error"]["code"] == "forbidden_host"
    assert refs_of(world.repo) == before


def test_too_large_body_is_413(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    big = json.dumps({"body": "x" * (64 * 1024)}).encode("utf-8")
    status, resp = post(world, pr, "comments", None, raw=big)
    assert status == 413 and resp["error"]["code"] == "too_large"
    assert refs_of(world.repo) == before
    just = json.dumps({"body": "x" * 7000}).encode("utf-8")  # 64 KB 未満は通る
    assert post(world, pr, "comments", None, raw=just)[0] == 201


@pytest.mark.parametrize("raw", [b"{", b"", b"not json", b'{"body": "x"', b"\xff\xfe"])
def test_broken_json_is_400(world, raw):
    pr = new_pr(world)
    before = refs_of(world.repo)
    status, resp = post(world, pr, "comments", None, raw=raw)
    assert status == 400 and resp["error"]["code"] == "bad_json"
    assert refs_of(world.repo) == before


@pytest.mark.parametrize("raw", [b"[]", b"1", b'"x"', b"null"])
def test_json_that_is_not_an_object_is_400(world, raw):
    pr = new_pr(world)
    for what in ("comments", "submit"):
        status, resp = post(world, pr, what, None, raw=raw)
        assert status == 400 and resp["error"]["code"] == "bad_request"


def test_only_the_two_posts_are_allowed(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    base = f"/api/prs/{pr['id']}"
    cases = [
        ("POST", "/api/repos"),
        ("POST", "/api/prs"),
        ("POST", base),
        ("POST", f"{base}/review"),
        ("POST", f"{base}/diff?path=README.md"),
        ("POST", f"{base}/merge"),
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
    assert refs_of(world.repo) == before


def test_get_on_post_routes_is_not_a_write(world):
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
    assert (
        body["review"] == "none"
        and body["threads"] == []
        and body["batches"] == []
        and body["unsent"] == 0
    )
    assert body["summary"] is None and body["merged"] is False and body["stale"] is False
    assert body["staleParts"] == {"source": False, "target": False, "base": False}
    status, headers, _ = world.server.request(f"/api/prs/{pr['id']}/review")
    assert status == 200 and headers["cache-control"] == "no-store"
    assert world.server.get(f"/api/prs/{_repo_id(world.repo)}/p{'0' * 16}/review")[0] == 404
    assert world.server.get("/api/prs/r00000000/pzz/review")[0] == 400
    assert refs_of(world.repo) == before


# ---------------------------------------------------------------- 書き込みの範囲


def test_writes_touch_only_refs_pi_review(world):
    pr = new_pr(world)
    before = {r.split()[-1]: r for r in refs_of(world.repo).splitlines()}
    state = {
        "head": (world.repo / ".git" / "HEAD").read_text(encoding="utf-8"),
        "config": (world.repo / ".git" / "config").read_text(encoding="utf-8"),
        "status": _git(world.repo, "status", "--porcelain"),
        "index": hashlib.sha256((world.repo / ".git" / "index").read_bytes()).hexdigest(),
    }
    assert post(world, pr, "comments", {"body": "a", "anchor": anchor_of(world, pr)})[0] == 201
    assert post(world, pr, "submit", {"kind": "changes"})[0] == 201
    after = {r.split()[-1]: r for r in refs_of(world.repo).splitlines()}
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {f"refs/pi/review/{pr['prKey']}"}
    assert state == {
        "head": (world.repo / ".git" / "HEAD").read_text(encoding="utf-8"),
        "config": (world.repo / ".git" / "config").read_text(encoding="utf-8"),
        "status": _git(world.repo, "status", "--porcelain"),
        "index": hashlib.sha256((world.repo / ".git" / "index").read_bytes()).hexdigest(),
    }
    assert not (world.repo / "docs" / "new.txt").exists()  # 作業ツリーは develop のまま


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
        ["worktree", "list", "--porcelain"],
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


# ---------------------------------------------------------------- コメント


def test_new_thread_reply_and_pr_wide_comment(world):
    pr = new_pr(world)
    anchor = anchor_of(world, pr, line=2, line_end=3)
    status, resp = post(world, pr, "comments", {"body": "ここを直す", "anchor": anchor})
    assert status == 201
    c = resp["comment"]
    assert (
        c["by"] == "app"
        and c["thread"] == c["id"]
        and c["body"] == "ここを直す"
        and c["anchor"] == anchor
    )
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", c["at"])
    status, reply = post(world, pr, "comments", {"body": "返信", "thread": c["id"]})
    assert (
        status == 201
        and reply["comment"]["thread"] == c["id"]
        and reply["comment"]["anchor"] is None
    )
    for pr_wide in ({"body": "全体 1"}, {"body": "全体 2", "anchor": None}):
        status, resp = post(world, pr, "comments", pr_wide)
        assert (
            status == 201
            and resp["comment"]["anchor"] is None
            and resp["comment"]["thread"] == resp["comment"]["id"]
        )
    rv = review(world, pr)
    assert [len(t["comments"]) for t in rv["threads"]] == [2, 1, 1]
    first = rv["threads"][0]
    assert first["id"] == c["id"] and first["status"] == "unsent" and first["stale"] is False
    assert first["comments"][0] == {
        "id": c["id"],
        "by": "app",
        "at": c["at"],
        "body": "ここを直す",
        "anchor": anchor,
    }
    assert rv["unsent"] == 4


def test_client_supplied_by_vs_id_are_ignored_and_meta_is_server_made(world):
    pr = new_pr(world)
    fake = {"source": "a" * 40, "target": "b" * 40, "base": "c" * 40}
    status, resp = post(
        world,
        pr,
        "comments",
        {"body": "x", "by": "pi", "id": "mine", "vs": fake, "at": "2020-01-01T00:00:00Z"},
    )
    assert status == 201 and resp["comment"]["by"] == "app" and resp["comment"]["id"] != "mine"
    (ev,) = ref_events(world.repo, pr)
    assert (
        ev["by"] == "app"
        and ev["vs"] == current_vs(pr)
        and ev["at"] != "2020-01-01T00:00:00Z"
        and ev["t"] == "comment"
    )
    meta = json.loads(
        _git(world.repo, "cat-file", "blob", f"refs/pi/review/{pr['prKey']}:meta.json")
    )
    assert set(meta) == {"schema", "pr", "branch", "target", "createdAt"}
    assert (meta["schema"], meta["pr"], meta["branch"], meta["target"]) == (
        1,
        pr["prKey"],
        pr["branch"],
        "develop",
    )
    tree = _git(world.repo, "ls-tree", f"refs/pi/review/{pr['prKey']}")
    assert sorted(line.split("\t")[1] for line in tree.splitlines()) == [
        "events.jsonl",
        "meta.json",
    ]


def test_body_is_plain_text_and_stored_as_is(world):
    pr = new_pr(world)
    body = '<script>alert(1)</script> <b>x</b> **強調** &amp; "引用" \\n\n2 行目'
    status, resp = post(world, pr, "comments", {"body": body})
    assert status == 201 and resp["comment"]["body"] == body
    assert review(world, pr)["threads"][0]["comments"][0]["body"] == body
    assert ref_events(world.repo, pr)[0]["d"]["body"] == body
    status, headers, _ = world.server.request(f"/api/prs/{pr['id']}/review")
    assert (
        headers["content-type"].startswith("application/json")
        and headers["x-content-type-options"] == "nosniff"
    )
    assert "default-src 'self'" in headers["content-security-policy"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"body": ""},
        {"body": "   \n\t"},
        {"body": None},
        {"body": 1},
        {"body": ["x"]},
        {"body": "x" * 8001},
        {"body": "あ" * 6000},  # 文字数は足りるが 16 KB を超える
    ],
)
def test_invalid_body_is_400(world, body):
    pr = new_pr(world)
    before = refs_of(world.repo)
    status, resp = post(world, pr, "comments", body)
    assert status == 400 and resp["error"]["code"] == "bad_body"
    assert refs_of(world.repo) == before


def test_body_boundary_is_accepted(world):
    pr = new_pr(world)
    assert post(world, pr, "comments", {"body": "x" * 8000})[0] == 201
    assert post(world, pr, "comments", {"body": "あ" * 5000})[0] == 201  # 15000 バイト


def _bad_anchors(w: World, pr: dict) -> dict[str, dict]:
    ok = anchor_of(w, pr)
    wrong = "f" * 40
    return {
        "blob_mismatch": {**ok, "blob": wrong},
        "blob_of_other_side": {**ok, "side": "old"},
        "blob_short": {**ok, "blob": ok["blob"][:10]},
        "blob_missing": {k: v for k, v in ok.items() if k != "blob"},
        "path_not_in_diff": {**ok, "path": "keep.txt"},
        "path_unknown": {**ok, "path": "nope.txt"},
        "path_traversal": {**ok, "path": "../README.md"},
        "path_absolute": {**ok, "path": "/etc/passwd"},
        "path_not_string": {**ok, "path": 1},
        "line_gt_end": {**ok, "line": 5, "lineEnd": 2},
        "line_zero": {**ok, "line": 0, "lineEnd": 1},
        "line_negative": {**ok, "line": -1, "lineEnd": 1},
        "line_float": {**ok, "line": 1.5, "lineEnd": 2},
        "line_string": {**ok, "line": "2", "lineEnd": "2"},
        "line_missing": {k: v for k, v in ok.items() if k != "line"},
        "lineend_missing": {k: v for k, v in ok.items() if k != "lineEnd"},
        "side_both": {**ok, "side": "both"},
        "side_missing": {k: v for k, v in ok.items() if k != "side"},
        "old_side_of_added_file": {
            "path": "docs/new.txt",
            "side": "old",
            "blob": blobs_of(w, pr, "docs/new.txt")["newBlob"],
            "line": 1,
            "lineEnd": 1,
        },
        "new_side_of_deleted_file": {
            "path": "gone.txt",
            "side": "new",
            "blob": blobs_of(w, pr, "gone.txt")["oldBlob"],
            "line": 1,
            "lineEnd": 1,
        },
        "not_object": "README.md",
        "list": [ok],
        "number": 1,
    }


def test_invalid_anchors_are_400_and_write_nothing(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    for name, anchor in _bad_anchors(world, pr).items():
        status, resp = post(world, pr, "comments", {"body": SECRET, "anchor": anchor})
        assert status == 400 and resp["error"]["code"] == "bad_anchor", name
        assert SECRET not in json.dumps(resp) and "README" not in resp["error"]["message"]
    assert refs_of(world.repo) == before


def test_old_side_and_renamed_file_anchors_are_accepted(world):
    pr = new_pr(world)
    old = anchor_of(world, pr, path="README.md", side="old", line=1)
    assert post(world, pr, "comments", {"body": "旧", "anchor": old})[0] == 201
    renamed_old = anchor_of(world, pr, path="renamed.txt", side="old", line=4)
    assert post(world, pr, "comments", {"body": "改名の旧", "anchor": renamed_old})[0] == 201
    deleted = anchor_of(world, pr, path="gone.txt", side="old", line=1)
    assert post(world, pr, "comments", {"body": "削除", "anchor": deleted})[0] == 201
    added = anchor_of(world, pr, path="docs/new.txt", side="new", line=1)
    assert post(world, pr, "comments", {"body": "追加", "anchor": added})[0] == 201


def test_a_blob_from_another_pr_is_refused(world):
    a, b = new_pr(world), new_pr(world)
    mine = anchor_of(world, a)
    # 内容が同じなので blob は同じ。別の内容を足したブランチで、内容が違えば断られる
    _git(world.repo, "switch", "-q", "-c", "feature/other-content", "develop")
    _commit(world.repo, {"README.md": "hello\nother\nworld\n"}, "feat: other")
    _git(world.repo, "switch", "-q", "develop")
    status, body = world.server.get("/api/prs")
    other = next(p for p in body["prs"] if p["branch"] == "feature/other-content")
    status, resp = post(world, other, "comments", {"body": "x", "anchor": mine})
    assert status == 400 and resp["error"]["code"] == "bad_anchor"
    assert (
        post(world, b, "comments", {"body": "x", "anchor": mine})[0] == 201
    )  # 同じ内容の blob なら通る（blob の一致を見ている）


def test_bad_replies_are_400(world):
    pr = new_pr(world)
    _, first = post(world, pr, "comments", {"body": "親"})
    tid = first["comment"]["id"]
    # 返信の id（スレッドの最初のコメントではない）は使えない
    _, reply = post(world, pr, "comments", {"body": "返信", "thread": tid})
    for thread in (reply["comment"]["id"], uuid_like(), "x", "", 1, ["a"], {"a": 1}):
        status, resp = post(world, pr, "comments", {"body": "x", "thread": thread})
        assert status == 400 and resp["error"]["code"] == "bad_thread", thread
    status, resp = post(
        world, pr, "comments", {"body": SECRET, "thread": tid, "anchor": anchor_of(world, pr)}
    )
    assert (
        status == 400 and resp["error"]["code"] == "bad_anchor" and SECRET not in json.dumps(resp)
    )
    assert len(review(world, pr)["threads"]) == 1


# ---------------------------------------------------------------- 送信


def test_submit_bundles_unsent_comments_into_one_batch(world):
    pr = new_pr(world)
    ids = [post(world, pr, "comments", {"body": f"c{i}"})[1]["comment"]["id"] for i in range(3)]
    status, resp = post(world, pr, "submit", {"kind": "comment"})
    assert status == 201 and resp["kind"] == "comment" and resp["items"] == ids
    assert re.match(r"^[0-9a-f-]{36}$", resp["batchId"])
    rv = review(world, pr)
    assert rv["unsent"] == 0 and [t["status"] for t in rv["threads"]] == ["sent"] * 3
    assert rv["review"] == "none"  # comment の送信ではレビュー状態は変わらない
    assert [b["items"] for b in rv["batches"]] == [ids] and rv["batches"][0]["received"] is False
    # 2 回目: 項目が無いので断る
    status, resp = post(world, pr, "submit", {"kind": "comment"})
    assert status == 400 and resp["error"]["code"] == "nothing_to_send"
    # 送信後に足したコメントは次の batch にだけ入る
    new_id = post(world, pr, "comments", {"body": "後から"})[1]["comment"]["id"]
    assert review(world, pr)["unsent"] == 1
    status, second = post(world, pr, "submit", {"kind": "comment"})
    assert status == 201 and second["items"] == [new_id] and not set(second["items"]) & set(ids)
    assert [b["items"] for b in review(world, pr)["batches"]] == [ids, [new_id]]


def test_replies_in_existing_threads_are_sent_too(world):
    pr = new_pr(world)
    root = post(world, pr, "comments", {"body": "親"})[1]["comment"]["id"]
    post(world, pr, "submit", {"kind": "comment"})
    reply = post(world, pr, "comments", {"body": "返信", "thread": root})[1]["comment"]["id"]
    status, resp = post(world, pr, "submit", {"kind": "changes"})
    assert status == 201 and resp["items"] == [reply]


def test_empty_submit_rules(world):
    pr = new_pr(world)
    before = refs_of(world.repo)
    status, resp = post(world, pr, "submit", {"kind": "comment"})
    assert status == 400 and resp["error"]["code"] == "nothing_to_send"
    assert refs_of(world.repo) == before  # 断った送信は ref も作らない
    status, resp = post(world, pr, "submit", {"kind": "changes"})
    assert status == 201 and resp["items"] == []
    assert review(world, pr)["review"] == "changes"
    status, resp = post(world, pr, "submit", {"kind": "approve"})
    assert status == 201 and resp["items"] == []
    rv = review(world, pr)
    assert rv["review"] == "approve" and rv["reviewStale"] is False and len(rv["batches"]) == 2
    (b1, b2) = ref_events(world.repo, pr)
    assert (
        b1["d"]["kind"] == "changes"
        and b2["d"]["kind"] == "approve"
        and b2["by"] == "app"
        and b2["vs"] == current_vs(pr)
    )


def test_approve_is_only_a_review_record(world):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "x"})
    before = {r for r in refs_of(world.repo).splitlines() if "refs/pi/review" not in r}
    status, resp = post(world, pr, "submit", {"kind": "approve"})
    assert status == 201 and len(resp["items"]) == 1
    assert {
        r for r in refs_of(world.repo).splitlines() if "refs/pi/review" not in r
    } == before  # 統合はしない
    assert _git(world.repo, "rev-parse", pr["branch"]).strip() == pr["sourceOid"]
    assert not any(e["t"].startswith("merge") for e in ref_events(world.repo, pr))
    assert review(world, pr)["merged"] is False


@pytest.mark.parametrize("kind", [None, "", "merge", "COMMENT", 1, ["comment"]])
def test_bad_kind_is_400(world, kind):
    pr = new_pr(world)
    status, resp = post(world, pr, "submit", {"kind": kind})
    assert status == 400 and resp["error"]["code"] == "bad_kind"
    assert post(world, pr, "submit", {})[1]["error"]["code"] == "bad_kind"


def test_dest_candidates_default_and_validation(world):
    pr = new_pr(world)
    rv = review(world, pr)
    main_id = hashlib.sha256(str(world.repo.resolve()).encode()).hexdigest()[:16]
    other_id = hashlib.sha256(str((world.base / "wt-two").resolve()).encode()).hexdigest()[:16]
    assert rv["worktrees"] == [
        {"worktreeId": main_id, "name": "example-app", "isMain": True},
        {"worktreeId": other_id, "name": "wt-two", "isMain": False},
    ]
    assert rv["defaultDest"] == {"worktreeId": main_id}
    post(world, pr, "comments", {"body": "a"})
    for dest in (
        {"worktreeId": "0" * 16},
        {"worktreeId": ""},
        {"worktreeId": 1},
        {},
        "x",
        ["a"],
        {"worktreeId": str(world.repo)},
    ):
        status, resp = post(world, pr, "submit", {"kind": "comment", "dest": dest})
        assert status == 400 and resp["error"]["code"] == "bad_dest", dest
    assert review(world, pr)["batches"] == []
    status, resp = post(world, pr, "submit", {"kind": "comment", "dest": {"worktreeId": other_id}})
    assert status == 201 and resp["dest"] == {"worktreeId": other_id}
    post(world, pr, "comments", {"body": "b"})
    status, resp = post(world, pr, "submit", {"kind": "comment"})
    assert status == 201 and resp["dest"] == {"worktreeId": main_id}
    assert [b["dest"]["worktreeId"] for b in review(world, pr)["batches"]] == [other_id, main_id]


def test_resend_of(world):
    pr = new_pr(world)
    ids = [post(world, pr, "comments", {"body": f"c{i}"})[1]["comment"]["id"] for i in range(2)]
    first = post(world, pr, "submit", {"kind": "comment"})[1]
    post(world, pr, "comments", {"body": "未送信"})
    for bad_id in (uuid_like(), "x", "", 1, ["a"]):
        status, resp = post(world, pr, "submit", {"kind": "comment", "resendOf": bad_id})
        assert status == 400 and resp["error"]["code"] == "bad_resend", bad_id
    status, again = post(world, pr, "submit", {"kind": "comment", "resendOf": first["batchId"]})
    assert status == 201 and again["batchId"] != first["batchId"] and again["items"] == ids
    batches = review(world, pr)["batches"]
    assert batches[1]["resendOf"] == first["batchId"] and "resendOf" not in batches[0]
    assert review(world, pr)["unsent"] == 1  # 再送では、新しい未送信は消えない


def test_four_concurrent_posts_keep_every_comment(world):
    pr = new_pr(world)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda i: post(world, pr, "comments", {"body": f"同時 {i}"}), range(4))
        )
    assert [s for s, _ in results] == [201] * 4
    rv = review(world, pr)
    assert sorted(t["comments"][0]["body"] for t in rv["threads"]) == [
        f"同時 {i}" for i in range(4)
    ]
    assert len({t["id"] for t in rv["threads"]}) == 4
    assert len(ref_events(world.repo, pr)) == 4


def test_concurrent_comments_and_submits_neither_lose_nor_duplicate(world):
    pr = new_pr(world)
    jobs = [
        ("comments", {"body": "a"}),
        ("comments", {"body": "b"}),
        ("submit", {"kind": "changes"}),
        ("submit", {"kind": "changes"}),
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda j: post(world, pr, j[0], j[1]), jobs))
    assert [s for s, _ in results] == [201] * 4
    events = ref_events(world.repo, pr)
    assert len(events) == 4 and len({e["id"] for e in events}) == 4
    items = [i for e in events if e["t"] == "submit" for i in e["d"]["items"]]
    assert len(items) == len(set(items))  # 同じコメントが 2 つの batch に入らない
    rv = review(world, pr)
    assert rv["unsent"] == 2 - len(items)


# ---------------------------------------------------------------- 状態


def test_thread_status_progresses_unsent_sent_read_replied(world, tmp_path):
    pr = new_pr(world)
    vs = current_vs(pr)
    t_sent = post(world, pr, "comments", {"body": "送信済みのまま"})[1]["comment"]["id"]
    b1 = post(world, pr, "submit", {"kind": "comment"})[1]
    t_read = post(world, pr, "comments", {"body": "読まれる"})[1]["comment"]["id"]
    t_replied = post(world, pr, "comments", {"body": "返信される"})[1]["comment"]["id"]
    b2 = post(world, pr, "submit", {"kind": "comment"})[1]
    t_unsent = post(world, pr, "comments", {"body": "未送信"})[1]["comment"]["id"]
    states = {t["id"]: t["status"] for t in review(world, pr)["threads"]}
    assert states == {t_sent: "sent", t_read: "sent", t_replied: "sent", t_unsent: "unsent"}
    run_js(
        tmp_path,
        world.repo,
        """
        const key = L.prKeyOf(arg.branch);
        const r1 = await G.appendEvents(git, key, meta(arg.branch), () => [
            ev("receipt", { batchId: arg.b2, sessionId: "s-1" }, { vs: arg.vs }),
        ]);
        const r2 = await G.appendEvents(git, key, meta(arg.branch), () => [
            ev("comment", { thread: arg.replied, anchor: null, body: "pi の返信" }, { vs: arg.vs }),
        ]);
        out([r1.ok, r2.ok]);
        """,
        {"branch": pr["branch"], "b2": b2["batchId"], "replied": t_replied, "vs": vs},
    )
    rv = review(world, pr)
    assert {t["id"]: t["status"] for t in rv["threads"]} == {
        t_sent: "sent",
        t_read: "read",
        t_replied: "replied",
        t_unsent: "unsent",
    }
    replied = next(t for t in rv["threads"] if t["id"] == t_replied)
    assert [c["by"] for c in replied["comments"]] == ["app", "pi"] and replied["comments"][1][
        "body"
    ] == "pi の返信"
    by_id = {b["batchId"]: b for b in rv["batches"]}
    assert by_id[b2["batchId"]]["received"] is True and by_id[b2["batchId"]]["sessionId"] == "s-1"
    assert by_id[b1["batchId"]]["received"] is False
    assert rv["unsent"] == 1
    # 利用者が受領後に足したコメントでは「返信済み」にならない
    post(world, pr, "comments", {"body": "利用者の追記", "thread": t_read})
    assert {t["id"]: t["status"] for t in review(world, pr)["threads"]}[t_read] == "read"
    # pi が書いたコメントは送信の項目に入らない（利用者の 2 件だけ）
    status, sub = post(world, pr, "submit", {"kind": "changes"})
    assert status == 201 and len(sub["items"]) == 2 and t_unsent in sub["items"]
    assert review(world, pr)["unsent"] == 0


def test_pi_summary_is_returned(world, tmp_path):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "x"})
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


def test_review_stale_and_thread_stale_follow_the_branch(world):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "古くなる"})
    post(world, pr, "submit", {"kind": "changes"})
    rv = review(world, pr)
    assert (rv["review"], rv["reviewStale"], rv["stale"]) == ("changes", False, False)
    _git(world.repo, "switch", "-q", pr["branch"])
    _commit(world.repo, {"keep.txt": "keep\nmore\n"}, "feat: more")
    _git(world.repo, "switch", "-q", "develop")
    rv = review(world, pr)
    assert rv["reviewStale"] is True and rv["stale"] is True and rv["staleParts"]["source"] is True
    assert rv["staleParts"]["target"] is False and rv["staleParts"]["base"] is False
    assert rv["threads"][0]["stale"] is True and rv["review"] == "changes"
    # 新しい版で足したコメントは古くない。最後のレビューは古いまま
    new_pr_info = next(p for p in world.server.get("/api/prs")[1]["prs"] if p["id"] == pr["id"])
    assert new_pr_info["sourceOid"] != pr["sourceOid"]
    assert post(world, new_pr_info, "comments", {"body": "新しい版"})[0] == 201
    rv = review(world, new_pr_info)
    assert (
        rv["stale"] is False
        and rv["reviewStale"] is True
        and [t["stale"] for t in rv["threads"]] == [True, False]
    )
    assert ref_events(world.repo, pr)[-1]["vs"]["source"] == new_pr_info["sourceOid"]
    # 新しい source は、この記録の commit の追加の親になる。古い source は、最初の記録の commit が親として持つ
    # (どちらも ref から到達できる。古い diff も、最後にレビューした版も gc 後に残る)
    parents = _git(
        world.repo, "rev-list", "--parents", "-n", "1", f"refs/pi/review/{pr['prKey']}"
    ).split()
    assert new_pr_info["sourceOid"] in parents[2:]
    _git(
        world.repo, "merge-base", "--is-ancestor", pr["sourceOid"], f"refs/pi/review/{pr['prKey']}"
    )


# ---------------------------------------------------------------- 断る場合

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


def test_merged_pr_refuses_writes_with_409(world, tmp_path):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "先に 1 件"})
    assert (
        run_js(
            tmp_path,
            world.repo,
            MERGE_JS,
            {"branch": pr["branch"], "vs": current_vs(pr), "outcome": "success"},
        )
        is True
    )
    rv = review(world, pr)
    assert rv["merged"] is True
    before = refs_of(world.repo)
    for what, body in (
        ("comments", {"body": SECRET}),
        ("submit", {"kind": "changes"}),
        ("submit", {"kind": "comment"}),
    ):
        status, resp = post(world, pr, what, body)
        assert (
            status == 409 and resp["error"]["code"] == "merged" and SECRET not in json.dumps(resp)
        ), (what, body)
    assert refs_of(world.repo) == before


def test_a_failed_merge_does_not_block_writes(world, tmp_path):
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
    assert post(world, pr, "comments", {"body": "続けられる"})[0] == 201


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


def test_selfcheck_failure_is_409_bad_state(world):
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
    assert (
        isinstance(rv["bad"], str) and rv["bad"] and rv["threads"] == [] and rv["readonly"] is False
    )
    for what, body in (("comments", {"body": SECRET}), ("submit", {"kind": "changes"})):
        status, resp = post(world, pr, what, body)
        assert (
            status == 409
            and resp["error"]["code"] == "bad_state"
            and SECRET not in json.dumps(resp)
        )
    assert refs_of(world.repo) == before


def test_invalid_event_log_is_bad_state(world):
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
    assert post(world, pr, "comments", {"body": "x"})[1]["error"]["code"] == "bad_state"


def test_newer_schema_is_readonly_409(world):
    pr = new_pr(world)
    _plant(
        world.repo,
        pr,
        [
            ("100644", "blob", _good_meta(pr, schema=2), "meta.json"),
            ("100644", "blob", "", "events.jsonl"),
        ],
    )
    before = refs_of(world.repo)
    rv = review(world, pr)
    assert rv["readonly"] is True and rv["threads"] == [] and rv["bad"] is None
    for what, body in (("comments", {"body": SECRET}), ("submit", {"kind": "changes"})):
        status, resp = post(world, pr, what, body)
        assert (
            status == 409 and resp["error"]["code"] == "readonly" and SECRET not in json.dumps(resp)
        )
    assert refs_of(world.repo) == before


def test_event_limit_is_413(world, tmp_path):
    pr = new_pr(world)
    res = run_js(
        tmp_path,
        world.repo,
        """
        const key = L.prKeyOf(arg.branch);
        let n = 0;
        for (;;) {
            const evs = [];
            for (let i = 0; i < 100; i++) evs.push(cm("x", { by: "app", vs: arg.vs }));
            const r = await G.appendEvents(git, key, meta(arg.branch), () => evs);
            if (!r.ok) { out({ refused: r.refused, n }); break; }
            n += 100;
        }
        """,
        {"branch": pr["branch"], "vs": current_vs(pr)},
    )
    assert res["n"] >= 1000
    # 末尾の 32 KB は終端用の余裕。通常のコメントは、上限の手前で 413 になる (大きい本文を続けて送る)
    before = refs_of(world.repo)
    status, resp = 201, {}
    for _ in range(12):
        before = refs_of(world.repo)
        status, resp = post(world, pr, "comments", {"body": "x" * 8000})
        if status != 201:
            break
    assert status == 413 and resp["error"]["code"] == "limit"
    assert refs_of(world.repo) == before
    rv = review(world, pr)  # 読むことはできる
    assert len(rv["threads"]) >= 1000


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


def test_writes_never_run_planted_commands(hostile):
    _clear(hostile.marks)
    status, body = hostile.server.get("/api/prs")
    assert status == 200 and len(body["prs"]) == 1
    pr = body["prs"][0]
    anchor = None
    _, diff = hostile.server.get(f"/api/prs/{pr['id']}/diff?path=README.md")
    anchor = {"path": "README.md", "side": "new", "blob": diff["newBlob"], "line": 2, "lineEnd": 2}
    for i in range(3):
        status, resp = call(
            hostile.server,
            f"/api/prs/{pr['id']}/comments",
            body={"body": f"c{i}", "anchor": anchor},
        )
        assert status == 201, resp
    status, resp = call(hostile.server, f"/api/prs/{pr['id']}/submit", body={"kind": "approve"})
    assert status == 201, resp
    assert call(hostile.server, f"/api/prs/{pr['id']}/review", method="GET")[0] == 200
    assert sorted(p.name for p in hostile.marks.iterdir()) == []  # 印ができていない
    assert "refs/pi/review/" in _git(hostile.repo, "for-each-ref")  # 書き込み自体は行われた
    assert len(ref_events(hostile.repo, pr)) == 4


# ---------------------------------------------------------------- パスの非漏洩・import 境界


def test_no_absolute_path_in_any_write_response(world):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "x", "anchor": anchor_of(world, pr)})
    post(
        world,
        pr,
        "comments",
        {
            "body": "x",
            "anchor": {"path": "../x", "side": "new", "blob": "0" * 40, "line": 1, "lineEnd": 1},
        },
    )
    post(world, pr, "submit", {"kind": "comment"})
    post(world, pr, "submit", {"kind": "comment"})
    post(world, pr, "submit", {"kind": "comment", "dest": {"worktreeId": str(world.repo)}})
    post(world, pr, "comments", None, raw=b"{")
    review(world, pr)
    assert len(world.texts) > 30
    joined = "\n".join(world.texts)
    for needle in (
        str(world.base),
        str(world.repo.resolve()),
        str(world.base.resolve()),
        "/tmp/",
        "/home/",
        "wt-two/",
    ):
        assert needle not in joined
    assert "node:" not in joined and "Error:" not in joined and "at async" not in joined
    for w in review(world, pr)["worktrees"]:
        assert set(w) == {"worktreeId", "name", "isMain"}


ALLOWED_HARNESS = {"review-log.ts", "review-git.ts"}


def test_app_imports_only_the_two_shared_review_libraries():
    sources = [p for p in APP.glob("*.ts")]
    assert {p.name for p in sources} >= {"server.ts", "routes.ts", "git-view.ts", "review-api.ts"}
    imported: set[str] = set()
    for p in sources:
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", text):
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


# ---------------------------------------------------------------- 本文の上限 (chunked) と表示版の固定 (expect)


def test_chunked_body_over_the_limit_is_413_and_writes_nothing(world):
    """Content-Length が無い (chunked) でも、ストリームの実測で 64 KB を超えたら 413。"""
    pr = new_pr(world)
    before = refs_of(world.repo)
    payload = json.dumps({"body": "x" * (96 * 1024)}).encode("utf-8")
    chunks = [payload[i : i + 8192] for i in range(0, len(payload), 8192)]
    conn = http.client.HTTPConnection("127.0.0.1", world.server.port, timeout=60)
    conn.request(
        "POST",
        f"/api/prs/{pr['id']}/comments",
        body=iter(chunks),
        headers={"Host": "127.0.0.1", "Content-Type": "application/json", "X-PRV": "1"},
        encode_chunked=True,
    )
    resp = conn.getresponse()
    status, text = resp.status, resp.read().decode("utf-8")
    conn.close()
    assert status == 413 and json.loads(text)["error"]["code"] == "too_large"
    assert refs_of(world.repo) == before


def expect_of(pr: dict, **over) -> dict:
    e = {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}
    e.update(over)
    return e


def test_expect_that_matches_is_accepted(world):
    pr = new_pr(world)
    assert post(world, pr, "comments", {"body": "合う", "expect": expect_of(pr)})[0] == 201
    assert post(world, pr, "submit", {"kind": "comment", "expect": expect_of(pr)})[0] == 201


def test_expect_is_optional(world):
    pr = new_pr(world)
    assert post(world, pr, "comments", {"body": "省略"})[0] == 201
    assert post(world, pr, "submit", {"kind": "comment"})[0] == 201


@pytest.mark.parametrize("part", ["source", "target", "base"])
@pytest.mark.parametrize("what", ["comments", "submit"])
def test_expect_that_differs_in_any_part_is_409_and_writes_nothing(world, part, what):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "先に 1 件"})
    before = refs_of(world.repo)
    body = {"body": "ずれている"} if what == "comments" else {"kind": "approve"}
    body["expect"] = expect_of(pr, **{part: "0123456789abcdef0123456789abcdef01234567"})
    status, resp = post(world, pr, what, body)
    assert status == 409 and resp["error"]["code"] == "stale_view"
    assert "更新" in resp["error"]["message"]
    assert refs_of(world.repo) == before


def test_old_expect_after_the_branch_moved_is_409(world):
    pr = new_pr(world)
    post(world, pr, "comments", {"body": "見ていた版へ"})
    _git(world.repo, "switch", "-q", pr["branch"])
    _commit(world.repo, {"keep.txt": "keep\nnext\n"}, "feat: next")
    _git(world.repo, "switch", "-q", "develop")
    before = refs_of(world.repo)
    status, resp = post(world, pr, "submit", {"kind": "approve", "expect": expect_of(pr)})
    assert status == 409 and resp["error"]["code"] == "stale_view"
    assert refs_of(world.repo) == before
    # 取り直した版なら通る
    fresh = next(p for p in world.server.get("/api/prs")[1]["prs"] if p["id"] == pr["id"])
    assert post(world, fresh, "submit", {"kind": "approve", "expect": expect_of(fresh)})[0] == 201


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        1,
        [],
        {},
        None,  # null は「省略」ではない (省略だけが照合なし)
        {"source": "a" * 40},
        {"source": "A" * 40, "target": "a" * 40, "base": "a" * 40},
        {"source": "a" * 39, "target": "a" * 40, "base": "a" * 40},
        {"source": 1, "target": "a" * 40, "base": "a" * 40},
        {"source": "a" * 40, "target": "a" * 40, "base": "a" * 40, "ref": "refs/heads/x"},
    ],
)
def test_malformed_expect_is_400_bad_expect(world, bad):
    pr = new_pr(world)
    before = refs_of(world.repo)
    for what, body in (("comments", {"body": "形"}), ("submit", {"kind": "approve"})):
        status, resp = post(world, pr, what, {**body, "expect": bad})
        assert status == 400 and resp["error"]["code"] == "bad_expect", (what, bad, status, resp)
    assert refs_of(world.repo) == before
