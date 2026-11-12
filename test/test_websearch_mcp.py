"""web-search の MCP サーバ (home/dot_config/agents/websearch/mcp_server.py) を、通信なしで検証する。

プロトコル (stdio の JSON-RPC)・検索の fallback・論文の fallback・秘匿チェックと SSRF 防止が MCP 経由でも効くこと。
ネットワークはすべて偽物に差し替える (本物の API は呼ばない)。

see docs/spec/web-search.md
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "home" / "dot_config" / "agents" / "websearch" / "mcp_server.py"
_spec = importlib.util.spec_from_file_location("websearch_mcp_server", SERVER)
assert _spec and _spec.loader
srv = importlib.util.module_from_spec(_spec)
sys.modules["websearch_mcp_server"] = srv
_spec.loader.exec_module(srv)
core = srv.core


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name in [n for n in os.environ if n.startswith(("WEBSEARCH_", "PIS_FETCH"))]:
        monkeypatch.delenv(name)


def resp(status=200, body=None, headers=None):
    data = (
        body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
    )
    return status, {k.lower(): v for k, v in (headers or {}).items()}, data


class FakeHttp:
    def __init__(self, plan):
        self.plan = {host: list(items) for host, items in plan.items()}
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=15.0):
        host = url.split("/")[2]
        self.calls.append((host, url, headers or {}))
        queue = self.plan.get(host)
        if not queue:
            raise AssertionError(f"想定外の呼び出し: {host}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def hosts(self):
        return [c[0] for c in self.calls]


def make_deps(tmp_path, http, keys=None, **extra):
    keys = keys or {}
    deps = {
        "http": http,
        "key_for": keys.get,
        "cache_dir": tmp_path / "cache",
        "now": lambda: 1000.0,
        "sleep": lambda s: None,
        "resolver": lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
        "transport": lambda *a: resp(
            200, b"<title>T</title><p>hello</p>", {"content-type": "text/html"}
        ),
    }
    deps.update(extra)
    return deps


def rpc(deps, *messages):
    lines = [json.dumps(m) if not isinstance(m, str) else m for m in messages]
    out = io.StringIO()
    srv.serve(lines, out, lambda: deps)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def call(deps, name, arguments, ident=1):
    (reply,) = rpc(
        deps,
        {
            "jsonrpc": "2.0",
            "id": ident,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    return reply


def text_of(reply):
    return reply["result"]["content"][0]["text"]


BRAVE_OK = {
    "web": {"results": [{"title": "Brave A", "url": "https://a.example/", "description": "s"}]}
}
OA_OK = {
    "results": [
        {
            "display_name": "OA paper",
            "doi": "https://doi.org/10.1/x",
            "publication_year": 2024,
            "cited_by_count": 3,
            "authorships": [{"author": {"display_name": "Ann"}}],
        }
    ]
}
S2_OK = {
    "data": [
        {
            "title": "S2 paper",
            "year": 2023,
            "authors": [{"name": "Bo"}],
            "citationCount": 1,
            "url": "https://s2.example/p",
        }
    ]
}
CR_OK = {
    "message": {
        "items": [
            {
                "title": ["CR paper"],
                "DOI": "10.2/y",
                "URL": "https://doi.org/10.2/y",
                "author": [{"given": "Cy", "family": "Dee"}],
                "issued": {"date-parts": [[2022]]},
                "is-referenced-by-count": 5,
            }
        ]
    }
}
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1234.5678v1</id><title>AX paper</title><summary>sum</summary>
<published>2021-01-01T00:00:00Z</published><author><name>Ed</name></author></entry></feed>"""


# ─── プロトコル ────────────────────────────────────────────────────────


