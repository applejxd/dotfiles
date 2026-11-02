"""PR ビューア 段 1 の結合 (サーバ ``apps/pr-viewer/server.ts`` と画面 ``apps/pr-viewer/web/``。案件 CHG-0060)。

画面の試験は、契約から作った fixture で動く。ここでは、**実サーバの応答が fixture と同じ形** (キーと型) であることと、
**既定の web ディレクトリから、画面が読み込むファイルを全部配信できる**ことを確かめる
(片方だけ契約からずれても、それぞれの試験は通ってしまうため)。

see docs/change/0060-local-pr-viewer.md
"""

from __future__ import annotations

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
    fixture = _load("diff_paaaaaaaaaaaaaaa1.json")
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
