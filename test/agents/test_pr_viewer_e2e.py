"""PR ビューア 段 1 の結合 (サーバ ``apps/pr-viewer/server.ts`` と画面 ``apps/pr-viewer/web/``。案件 CHG-0060)。

画面の試験は、契約から作った fixture で動く。ここでは、**実サーバの応答が fixture と同じ形** (キーと型) であることと、
**既定の web ディレクトリから、画面が読み込むファイルを全部配信できる**ことを確かめる
(片方だけ契約からずれても、それぞれの試験は通ってしまうため)。

see docs/change/0060-local-pr-viewer.md
"""

from __future__ import annotations

import http.client
import json
import re

import pytest
from agents_common import ROOT
from test_pi_judge_ts import _node
from test_pr_viewer_server import Server, _commit, _git, _init

pytestmark = pytest.mark.skipif(_node() is None, reason="型除去に対応した node (22.18 以上) が無い")

FIXTURES = ROOT / "test" / "agents" / "pr_viewer_fixtures"
WEB = ROOT / "apps" / "pr-viewer" / "web"
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_shape(real, fixture, where: str = "$") -> None:
    """キーと型が同じか。None はどの型とも合う。リストは最初の要素どうしを比べる。"""
    if real is None or fixture is None:
        return
    assert type(real) is type(fixture) or (_number(real) and _number(fixture)), (
        f"{where}: 型が違う ({type(real).__name__} と {type(fixture).__name__})"
    )
    if isinstance(real, dict):
        assert set(real) == set(fixture), f"{where}: キーが違う {sorted(set(real) ^ set(fixture))}"
        for key in real:
            _same_shape(real[key], fixture[key], f"{where}.{key}")
    elif isinstance(real, list) and real and fixture:
        _same_shape(real[0], fixture[0], f"{where}[0]")


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    base = tmp_path_factory.mktemp("e2e")
    repo = _init(base / "example-app")
    _commit(repo, {"src/app.ts": "export const a = 1;\nexport const b = 2;\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/add-search")
    _commit(
        repo,
        {
            "src/app.ts": "export const a = 1;\nexport const b = 3;\n",
            "src/search.ts": "export function search() {}\n",
        },
        "feat: 検索を追加",
    )
    _git(repo, "switch", "-q", "develop")
    server = Server(
        ["--repo", str(repo), "--port", "0"]
    )  # web ディレクトリは既定 (apps/pr-viewer/web/)
    yield server
    server.stop()


def test_real_responses_have_the_same_shape_as_the_fixtures(served):
    status, repos = served.get("/api/repos")
    assert status == 200
    _same_shape(repos, _load("repos.json"), "repos")
    status, prs = served.get("/api/prs")
    assert status == 200 and len(prs["prs"]) == 1
    _same_shape(prs, _load("prs.json"), "prs")
    pr_id = prs["prs"][0]["id"]
    status, detail = served.get(f"/api/prs/{pr_id}")
    assert status == 200 and detail["files"]
    # 画面の試験の fixture サーバは、詳細に一覧の PR を `pr` として足して契約の形にしている。ここも同じ組み立てで比べる
    _same_shape(
        detail,
        {"pr": _load("prs.json")["prs"][0], **_load("detail_paaaaaaaaaaaaaaa1.json")},
        "detail",
    )
    status, diff = served.get(f"/api/prs/{pr_id}/diff?path=src/app.ts")
    assert status == 200 and diff["hunks"], "実サーバの diff に hunk が無い"
    # 段 2 で足したフィールド (null はどの型とも合う)。画面側の fixture が持っていてもいなくても通る
    fixture = {"oldBlob": None, "newBlob": None, **_load("diff_paaaaaaaaaaaaaaa1.json")}
    assert fixture["hunks"], "fixture の diff に hunk が無い"
    _same_shape(diff, fixture, "diff")


def test_the_page_is_served_with_the_files_it_loads(served):
    status, headers, body = served.request("/")
    assert status == 200 and headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in headers["content-security-policy"]
    page = body.decode("utf-8")
    loaded = re.findall(r'(?:src|href)="(/web/[^"]+)"', page)
    assert loaded, "ページが /web/ のファイルを読み込んでいない"
    for path in loaded:
        status, headers, body = served.request(path)
        assert status == 200, path
        assert headers["content-type"].startswith(TYPES[path[path.rfind(".") :]]), path
        assert body == (WEB / path.removeprefix("/web/")).read_bytes(), path


def test_every_web_file_is_in_the_servers_allowlist(served):
    names = sorted(p.name for p in WEB.iterdir() if p.is_file())
    assert "index.html" in names
    for name in names:
        status, _, _ = served.request(f"/web/{name}")
        assert status == 200, f"{name}: サーバの許可リストに合わない"


def _post(server, path: str, payload: dict):
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


def test_real_review_response_has_the_same_shape_as_the_fixture(served):
    """画面が使う `GET …/review` の形を、実サーバが実際に書いたコメントと送信で確かめる (行・返信・PR 全体・送信)。"""
    status, prs = served.get("/api/prs")
    pr_id = prs["prs"][0]["id"]
    status, diff = served.get(f"/api/prs/{pr_id}/diff?path=src/app.ts")
    assert status == 200 and diff["newBlob"], "diff の応答に newBlob が無い (anchor に使えない)"
    anchor = {"path": "src/app.ts", "side": "new", "blob": diff["newBlob"], "line": 2, "lineEnd": 2}
    status, first = _post(
        served, f"/api/prs/{pr_id}/comments", {"body": "行へのコメント", "anchor": anchor}
    )
    assert status == 201, first
    status, _ = _post(
        served, f"/api/prs/{pr_id}/comments", {"body": "返信", "thread": first["comment"]["id"]}
    )
    assert status == 201
    status, _ = _post(served, f"/api/prs/{pr_id}/comments", {"body": "全体へのコメント"})
    assert status == 201
    status, sent = _post(served, f"/api/prs/{pr_id}/submit", {"kind": "changes"})
    assert status == 201 and len(sent["items"]) == 3, sent
    status, review = served.get(f"/api/prs/{pr_id}/review")
    assert status == 200 and review["review"] == "changes" and len(review["threads"]) == 2
    assert {t["status"] for t in review["threads"]} == {"sent"}
    _same_shape(review, _load("review_paaaaaaaaaaaaaaa1.json"), "review")


def test_old_expect_submit_after_the_branch_moved_is_409(tmp_path):
    """画面が表示した版 (expect) を付けた送信は、ブランチが進んだ後は実サーバで 409 になり、取り直せば通る。"""
    repo = _init(tmp_path / "example-app")
    _commit(repo, {"a.txt": "one\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/x")
    _commit(repo, {"a.txt": "one\ntwo\n"}, "feat: x")
    _git(repo, "switch", "-q", "develop")
    server = Server(["--repo", str(repo), "--port", "0"])
    try:
        pr = server.get("/api/prs")[1]["prs"][0]
        shown = {"source": pr["sourceOid"], "target": pr["targetOid"], "base": pr["baseOid"]}
        path = f"/api/prs/{pr['id']}/submit"
        assert _post(server, path, {"kind": "approve", "expect": shown})[0] == 201
        _git(repo, "switch", "-q", "feature/x")
        _commit(repo, {"a.txt": "one\ntwo\nthree\n"}, "feat: more")
        _git(repo, "switch", "-q", "develop")
        status, err = _post(server, path, {"kind": "approve", "expect": shown})
        assert status == 409 and err["error"]["code"] == "stale_view"
        batches = server.get(f"/api/prs/{pr['id']}/review")[1]["batches"]
        assert len(batches) == 1  # 409 のほうは書かれていない
        now = server.get("/api/prs")[1]["prs"][0]
        fresh = {"source": now["sourceOid"], "target": now["targetOid"], "base": now["baseOid"]}
        assert fresh["source"] != shown["source"]
        assert _post(server, path, {"kind": "approve", "expect": fresh})[0] == 201
    finally:
        server.stop()


# ---------------------------------------------------------------- 統合 API（段 A2）: 実サーバの応答が、画面の fixture と同じ形


def _merge_world(tmp_path, *, rules: str | None = None):
    """--allow-merge つきの実サーバ。feature/add-search は統合できる。名前・メールは架空。"""
    repo = _init(tmp_path / "example-app")
    for key, value in (
        ("user.name", "Example Dev"),
        ("user.email", "you@example.com"),
        ("gc.auto", "0"),
        ("maintenance.auto", "false"),
    ):
        _git(repo, "config", key, value)
    _commit(repo, {"README.md": "hello\n", "AGENTS.md": "rules\n"}, "init")
    _git(repo, "switch", "-q", "-c", "feature/add-search")
    _commit(repo, {"docs/search.md": "検索\n", "AGENTS.md": "rules 2\n"}, "feat: 検索を追加")
    _git(repo, "switch", "-q", "develop")
    rules_file = tmp_path / "rules.json"
    if rules is not None:
        rules_file.write_text(rules, encoding="utf-8")
    server = Server(
        ["--repo", str(repo), "--port", "0", "--allow-merge", "--rules-file", str(rules_file)]
    )
    return repo, server


def _post_merge(server, path: str, payload: dict):
    """Origin・Host を正しく付けた統合系の POST（ブラウザと同じ）。"""
    host = f"127.0.0.1:{server.port}"
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=60)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={
            "Host": host,
            "Origin": f"http://{host}",
            "Content-Type": "application/json",
            "X-PRV": "1",
        },
    )
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, data


