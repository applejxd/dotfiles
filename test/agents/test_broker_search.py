"""検索ブローカー (``websearch.py`` 用のリスナー) の試験。鍵はすべてダミー。

契約: .tmp/handoff-search/README.md。Copilot / GitHub の出力が変わらないことは ``test_broker.py`` の
正解データが固定している。
"""

from __future__ import annotations

import contextlib
import http.client
import http.server
import json
import os
import shutil
import stat
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_broker import _install_envoy, _ocs

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="境界は Linux 専用")

KEYS = {"brave": "DUMMY-BRAVE-KEY", "exa": "DUMMY-EXA-KEY", "tavily": "DUMMY-TAVILY-KEY"}
IDENTITY = "/__pis_broker"

# 本物の Envoy の代わり: 設定の身元確認の本文を、リスナーごとにそのまま返す
FAKE_ENVOY = """#!{python}
import http.server
import json
import os
import sys
import threading

cfg = sys.argv[sys.argv.index("--config-path") + 1]
data = json.loads(open(cfg, encoding="utf-8").read())
with open(os.path.join(os.path.dirname(cfg), "fake.pid"), "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))


def identity(listener):
    manager = listener["filter_chains"][0]["filters"][0]["typed_config"]
    for route in manager["route_config"]["virtual_hosts"][0]["routes"]:
        if route["match"].get("path") == "/__pis_broker":
            return route["direct_response"]["body"]["inline_string"].encode()
    return b"no"


def handler_for(body):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path == "/__pis_broker"
            out = body if ok else b"no"
            self.send_response(200 if ok else 403)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    return Handler


servers = []
for item in data["static_resources"]["listeners"]:
    port = item["address"]["socket_address"]["port_value"]
    servers.append(http.server.HTTPServer(("127.0.0.1", port), handler_for(identity(item))))
for extra in servers[1:]:
    threading.Thread(target=extra.serve_forever, daemon=True).start()
servers[0].serve_forever()
"""


def _config(**kwargs) -> dict:
    broker = _ocs().broker
    options = {"sds_dir": Path("/state/dir"), "ca_file": "/etc/ssl/ca.pem", "search_port": 23456}
    return json.loads(broker.build_config(**{**options, **kwargs}))


def _search_routes(data: dict) -> list[dict]:
    (listener,) = data["static_resources"]["listeners"]
    manager = listener["filter_chains"][0]["filters"][0]["typed_config"]
    (vhost,) = manager["route_config"]["virtual_hosts"]
    return vhost["routes"]


def _route_for(routes: list[dict], path: str) -> list[dict]:
    return [r for r in routes if r["match"].get("path") == path]


# ─── build_config: 検索のリスナー ───────────────────────────────────


def test_search_config_without_search_arguments_is_unchanged():
    broker = _ocs().broker
    base = {
        "sds_dir": Path("/state/dir"),
        "ca_file": "/etc/ssl/ca.pem",
        "copilot_port": 12345,
        "copilot_host": "api.example.test",
    }
    assert broker.build_config(**base) == broker.build_config(
        **base, search_port=None, search_keys=None
    )
    assert "search" not in broker.build_config(**base)


def test_search_listener_is_loopback_with_five_clusters():
    data = _config(search_keys=KEYS)
    (listener,) = data["static_resources"]["listeners"]
    assert listener["address"] == {"socket_address": {"address": "127.0.0.1", "port_value": 23456}}
    clusters = data["static_resources"]["clusters"]
    hosts = [c["transport_socket"]["typed_config"]["sni"] for c in clusters]
    assert hosts == [
        "api.search.brave.com",
        "api.exa.ai",
        "api.tavily.com",
        "api.openalex.org",
        "html.duckduckgo.com",
    ]
    for cluster, host in zip(clusters, hosts, strict=True):
        validation = cluster["transport_socket"]["typed_config"]["common_tls_context"][
            "validation_context"
        ]
        assert validation["trusted_ca"] == {"filename": "/etc/ssl/ca.pem"}
        assert validation["match_typed_subject_alt_names"] == [
            {"san_type": "DNS", "matcher": {"exact": host}}
        ]