def test_initialize_list_and_ping(tmp_path):
    deps = make_deps(tmp_path, FakeHttp({}))
    init, listed, ping, _res = rpc(
        deps,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # 通知には答えない
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
    )

    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["capabilities"] == {"tools": {}}
    names = [t["name"] for t in listed["result"]["tools"]]
    assert names == ["web_search", "fetch_page", "search_papers"]
    for tool in listed["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object" and "信頼できない外部" in tool["description"]
        assert tool["annotations"]["readOnlyHint"] is True
    assert ping["result"] == {} and _res["result"] == {"resources": []}


def test_protocol_errors(tmp_path):
    deps = make_deps(tmp_path, FakeHttp({}))
    replies = rpc(
        deps,
        "{not json",
        "[1, 2]",
        {"jsonrpc": "2.0", "id": 1, "method": "nope"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "rm_rf"}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {}},
        "",
    )

    assert [r["error"]["code"] for r in replies] == [-32700, -32600, -32601, -32602, -32602]
    assert replies[0]["id"] is None and replies[2]["id"] == 1


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("web_search", {}),
        ("web_search", {"query": 5}),
        ("web_search", {"query": "x", "n": "many"}),
        ("web_search", {"query": "x", "n": True}),
        ("web_search", "str"),
        ("fetch_page", {"url": ""}),
        ("search_papers", {"query": "x", "from_year": 2.5}),
    ],
)
def test_bad_arguments_are_tool_errors_not_crashes(tmp_path, name, arguments):
    deps = make_deps(tmp_path, FakeHttp({}))
    reply = call(deps, name, arguments)

    assert reply["result"]["isError"] is True


def test_unexpected_failures_do_not_leak_details(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("secret-token-value")

    reply = call(make_deps(tmp_path, boom, keys={"brave": "k"}), "web_search", {"query": "hello"})

    assert reply["result"]["isError"] and "secret-token-value" not in text_of(reply)
    assert "RuntimeError" in text_of(reply)


def test_bad_broker_setting_is_a_tool_error(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBSEARCH_BROKER_URL", "http://evil.example")

    def deps():
        return core.default_deps()

    out = io.StringIO()
    srv.serve(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "web_search", "arguments": {"query": "x"}},
                }
            )
        ],
        out,
        deps,
    )
    reply = json.loads(out.getvalue())

    assert reply["result"]["isError"] and "不正" in text_of(reply)