RULES = json.dumps({"judge": {"common": {"pi": {"integrate": {"risk_paths": ["AGENTS.md"]}}}}})


def test_real_merge_responses_have_the_same_shape_as_the_fixtures(tmp_path):
    """画面（merge.js）が読む capabilities・merge-plan・merge の形を、実サーバの応答で確かめる。

    画面の試験は契約から作った fixture（偽サーバ）で動くので、片方だけ契約からずれても、それぞれの試験は通ってしまう。
    """
    _repo, server = _merge_world(tmp_path, rules=RULES)
    try:
        status, caps = server.get("/api/capabilities")
        assert status == 200
        _same_shape(caps, _load("capabilities.json"), "capabilities")
        pr = server.get("/api/prs")[1]["prs"][0]
        plan_path = f"/api/prs/{pr['id']}/merge-plan"
        # 統合できる計画（リスクのあるパス AGENTS.md・警告は無し）
        status, plan = _post_merge(server, plan_path, {})
        assert status == 200 and plan["mergeable"] is True and plan["plan"]["risks"], plan
        _same_shape(plan, _load("merge_plan_ok.json"), "merge-plan")
        # 統合する（画面が送る 3 キー）と、その応答
        status, done = _post_merge(
            server,
            f"/api/prs/{pr['id']}/merge",
            {
                "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
                "message": plan["defaults"]["message"],
                "cleanup": "none",
            },
        )
        assert status == 200, done
        _same_shape(done, _load("merge_ok.json"), "merge")
        assert done["merge"]["recorded"] is True
    finally:
        server.stop()