def test_search_routes_are_exact_paths_and_methods():
    routes = _search_routes(_config(search_keys=KEYS))

    def shape(route):
        match = route["match"]
        headers = match.get("headers")
        method = None
        if headers:
            matcher = headers[0]["string_match"]
            method = matcher.get("exact") or matcher["safe_regex"]["regex"]
        return match.get("path") or match.get("prefix"), method

    assert [shape(r) for r in routes] == [
        (IDENTITY, "GET"),
        ("/brave/res/v1/web/search", "GET"),
        ("/exa/search", "POST"),
        ("/tavily/search", "POST"),
        ("/openalex/works", "GET"),
        ("/ddg/html/", "GET|POST"),
        ("/", None),
    ]
    assert routes[0]["direct_response"]["status"] == 200
    assert routes[0]["direct_response"]["body"]["inline_string"] == "pis-broker-search"
    last = routes[-1]["direct_response"]
    assert last["status"] == 403
    assert last["body"]["inline_string"] == "pis-broker: path or method not allowed"


def test_search_routes_strip_the_prefix_and_set_the_upstream_host():
    routes = _search_routes(_config(search_keys=KEYS))
    for path, host in (
        ("/brave/res/v1/web/search", "api.search.brave.com"),
        ("/exa/search", "api.exa.ai"),
        ("/tavily/search", "api.tavily.com"),
        ("/openalex/works", "api.openalex.org"),
        ("/ddg/html/", "html.duckduckgo.com"),
    ):
        (entry,) = _route_for(routes, path)
        route = entry["route"]
        assert route["host_rewrite_literal"] == host
        prefix = path.split("/")[1]
        assert route["regex_rewrite"] == {"pattern": {"regex": f"^/{prefix}"}, "substitution": ""}


def _headers(entry: dict) -> dict[str, str]:
    return {
        h["header"]["key"]: h["header"]["value"] for h in entry.get("request_headers_to_add", [])
    }


def test_each_key_is_attached_only_to_its_own_route():
    routes = _search_routes(_config(search_keys=KEYS))
    expected = {
        "/brave/res/v1/web/search": {"X-Subscription-Token": KEYS["brave"]},
        "/exa/search": {"x-api-key": KEYS["exa"]},
        "/tavily/search": {"Authorization": "Bearer " + KEYS["tavily"]},
        "/openalex/works": {},
        "/ddg/html/": {},
    }
    for path, headers in expected.items():
        (entry,) = _route_for(routes, path)
        assert _headers(entry) == headers
        for header in entry.get("request_headers_to_add", []):
            assert header["append_action"] == "OVERWRITE_IF_EXISTS_OR_ADD"
    text = json.dumps(routes)
    for name, key in KEYS.items():
        assert text.count(key) == 1, name  # 自分の経路にだけ 1 回


def test_other_auth_headers_from_the_inside_are_removed_on_every_route():
    routes = _search_routes(_config(search_keys=KEYS))
    all_auth = {"authorization", "proxy-authorization", "x-api-key", "x-subscription-token"}
    own = {
        "/brave/res/v1/web/search": "x-subscription-token",
        "/exa/search": "x-api-key",
        "/tavily/search": "authorization",
        "/openalex/works": None,
        "/ddg/html/": None,
    }
    for path, mine in own.items():
        (entry,) = _route_for(routes, path)
        removed = set(entry["request_headers_to_remove"])
        assert removed == all_auth - {mine}