def test_stdio_subprocess_roundtrip(tmp_path):
    """実際にプロセスとして起動し、通信の要らない呼び出しだけを往復する。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("WEBSEARCH_", "BW_"))}
    env.update(
        {"HOME": str(tmp_path), "WEBSEARCH_CACHE_DIR": str(tmp_path / "c"), "PATH": "/nonexistent"}
    )
    requests = "\n".join(
        json.dumps(m)
        for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "web_search", "arguments": {"query": "password=hunter2hunter2"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "fetch_page", "arguments": {"url": "http://127.0.0.1/"}},
            },
        )
    )
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=requests + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    replies = [json.loads(x) for x in proc.stdout.splitlines()]

    assert proc.returncode == 0 and [r["id"] for r in replies] == [1, 2, 3, 4]
    assert replies[2]["result"]["isError"] and "検索を止めた" in text_of(replies[2])
    assert replies[3]["result"]["isError"] and "取得を止めた" in text_of(replies[3])


# ─── web_search のフォールバックと安全策 ─────────────────────────────


def test_web_search_returns_text_with_provider_and_untrusted_notice(tmp_path):
    http = FakeHttp({"api.search.brave.com": [resp(200, BRAVE_OK)]})
    reply = call(make_deps(tmp_path, http, {"brave": "kb"}), "web_search", {"query": "hello"})

    text = text_of(reply)
    assert reply["result"]["isError"] is False
    assert "provider=brave" in text and "https://a.example" in text and core.UNTRUSTED in text


def test_web_search_falls_through_missing_key_failure_and_disabled(tmp_path):
    http = FakeHttp(
        {
            "api.exa.ai": [resp(429, {}, {"retry-after": "100"})],
            "api.tavily.com": [resp(402, {})],
            "html.duckduckgo.com": [
                resp(200, b'<a class="result__a" href="https://d.example/">D</a>')
            ],
        }
    )
    deps = make_deps(tmp_path, http, {"exa": "ke", "tavily": "kt"})  # brave は鍵なし
    text = text_of(call(deps, "web_search", {"query": "fallback"}))

    assert "brave(no-key)" in text and "exa(rate)" in text and "tavily(quota)" in text
    assert http.hosts == ["api.exa.ai", "api.tavily.com", "html.duckduckgo.com"]
    # tavily は枠切れで休止に入り、次の (別の語の) 検索では呼ばれない
    http.plan["html.duckduckgo.com"] = [
        resp(200, b'<a class="result__a" href="https://d2.example/">D2</a>')
    ]
    text2 = text_of(call(deps, "web_search", {"query": "another"}))
    assert "tavily(disabled)" in text2


def test_web_search_all_failed_is_an_error(tmp_path):
    reply = call(make_deps(tmp_path, FakeHttp({})), "web_search", {"query": "none", "n": 3})
    # 鍵なし 3 つは飛ばし、DuckDuckGo へ偽物が無いので AssertionError → 内部エラーになる
    assert reply["result"]["isError"] is True


def test_web_search_uses_the_cache(tmp_path):
    http = FakeHttp({"api.search.brave.com": [resp(200, BRAVE_OK)]})
    deps = make_deps(tmp_path, http, {"brave": "kb"})
    call(deps, "web_search", {"query": "cached"})
    again = text_of(call(deps, "web_search", {"query": "cached"}))

    assert "(cache)" in again and http.hosts == ["api.search.brave.com"]


@pytest.mark.parametrize(
    "query",
    [
        "ghp_" + "a" * 30,
        "password=hunter2hunter2",
        "host.internal config",
        "10.0.0.5 の設定",
    ],
)
def test_secret_queries_are_never_sent(tmp_path, query):
    http = FakeHttp({})
    deps = make_deps(tmp_path, http, {"brave": "kb"})
    for name in ("web_search", "search_papers"):
        reply = call(deps, name, {"query": query})
        assert reply["result"]["isError"] and "検索を止めた" in text_of(reply)
    assert http.calls == []


# ─── search_papers の fallback ───────────────────────────────────────


def test_papers_use_openalex_first_without_a_key(tmp_path):
    http = FakeHttp({"api.openalex.org": [resp(200, OA_OK)]})
    text = text_of(call(make_deps(tmp_path, http), "search_papers", {"query": "graph"}))

    assert "provider=openalex" in text and "OA paper" in text and "api_key" not in http.calls[0][1]
    assert http.hosts == ["api.openalex.org"]


@pytest.mark.parametrize(
    ("plan", "expected", "label"),
    [
        (
            {"api.openalex.org": [resp(500)], "api.semanticscholar.org": [resp(200, S2_OK)]},
            "semanticscholar",
            "S2 paper",
        ),
        (
            {
                "api.openalex.org": [resp(500)],
                "api.semanticscholar.org": [resp(429)],
                "api.crossref.org": [resp(200, CR_OK)],
            },
            "crossref",
            "CR paper",
        ),
        (
            {
                "api.openalex.org": [resp(200, {"results": []})],
                "api.semanticscholar.org": [resp(429)],
                "api.crossref.org": [resp(503)],
                "export.arxiv.org": [resp(200, ATOM)],
            },
            "arxiv",
            "AX paper",
        ),
    ],
)
def test_papers_fall_back_in_order(tmp_path, plan, expected, label):
    http = FakeHttp(plan)
    reply = call(make_deps(tmp_path, http), "search_papers", {"query": "graph"})
    text = text_of(reply)

    assert reply["result"]["isError"] is False
    assert f"provider={expected}" in text and label in text
    order = {
        "openalex": "api.openalex.org",
        "semanticscholar": "api.semanticscholar.org",
        "crossref": "api.crossref.org",
        "arxiv": "export.arxiv.org",
    }
    hosts = list(order.values())
    # 答えたプロバイダまでを、鎖の順に 1 回ずつ呼ぶ
    assert http.hosts == hosts[: hosts.index(order[expected]) + 1]


def test_papers_all_failed_reports_the_trail(tmp_path):
    http = FakeHttp(
        {
            "api.openalex.org": [resp(500)],
            "api.semanticscholar.org": [resp(429)],
            "api.crossref.org": [resp(503)],
            "export.arxiv.org": [resp(200, b"not xml")],
        }
    )
    reply = call(make_deps(tmp_path, http), "search_papers", {"query": "graph"})

    assert reply["result"]["isError"] is True
    assert "openalex(server)" in text_of(reply) and "arxiv(parse)" in text_of(reply)


def test_papers_quota_disables_a_provider_and_keys_are_optional(tmp_path):
    http = FakeHttp(
        {
            "api.openalex.org": [resp(402)],
            "api.semanticscholar.org": [resp(200, S2_OK)],
        }
    )
    deps = make_deps(tmp_path, http, {"semanticscholar": "ks"})
    call(deps, "search_papers", {"query": "one"})
    text = text_of(call(deps, "search_papers", {"query": "two"}))

    assert "openalex(disabled)" in text
    assert [c[2].get("x-api-key") for c in http.calls if "semantic" in c[0]] == ["ks", "ks"]


def test_papers_from_year_and_cache(tmp_path):
    http = FakeHttp({"api.openalex.org": [resp(200, OA_OK)]})
    deps = make_deps(tmp_path, http)
    call(deps, "search_papers", {"query": "graph", "from_year": 2020})
    again = text_of(call(deps, "search_papers", {"query": "graph", "from_year": 2020}))

    assert "from_publication_date%3A2020-01-01" in http.calls[0][1] and "(cache)" in again
    assert len(http.calls) == 1


def test_arxiv_filters_by_year_client_side(tmp_path):
    http = FakeHttp({"export.arxiv.org": [resp(200, ATOM)]})
    results = core.search_arxiv("graph", 5, None, http, from_year=2023)

    assert results == []


def test_papers_in_broker_mode_skip_providers_the_broker_cannot_reach(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBSEARCH_BROKER_URL", "http://127.0.0.1:9999")
    http = FakeHttp({"127.0.0.1:9999": [resp(500)]})
    outcome = core.run_papers(
        "q", 3, None, http=http, key_for=lambda n: None, state=core.State(tmp_path, lambda: 1.0)
    )

    assert outcome.provider is None
    assert ("semanticscholar", "no-broker") in outcome.attempts and (
        "arxiv",
        "no-broker",
    ) in outcome.attempts


# ─── fetch_page の SSRF 防止 (MCP 経由) ──────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://example.com:8443/",
        "https://user:pw@example.com/",
        "file:///etc/passwd",
    ],
)
def test_fetch_page_blocks_internal_targets(tmp_path, url):
    def resolver(host, port, **kw):  # 名前は実際の解決結果を真似る
        address = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    deps = make_deps(
        tmp_path,
        FakeHttp({}),
        resolver=resolver,
        transport=lambda *a: pytest.fail("接続してはいけない"),
    )
    reply = call(deps, "fetch_page", {"url": url})

    assert reply["result"]["isError"] is True and "取得を止めた" in text_of(reply)


def test_fetch_page_blocks_names_that_resolve_to_private_addresses(tmp_path):
    deps = make_deps(
        tmp_path,
        FakeHttp({}),
        resolver=lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))
        ],
        transport=lambda *a: pytest.fail("接続してはいけない"),
    )

    assert call(deps, "fetch_page", {"url": "https://rebind.example/"})["result"]["isError"]


def test_fetch_page_returns_text_and_rejects_binary(tmp_path):
    ok = text_of(
        call(make_deps(tmp_path, FakeHttp({})), "fetch_page", {"url": "https://ok.example/"})
    )
    assert "title='T'" in ok and "hello" in ok and core.UNTRUSTED in ok

    deps = make_deps(
        tmp_path,
        FakeHttp({}),
        transport=lambda *a: resp(200, b"%PDF", {"content-type": "application/pdf"}),
    )
    reply = call(deps, "fetch_page", {"url": "https://ok.example/a.pdf"})
    assert reply["result"]["isError"] and "content-type" in text_of(reply)


# ─── コードを 1 本に保つ ─────────────────────────────────────────────


def test_server_does_not_copy_core_logic():
    text = SERVER.read_text(encoding="utf-8")

    assert "def check_query" not in text and "def check_url" not in text
    assert "api.search.brave.com" not in text and "def sync_keys" not in text