def test_real_merge_plan_variants_have_the_same_shape_as_the_fixtures(tmp_path):
    """リスク設定なし・旧経路の残骸・衝突の、実サーバの応答の形。"""
    repo, server = _merge_world(tmp_path)  # rules.json 無し
    try:
        pr = server.get("/api/prs")[1]["prs"][0]
        path = f"/api/prs/{pr['id']}/merge-plan"
        status, plan = _post_merge(server, path, {})
        assert status == 200 and plan["plan"]["riskConfig"] == "unavailable", plan
        _same_shape(plan, _load("merge_plan_riskcfg.json"), "merge-plan(riskcfg)")
        # 旧経路の残骸（refs/pi/{pending,lock,running}）があっても、blockers は空で統合できる
        head = _git(repo, "rev-parse", "HEAD").strip()
        for ref in (
            "refs/pi/pending/001793000000001",
            "refs/pi/lock/abcdef0123456789",
            "refs/pi/running/001793000000002",
        ):
            _git(repo, "update-ref", ref, head)
        status, residue = _post_merge(server, path, {})
        assert status == 200 and residue["blockers"] == [] and residue["mergeable"] is True, residue
        _same_shape(residue, _load("merge_plan_riskcfg.json"), "merge-plan(residue)")
        for ref in (
            "refs/pi/pending/001793000000001",
            "refs/pi/lock/abcdef0123456789",
            "refs/pi/running/001793000000002",
        ):
            _git(repo, "update-ref", "-d", ref)
        # 衝突: 統合先と同じファイルを変える
        _commit(repo, {"AGENTS.md": "develop 側\n"}, "develop 側の変更")
        pr = server.get("/api/prs")[1]["prs"][0]
        status, conflict = _post_merge(server, f"/api/prs/{pr['id']}/merge-plan", {})
        assert status == 200 and conflict["mergeable"] is False, conflict
        _same_shape(conflict, _load("merge_plan_conflict.json"), "merge-plan(conflict)")
        status, err = _post_merge(
            server,
            f"/api/prs/{pr['id']}/merge",
            {
                "expect": {"source": pr["sourceOid"], "target": pr["targetOid"]},
                "message": "feat: x\n",
                "cleanup": "none",
            },
        )
        assert (
            status == 409
            and err["error"]["code"] == "conflict"
            and err["error"]["conflicts"] == ["AGENTS.md"]
        ), err
    finally:
        server.stop()