def test_missing_keys_answer_503_at_the_route():
    routes = _search_routes(_config(search_keys={"brave": KEYS["brave"]}))
    for name, path in (("exa", "/exa/search"), ("tavily", "/tavily/search")):
        (entry,) = _route_for(routes, path)
        assert "route" not in entry
        assert entry["direct_response"]["status"] == 503
        assert entry["direct_response"]["body"]["inline_string"] == f"pis-broker: no key for {name}"
    (brave,) = _route_for(routes, "/brave/res/v1/web/search")
    assert "route" in brave
    # 鍵なしの経路 (OpenAlex・DDG) は鍵が無くても通る
    assert "route" in _route_for(routes, "/openalex/works")[0]
    assert "route" in _route_for(routes, "/ddg/html/")[0]
    routes = _search_routes(_config())  # search_keys 自体が無い
    assert [r["direct_response"]["status"] for r in routes[1:4]] == [503, 503, 503]


def test_access_log_omits_the_query_and_headers():
    data = _config(search_keys=KEYS)
    (listener,) = data["static_resources"]["listeners"]
    manager = listener["filter_chains"][0]["filters"][0]["typed_config"]
    fmt = manager["access_log"][0]["typed_config"]["log_format"]["text_format_source"][
        "inline_string"
    ]
    assert "%REQ_WITHOUT_QUERY(:PATH)%" in fmt
    assert "%REQ(:PATH)%" not in fmt
    assert "%REQ(" not in fmt.replace("%REQ(:METHOD)%", "")  # ヘッダーは出さない
    assert "%DOWNSTREAM_" not in fmt


def test_search_has_no_credential_injector_and_percent_in_keys_is_escaped():
    data = _config(search_keys={"brave": "a%b"})
    (listener,) = data["static_resources"]["listeners"]
    manager = listener["filter_chains"][0]["filters"][0]["typed_config"]
    assert [f["name"] for f in manager["http_filters"]] == ["envoy.filters.http.router"]
    (entry,) = _route_for(_search_routes(data), "/brave/res/v1/web/search")
    assert _headers(entry) == {"X-Subscription-Token": "a%%b"}


@pytest.mark.parametrize("bad", ["", "a b", "a\nb", "あ", "x" * 513, 5, None])
def test_bad_key_values_are_refused_without_echoing_them(bad):
    broker = _ocs().broker
    secret = bad if isinstance(bad, str) and bad else "unused"
    with pytest.raises(broker.BrokerError) as raised:
        broker.build_config(
            sds_dir=Path("/state/dir"),
            ca_file="/etc/ssl/ca.pem",
            search_port=23456,
            search_keys={"brave": bad},  # type: ignore[dict-item]
        )
    assert secret not in str(raised.value) and secret not in repr(raised.value)


def test_search_only_config_does_not_need_copilot_or_github():
    data = _config(search_keys=KEYS)
    assert [listener["name"] for listener in data["static_resources"]["listeners"]] == ["search"]
    text = json.dumps(data)
    assert "copilot" not in text and "gh_token" not in text


def test_search_alongside_copilot_keeps_both_listeners():
    data = _config(search_keys=KEYS, copilot_port=12345, copilot_host="api.example.test")
    names = [listener["name"] for listener in data["static_resources"]["listeners"]]
    assert names == ["copilot", "search"]
    assert len(data["static_resources"]["clusters"]) == 6


# ─── 鍵ファイルの読み取り (ホスト側) ──────────────────────────────


def _keys_file(tmp_path: Path, body, mode: int = 0o600) -> Path:
    path = tmp_path / "websearch-keys.json"
    text = body if isinstance(body, str) else json.dumps(body)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_search_keys_are_read_for_the_keyed_providers_only(tmp_path):
    broker = _ocs().broker
    path = _keys_file(tmp_path, {**KEYS, "openalex": "ignored", "extra": "x"})
    keys, notes = broker.read_search_keys(path)
    assert keys == KEYS and notes == []


def test_missing_search_keys_file_is_no_keys_with_a_note(tmp_path):
    broker = _ocs().broker
    keys, notes = broker.read_search_keys(tmp_path / "none.json")
    assert keys == {} and len(notes) == 1


@pytest.mark.parametrize(
    "body",
    ["{not json", "[]", '"str"', json.dumps({"brave": 5}), json.dumps({"brave": "a b"})],
    ids=["broken", "list", "string", "non-string-value", "whitespace-value"],
)
def test_broken_search_keys_are_treated_as_no_keys_without_leaking(tmp_path, body):
    broker = _ocs().broker
    keys, notes = broker.read_search_keys(_keys_file(tmp_path, body))
    assert "brave" not in keys
    assert notes
    assert not any("a b" in n for n in notes)


def test_one_bad_value_does_not_hide_the_good_ones(tmp_path):
    broker = _ocs().broker
    path = _keys_file(tmp_path, {"brave": 5, "exa": KEYS["exa"]})
    keys, notes = broker.read_search_keys(path)
    assert keys == {"exa": KEYS["exa"]}
    assert any("brave" in n for n in notes)


def test_search_keys_file_with_open_permissions_is_not_used(tmp_path):
    broker = _ocs().broker
    keys, notes = broker.read_search_keys(_keys_file(tmp_path, KEYS, mode=0o644))
    assert keys == {} and notes
    assert not any(v in n for n in notes for v in KEYS.values())


def test_search_keys_file_over_the_limit_is_not_used(tmp_path):
    broker = _ocs().broker
    big = json.dumps({"brave": "k", "pad": "x" * (broker.SEARCH_KEYS_MAX_BYTES + 1)})
    keys, notes = broker.read_search_keys(_keys_file(tmp_path, big))
    assert keys == {} and notes


def test_search_keys_file_symlink_or_directory_is_not_used(tmp_path):
    broker = _ocs().broker
    target = _keys_file(tmp_path, KEYS)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    assert broker.read_search_keys(link)[0] == {}
    (tmp_path / "dir").mkdir()
    assert broker.read_search_keys(tmp_path / "dir")[0] == {}


def test_search_keys_are_not_taken_from_the_environment(tmp_path, monkeypatch):
    broker = _ocs().broker
    monkeypatch.setenv("BRAVE_API_KEY", "ENV-KEY")
    assert broker.read_search_keys(tmp_path / "none.json")[0] == {}


# ─── 設定の検証 (rules.json の broker.search) ─────────────────────


def _rules_json(tmp_path, body) -> Path:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, False),
        ({"broker": {}}, False),
        ({"broker": {"search": "off"}}, False),
        ({"broker": {"search": "auto"}}, True),
    ],
)
def test_search_setting_values(tmp_path, body, expected):
    pi = _ocs().pi
    assert pi.read_search_setting(_rules_json(tmp_path, body)) is expected


@pytest.mark.parametrize("value", ["AUTO", "on", "", None, True, 1, ["auto"]])
def test_search_setting_rejects_other_values(tmp_path, capsys, value):
    pi = _ocs().pi
    with pytest.raises(SystemExit):
        pi.read_search_setting(_rules_json(tmp_path, {"broker": {"search": value}}))
    assert "broker.search" in capsys.readouterr().err


def test_search_setting_fails_closed_on_a_broken_broker_section(tmp_path):
    pi = _ocs().pi
    with pytest.raises(SystemExit):
        pi.read_search_setting(_rules_json(tmp_path, {"broker": "auto"}))


# ─── pi.py の配線 (session を記録する偽物) ────────────────────────


def _recording_session(pi, events, search_url="http://127.0.0.1:18082"):
    @contextlib.contextmanager
    def session(*args, **kwargs):
        events.append(("enter", args, kwargs))
        try:
            yield pi.broker.BrokerSession(
                None, Path("/nonexistent/run/pis-broker-x"), None, search_url
            )
        finally:
            events.append(("exit",))

    return session


def _wire(pi, monkeypatch, tmp_path, broker_section):
    monkeypatch.setattr(pi, "AGENT_HOME", tmp_path / "sandbox")
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi, "RULES", _rules_json(tmp_path, {"broker": broker_section}))
    seen: dict = {}
    events: list = []
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    monkeypatch.setattr(
        pi,
        "_launch_with",
        lambda args, p, value, s=None, **k: seen.update(value=value, **k) or 0,
    )
    return events, seen


def test_search_auto_starts_a_session_with_search_only(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    events, seen = _wire(pi, monkeypatch, tmp_path, {"copilot": "off", "search": "auto"})
    monkeypatch.setattr(pi.broker, "read_search_keys", lambda: ({"brave": "DUMMY-K"}, []))
    assert pi._launch(SimpleNamespace(no_broker=False), []) == 0
    (enter, _exit) = events
    assert enter[2]["copilot"] is False and enter[2]["search"] is True
    assert enter[2]["search_keys"] == {"brave": "DUMMY-K"}
    assert seen["value"] is None  # Copilot は off のまま
    assert seen["search_url"] == "http://127.0.0.1:18082"
    err = capsys.readouterr().err
    assert "exa" in err and "tavily" in err and "DUMMY-K" not in err
    assert events[-1] == ("exit",)


def test_search_off_does_not_start_a_session(monkeypatch, tmp_path):
    pi = _ocs().pi
    events, seen = _wire(pi, monkeypatch, tmp_path, {"copilot": "off", "search": "off"})
    monkeypatch.setattr(pi.broker, "read_search_keys", lambda: pytest.fail("鍵を読んではいけない"))
    assert pi._launch(SimpleNamespace(no_broker=False), []) == 0
    assert events == [] and seen.get("search_url") is None


def test_no_broker_flag_also_drops_search(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    events, seen = _wire(pi, monkeypatch, tmp_path, {"copilot": "off", "search": "auto"})
    monkeypatch.setattr(pi.broker, "read_search_keys", lambda: pytest.fail("鍵を読んではいけない"))
    assert pi._launch(SimpleNamespace(no_broker=True), []) == 0
    assert events == [] and seen.get("search_url") is None
    assert "検索" in capsys.readouterr().err


def test_search_session_failure_refuses_to_start(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    _wire(pi, monkeypatch, tmp_path, {"search": "auto"})
    monkeypatch.setattr(pi.broker, "read_search_keys", lambda: ({}, []))

    @contextlib.contextmanager
    def failing(*args, **kwargs):
        raise pi.broker.BrokerError("envoy が見つからない", "導入の案内")
        yield  # pragma: no cover

    monkeypatch.setattr(pi.broker, "session", failing)
    monkeypatch.setattr(pi, "_launch_with", lambda *a, **k: pytest.fail("起動してはいけない"))
    with pytest.raises(SystemExit):
        pi._launch(SimpleNamespace(no_broker=False), [])
    err = capsys.readouterr().err
    assert "envoy が見つからない" in err and "--no-broker" in err


def test_inner_env_gets_the_search_url_and_never_a_key(tmp_path, monkeypatch):
    pi = _ocs().pi
    monkeypatch.setattr(pi.check, "ensure_canary", lambda: None)
    monkeypatch.setenv("WEBSEARCH_BROKER_URL", "http://evil.example:1")
    monkeypatch.setenv("BRAVE_API_KEY", "HOST-KEY")
    monkeypatch.setenv("TAVILY_API_KEY", "HOST-KEY")
    url = "http://127.0.0.1:18082"
    on = pi.inner_env(tmp_path / "agent", {"filesystem": {}}, search_url=url)
    assert on["WEBSEARCH_BROKER_URL"] == url
    off = pi.inner_env(tmp_path / "agent", {"filesystem": {}})
    assert "WEBSEARCH_BROKER_URL" not in off  # ホストの値を内側へ素通しにしない
    for env in (on, off):
        assert "TAVILY_API_KEY" in os.environ  # ホスト側は変えない
        assert "HOST-KEY" not in json.dumps(env, ensure_ascii=False)
        assert "BRAVE_API_KEY" not in env or env["BRAVE_API_KEY"] != "HOST-KEY"


def test_search_port_is_opened_alongside_the_copilot_port():
    pi = _ocs().pi
    config_ = {"network": {}}
    pi.apply_broker_network(config_, 18080, 18082)
    assert config_["network"]["allowLocalOutbound"] is True
    assert config_["network"]["allowLocalOutboundPorts"] == [18080, 18082]
    only = {"network": {}}
    pi.apply_broker_network(only, 18082)
    assert only["network"]["allowLocalOutboundPorts"] == [18082]


def test_identity_check_accepts_only_the_search_prefix(monkeypatch, capsys):
    pi = _ocs().pi

    class Handler(http.server.BaseHTTPRequestHandler):
        body = b"pis-broker-search"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.body)))
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        pi.verify_broker(url, pi.broker.SEARCH_IDENTITY_PREFIX, "検索")
        with pytest.raises(SystemExit):
            pi.verify_broker(url)  # Copilot の身元ではない
    finally:
        server.shutdown()
        server.server_close()


# ─── session (偽の Envoy) ─────────────────────────────────────────


@pytest.fixture
def fake_host(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    runtime = tmp_path / "run"
    runtime.mkdir()
    bin_dir = tmp_path / "bin"
    _install_envoy(bin_dir, FAKE_ENVOY)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(_ocs().broker, "find_ca_file", lambda: str(ca))
    return SimpleNamespace(home=home, runtime=runtime)


def test_search_only_session_writes_the_keys_to_a_private_config(fake_host):
    broker = _ocs().broker
    with broker.session(copilot=False, search=True, search_keys=KEYS) as started:
        assert started.url is None and started.github_socket is None
        assert started.search_url and started.search_url.startswith("http://127.0.0.1:")
        config = started.state / broker.CONFIG_NAME
        assert stat.S_IMODE(config.stat().st_mode) == 0o600
        assert stat.S_IMODE(started.state.stat().st_mode) == 0o700
        text = config.read_text(encoding="utf-8")
        assert KEYS["brave"] in text
        assert not any(started.state.glob("*sds*"))  # SDS ファイルは作らない
        assert KEYS["brave"] not in repr(started)
        state = started.state
    assert not state.exists()


def test_search_session_runs_beside_the_copilot_listener(fake_host, monkeypatch):
    broker = _ocs().broker
    agent = fake_host.home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "auth.json").write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": "R", "expires": 1}}),
        encoding="utf-8",
    )
    import time

    monkeypatch.setattr(
        broker,
        "exchange",
        lambda refresh: (
            "tid=T;proxy-ep=proxy.individual.githubcopilot.com;exp=1",
            int(time.time()) + 3600,
        ),
    )
    with broker.session(agent, search=True, search_keys={}) as started:
        assert started.url and started.search_url and started.url != started.search_url


def test_session_without_any_broker_is_still_an_error(fake_host):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError), broker.session(copilot=False):
        pass


def test_session_error_does_not_carry_the_keys(fake_host):
    broker = _ocs().broker
    with (
        pytest.raises(broker.BrokerError) as raised,
        broker.session(copilot=False, search=True, search_keys={"brave": "bad key with space"}),
    ):
        pass
    assert "bad key" not in str(raised.value) and "bad key" not in repr(raised.value)


# ─── 本物の Envoy (無ければ skip) ────────────────────────────────


def _real_envoy() -> str | None:
    found = shutil.which("envoy")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "envoy"
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).seen.append((self.command, self.path, dict(self.headers.items())))
        body = b"upstream-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _record

    def log_message(self, *args):
        pass


@pytest.fixture
def real_search(tmp_path, monkeypatch):
    envoy = _real_envoy()
    if envoy is None:
        pytest.skip("envoy が無い")
    broker = _ocs().broker
    runtime = tmp_path / "run"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("PATH", f"{Path(envoy).parent}{os.pathsep}{os.environ['PATH']}")

    class Handler(_Upstream):
        seen: ClassVar[list] = []

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    upstreams = {p.name: server.server_port for p in broker.SEARCH_PROVIDERS}
    final_log: list[str] = []
    real_rmtree = shutil.rmtree

    def capture_then_remove(path, *args, **kwargs):
        # Envoy を止めた後 (stdout のバッファを出し切った後) のログを、状態を消す前に取る
        log = Path(path) / "envoy.log"
        if log.is_file():
            final_log.append(log.read_text(encoding="utf-8", errors="replace"))
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", capture_then_remove)
    stack = contextlib.ExitStack()
    try:
        started = stack.enter_context(
            broker.session(
                copilot=False,
                search=True,
                search_keys={"brave": KEYS["brave"], "tavily": KEYS["tavily"]},
                search_test_upstreams=upstreams,
            )
        )
        yield SimpleNamespace(
            url=started.search_url, seen=Handler.seen, stop=stack.close, final_log=final_log
        )
    finally:
        stack.close()
        server.shutdown()
        server.server_close()


def _request(url: str, method: str, path: str, headers: dict | None = None, body: bytes = b""):
    conn = http.client.HTTPConnection(url.removeprefix("http://"), timeout=10)
    try:
        conn.request(method, path, body=body or None, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def _lower(headers: dict) -> dict:
    return {k.lower(): v for k, v in headers.items()}


def test_real_envoy_identity_denial_and_missing_key(real_search):
    assert _request(real_search.url, "GET", IDENTITY) == (200, "pis-broker-search")
    assert _request(real_search.url, "POST", IDENTITY)[0] == 403  # 身元確認は GET だけ
    status, body = _request(real_search.url, "GET", "/brave/other")
    assert (status, body) == (403, "pis-broker: path or method not allowed")
    assert _request(real_search.url, "POST", "/brave/res/v1/web/search")[0] == 403
    assert _request(real_search.url, "GET", "/")[0] == 403
    status, body = _request(real_search.url, "POST", "/exa/search", body=b"{}")
    assert (status, body) == (503, "pis-broker: no key for exa")
    assert real_search.seen == []  # 上流へは何も出ていない


def test_real_envoy_injects_only_the_routes_own_key(real_search):
    evil = {
        "X-Subscription-Token": "INNER-1",
        "x-api-key": "INNER-2",
        "Authorization": "Bearer INNER-3",
        "X-Other": "kept",
    }
    status, body = _request(
        real_search.url, "GET", "/brave/res/v1/web/search?q=hello&count=3", evil
    )
    assert (status, body) == (200, "upstream-ok")
    method, path, headers = real_search.seen[-1]
    headers = _lower(headers)
    assert (method, path) == ("GET", "/res/v1/web/search?q=hello&count=3")
    assert headers["x-subscription-token"] == KEYS["brave"]
    assert "x-api-key" not in headers and "authorization" not in headers
    assert headers["x-other"] == "kept"
    assert headers["host"] == "api.search.brave.com"

    status, _ = _request(real_search.url, "POST", "/tavily/search", evil, b"{}")
    assert status == 200
    method, path, headers = real_search.seen[-1]
    headers = _lower(headers)
    assert (method, path) == ("POST", "/search")
    assert headers["authorization"] == "Bearer " + KEYS["tavily"]
    assert "x-api-key" not in headers and "x-subscription-token" not in headers
    assert headers["host"] == "api.tavily.com"


def test_real_envoy_keyless_routes_drop_every_auth_header(real_search):
    evil = {
        "X-Subscription-Token": "INNER-1",
        "x-api-key": "INNER-2",
        "Authorization": "B INNER",
        "Proxy-Authorization": "B INNER-4",
    }
    assert _request(real_search.url, "GET", "/openalex/works?search=x", evil)[0] == 200
    method, path, headers = real_search.seen[-1]
    assert (method, path) == ("GET", "/works?search=x")
    assert not {"x-subscription-token", "x-api-key", "authorization"} & set(_lower(headers))
    assert _lower(headers)["host"] == "api.openalex.org"
    for verb in ("GET", "POST"):
        assert _request(real_search.url, verb, "/ddg/html/", evil, b"q=x")[0] == 200
        method, path, headers = real_search.seen[-1]
        assert (method, path) == (verb, "/html/")
        assert not {"x-subscription-token", "x-api-key", "authorization"} & set(_lower(headers))
        assert _lower(headers)["host"] == "html.duckduckgo.com"
    assert _request(real_search.url, "GET", "/ddg/other")[0] == 403


def test_real_envoy_keyless_routes_drop_every_auth_header_proxy(real_search):
    # Proxy-Authorization も、どの経路でも上流へ出さない
    evil = {"Proxy-Authorization": "B INNER-4"}
    assert _request(real_search.url, "GET", "/openalex/works?search=x", evil)[0] == 200
    assert "proxy-authorization" not in _lower(real_search.seen[-1][2])
    assert _request(real_search.url, "GET", "/brave/res/v1/web/search?q=x", evil)[0] == 200
    assert "proxy-authorization" not in _lower(real_search.seen[-1][2])


@pytest.mark.parametrize(
    "path",
    [
        "/brave/../exa/search",
        "//brave/res/v1/web/search?q=x",
        "/brave/res/v1/web/%2e%2e/%2e%2e/%2e%2e/exa/search",
        "/brave/res/v1/web/search/../../../../tavily/search",
        "/brave//res/v1/web/search?q=x",
        "/BRAVE/res/v1/web/search?q=x",
        "/brave/res/v1/web/search%2f..%2f..%2ftavily%2fsearch",
    ],
)
@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_real_envoy_odd_paths_never_carry_another_providers_key(real_search, path, verb):
    # 正規化やエンコードで別の経路へ抑けても、上流へ出る要求は「許可した組」で、その経路自身の鍵だけ
    before = len(real_search.seen)
    evil = {"x-api-key": "INNER-2", "Authorization": "Bearer INNER-3"}
    status, _ = _request(real_search.url, verb, path, evil, b"{}" if verb == "POST" else b"")
    for method, upstream_path, headers in real_search.seen[before:]:
        headers = _lower(headers)
        assert "INNER-2" not in headers.get("x-api-key", "")
        assert "INNER-3" not in headers.get("authorization", "")
        if (method, upstream_path.split("?")[0]) == ("GET", "/res/v1/web/search"):
            assert headers["x-subscription-token"] == KEYS["brave"]
            assert "authorization" not in headers and "x-api-key" not in headers
        elif (method, upstream_path) == ("POST", "/search"):
            assert headers["authorization"] == "Bearer " + KEYS["tavily"]
            assert "x-subscription-token" not in headers and "x-api-key" not in headers
        else:
            raise AssertionError(f"許可していない要求が上流へ出た: {method} {upstream_path}")
    assert status in (200, 400, 403, 404, 503)


def test_real_envoy_access_log_has_neither_the_query_nor_the_keys(real_search):
    query = "SECRET-QUERY-WORDS"
    headers = {"X-Subscription-Token": "INNER-LOG"}
    assert (
        _request(real_search.url, "GET", f"/brave/res/v1/web/search?q={query}", headers)[0] == 200
    )
    real_search.stop()  # Envoy を止めてログを出し切らせる
    (text,) = real_search.final_log
    assert "ACCESS search GET /res/v1/web/search 200" in text  # ログは接頭辞を除いた後のパス
    for hidden in (query, "INNER-LOG", KEYS["brave"], "q="):
        assert hidden not in text
