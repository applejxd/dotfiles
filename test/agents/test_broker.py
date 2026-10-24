"""``pis`` の Copilot ブローカー自動起動 (rules.json の ``broker.copilot`` = ``auto``) の試験。

本物の Envoy とネットワークは使わない。トークンの取得は差し替え、``envoy`` は PATH に置く偽物
(設定の ``port_value`` で ``/__pis_broker`` に答える Python スクリプト) にする。
see docs/spec/pi-guard.md
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from agents_common import ROOT

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="境界は Linux 専用")

LIB = ROOT / "home" / "dot_local" / "share" / "ocs"
LAUNCHER = ROOT / "home" / "dot_local" / "bin" / "executable_ocs"

REFRESH = "ghu_REFRESH_SECRET_VALUE"
TOKEN1 = "tid=TOKEN_ONE_SECRET;proxy-ep=proxy.individual.githubcopilot.com;exp=1"
TOKEN2 = "tid=TOKEN_TWO_SECRET;proxy-ep=proxy.individual.githubcopilot.com;exp=2"

FAKE_ENVOY = """#!{python}
import http.server
import os
import re
import socketserver
import sys
import threading

cfg = sys.argv[sys.argv.index("--config-path") + 1]
text = open(cfg, encoding="utf-8").read()
with open(os.path.join(os.path.dirname(cfg), "fake.pid"), "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/__pis_broker"
        body = b"pis-broker-copilot" if ok else b"no"
        self.send_response(200 if ok else 403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class UnixHandler(http.server.BaseHTTPRequestHandler):
    # GitHub のリスナーの「*」の仮想ホストと同じ答え (403 + pis-broker: ...)
    def do_GET(self):
        body = b"pis-broker: host not allowed"
        self.send_response(403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


servers = []
tcp = re.search(r"address: 127[.]0[.]0[.]1, port_value: (\\d+)", text)
if tcp:
    servers.append(http.server.HTTPServer(("127.0.0.1", int(tcp.group(1))), Handler))
pipe = re.search(r'pipe: [{]path: "([^"]+)"', text)
if pipe:
    if os.path.exists(pipe.group(1)):
        os.unlink(pipe.group(1))
    servers.append(socketserver.UnixStreamServer(pipe.group(1), UnixHandler))
for extra in servers[1:]:
    threading.Thread(target=extra.serve_forever, daemon=True).start()
servers[0].serve_forever()
"""

FAILING_ENVOY = """#!{python}
import sys

print("boom: bad config", file=sys.stderr)
sys.exit(1)
"""


def _ocs() -> SimpleNamespace:
    """ランチャーの本体を source state から読み込む (配備先は読まない)。"""
    namespace: dict = {"__name__": "probe"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), "launcher", "exec"), namespace)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        namespace["load"](LIB)
        importlib.import_module("ocs_lib.pi")
        importlib.import_module("ocs_lib.pis")
    finally:
        sys.dont_write_bytecode = saved
    return SimpleNamespace(
        pi=sys.modules["ocs_lib.pi"],
        pis=sys.modules["ocs_lib.pis"],
        broker=sys.modules["ocs_lib.broker"],
    )


def _install_envoy(directory: Path, script: str = FAKE_ENVOY) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "envoy"
    path.write_text(script.replace("{python}", sys.executable), encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """ホスト側の環境: 偽の envoy を PATH に置き、auth.json と XDG_RUNTIME_DIR を用意する。"""
    home = tmp_path / "home"
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "auth.json").write_text(
        json.dumps({"github-copilot": {"type": "oauth", "refresh": REFRESH, "expires": 1}}),
        encoding="utf-8",
    )
    runtime = tmp_path / "run"
    runtime.mkdir()
    bin_dir = tmp_path / "bin"
    _install_envoy(bin_dir)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr(_ocs().broker, "find_ca_file", lambda: str(ca))
    return SimpleNamespace(home=home, agent=agent, runtime=runtime, bin=bin_dir)


def _fake_exchange(monkeypatch, broker, results):
    """``exchange`` を差し替える。``results`` は順に返す (例外なら送出)。尽きたら最後を繰り返す。"""
    calls: list[str] = []

    def exchange(refresh):
        calls.append(refresh)
        item = results[min(len(calls) - 1, len(results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(broker, "exchange", exchange)
    return calls


def _far() -> int:
    return int(time.time()) + 3600


def _wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _sds_token(state: Path) -> str:
    body = json.loads((state / "copilot-sds.json").read_text(encoding="utf-8"))
    return body["resources"][0]["generic_secret"]["secret"]["inline_string"]


# ─── (a) auto の判定と、手動モードの検証 ────────────────────────────


@pytest.mark.parametrize("value", ["auto", "AUTO", "Auto"])
def test_auto_is_case_insensitive(value):
    assert _ocs().pi.is_auto_broker(value)


@pytest.mark.parametrize("value", [None, "", " auto", "auto ", "http://127.0.0.1:18080", "autox"])
def test_only_the_exact_word_is_auto(value):
    assert not _ocs().pi.is_auto_broker(value)


def test_manual_mode_validation_is_unchanged(capsys):
    pi = _ocs().pi
    assert pi.parse_broker("http://127.0.0.1:18080") == ("http://127.0.0.1:18080", 18080)
    assert pi.parse_broker(None) is None and pi.parse_broker("") is None
    for bad in ("auto", "http://example.com:18080", "http://127.0.0.1", "http://127.0.0.1:80"):
        with pytest.raises(SystemExit):
            pi.parse_broker(bad)
    assert "broker.copilot" in capsys.readouterr().err


# ─── (b) 設定の置換 ─────────────────────────────────────────────────


def _render(broker, tmp_path, host="api.example.test", ca="/etc/ssl/ca.pem", **kwargs):
    """Copilot だけ有効の設定 (``**kwargs`` で ``build_config`` の引数を上書きできる)。"""
    options = {"copilot_port": 12345, "copilot_host": host, "sds_dir": tmp_path, "ca_file": ca}
    return broker.build_config(**{**options, **kwargs})


def test_render_config_fills_every_placeholder(tmp_path):
    broker = _ocs().broker
    out = _render(broker, tmp_path)
    assert not re.search(r"@(PORT|HOST|SDS_DIR|CA_FILE|SOCKET|LISTENERS|CLUSTERS)@", out)
    assert "port_value: 12345}" in out
    assert out.count('"api.example.test"') == 3  # host_rewrite_literal・接続先・SNI
    assert f'path: "{tmp_path}/copilot-sds.json"' in out
    assert f'watched_directory: {{path: "{tmp_path}"}}' in out
    assert '"@type"' in out  # 型の指定は置換の対象ではない
    for absent in ("github_upstream", "gh_token", "pipe:", "gh-sds.json"):
        assert absent not in out  # Copilot だけ有効なら GitHub の要素は出ない
    assert broker.CLUSTERS_MARK.strip() not in out


def test_config_verifies_the_upstream_certificate(tmp_path):
    broker = _ocs().broker
    out = _render(broker, tmp_path, ca="/etc/ssl/ca.pem")
    assert 'trusted_ca: {filename: "/etc/ssl/ca.pem"}' in out
    assert (
        'match_typed_subject_alt_names: [{san_type: DNS, matcher: {suffix: "githubcopilot.com"}}]'
        in out
    )


def test_allowed_routes_are_exact_paths(tmp_path):
    out = _render(_ocs().broker, tmp_path)
    assert "path_separated_prefix" not in out
    for route in ("/v1/messages", "/responses", "/chat/completions"):
        assert f'{{path: "{route}"' in out


@pytest.mark.parametrize("bad", ['/tmp/a"b.pem', "/tmp/a\nb.pem", "/tmp/a\\b.pem"])
def test_render_config_rejects_paths_that_break_the_yaml_string(tmp_path, bad):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError):
        _render(broker, tmp_path, ca=bad)
    with pytest.raises(broker.BrokerError):
        _render(broker, tmp_path, github_socket=Path(bad))


def test_ca_file_prefers_the_default_then_falls_back(tmp_path, monkeypatch):
    broker = _ocs().broker
    default = tmp_path / "default.pem"
    default.write_text("x", encoding="utf-8")
    other = tmp_path / "other.pem"
    other.write_text("x", encoding="utf-8")
    paths = SimpleNamespace(cafile=str(default))
    monkeypatch.setattr(broker.ssl, "get_default_verify_paths", lambda: paths)
    monkeypatch.setattr(broker, "CA_FALLBACKS", (str(other),))
    assert broker.find_ca_file() == str(default)
    paths.cafile = str(tmp_path / "missing.pem")
    assert broker.find_ca_file() == str(other)


def test_missing_ca_file_refuses_to_start(tmp_path, monkeypatch):
    broker = _ocs().broker
    monkeypatch.setattr(
        broker.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile=str(tmp_path / "none.pem")),
    )
    monkeypatch.setattr(broker, "CA_FALLBACKS", (str(tmp_path / "none2.pem"),))
    with pytest.raises(broker.BrokerError, match="CA"):
        broker.find_ca_file()


def test_session_refuses_to_start_without_a_ca_file(host, monkeypatch):
    broker = _ocs().broker
    _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])

    def no_ca():
        raise broker.BrokerError("CA が無い")

    monkeypatch.setattr(broker, "find_ca_file", no_ca)
    with pytest.raises(broker.BrokerError, match="CA"), broker.session(host.agent, home=host.home):
        pass
    assert not list(host.runtime.glob("pis-broker-*"))


def test_rendered_config_is_valid_yaml(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    out = _render(broker, tmp_path)
    data = yaml.safe_load(out)
    (listener,) = data["static_resources"]["listeners"]
    assert listener["name"] == "copilot"
    assert listener["address"]["socket_address"] == {"address": "127.0.0.1", "port_value": 12345}
    (cluster,) = data["static_resources"]["clusters"]
    assert cluster["name"] == "copilot_upstream"
    context = cluster["transport_socket"]["typed_config"]
    validation = context["common_tls_context"]["validation_context"]
    assert validation["trusted_ca"] == {"filename": "/etc/ssl/ca.pem"}


def test_upstream_host_follows_proxy_ep_and_rejects_odd_values():
    broker = _ocs().broker
    assert broker.upstream_host(TOKEN1) == "api.individual.githubcopilot.com"
    assert broker.upstream_host("a=b;proxy-ep=proxy.business.githubcopilot.com") == (
        "api.business.githubcopilot.com"
    )
    assert broker.upstream_host("no endpoint") == broker.DEFAULT_HOST
    for bad in ("proxy-ep=proxy.x.com\nevil: 1", "proxy-ep=proxy.evil.example", "proxy-ep=x.com"):
        with pytest.raises(broker.BrokerError, match="上流"):
            broker.upstream_host(bad)


# ─── (c) session のライフサイクル ───────────────────────────────────


def test_session_starts_envoy_and_cleans_up(host, monkeypatch, capsys):
    broker = _ocs().broker
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with broker.session(host.agent, home=host.home) as started:
        url = started.url
        match = re.fullmatch(r"http://127\.0\.0\.1:(\d+)", url)
        assert match
        (state,) = host.runtime.glob("pis-broker-*")
        assert started.state == state
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        sds = state / "copilot-sds.json"
        assert stat.S_IMODE(sds.stat().st_mode) == 0o600
        assert _sds_token(state) == TOKEN1
        config = (state / "envoy.yaml").read_text(encoding="utf-8")
        assert f"port_value: {match.group(1)}}}" in config
        assert "api.individual.githubcopilot.com" in config
        pid = int((state / "fake.pid").read_text(encoding="utf-8"))
        os.kill(pid, 0)  # 生きている
    assert calls == [REFRESH]
    assert not list(host.runtime.glob("pis-broker-*"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    # (f) トークンの値は出力へ出ない
    captured = capsys.readouterr()
    for secret in (REFRESH, "TOKEN_ONE_SECRET"):
        assert secret not in captured.out + captured.err


def test_session_cleans_up_when_the_body_raises(host, monkeypatch):
    broker = _ocs().broker
    _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with pytest.raises(RuntimeError, match="boom"), broker.session(host.agent, home=host.home):
        raise RuntimeError("boom")
    assert not list(host.runtime.glob("pis-broker-*"))


def test_two_sessions_get_separate_ports_and_state(host, monkeypatch):
    broker = _ocs().broker
    _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with (
        broker.session(host.agent, home=host.home) as first,
        broker.session(host.agent, home=host.home) as second,
    ):
        assert first.url != second.url
        assert first.state != second.state
        assert len(list(host.runtime.glob("pis-broker-*"))) == 2
    assert not list(host.runtime.glob("pis-broker-*"))


def test_state_dir_falls_back_to_home_without_xdg_runtime_dir(host, monkeypatch):
    broker = _ocs().broker
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with broker.session(host.agent, home=host.home):
        (state,) = (host.home / ".local" / "state" / "pis").glob("pis-broker-*")
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert not list((host.home / ".local" / "state" / "pis").glob("pis-broker-*"))


def test_envoy_exiting_early_reports_its_log_and_cleans_up(host, monkeypatch):
    broker = _ocs().broker
    _install_envoy(host.bin, FAILING_ENVOY)
    _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with pytest.raises(broker.BrokerError) as info, broker.session(host.agent, home=host.home):
        pass
    assert "boom: bad config" in str(info.value)
    assert "TOKEN_ONE_SECRET" not in str(info.value)
    assert not list(host.runtime.glob("pis-broker-*"))


# ─── (d) envoy が無いとき ───────────────────────────────────────────


def test_missing_envoy_is_a_clear_error(host, monkeypatch):
    broker = _ocs().broker
    empty = host.runtime / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with pytest.raises(broker.BrokerError) as info, broker.session(host.agent, home=host.home):
        pass
    assert "envoy" in str(info.value)
    assert "~/.local/bin/envoy" in info.value.hint and "sha256" in info.value.hint
    assert calls == []  # 取得もせず、状態も作らない
    assert not list(host.runtime.glob("pis-broker-*"))


def test_envoy_in_local_bin_is_found(host, monkeypatch):
    broker = _ocs().broker
    empty = host.runtime / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    _install_envoy(host.home / ".local" / "bin")
    assert broker.find_envoy(host.home) == str(host.home / ".local" / "bin" / "envoy")


def test_missing_copilot_credentials_is_an_error(host, monkeypatch):
    broker = _ocs().broker
    (host.agent / "auth.json").write_text("{}", encoding="utf-8")
    with pytest.raises(broker.BrokerError, match="github-copilot"):
        broker.load_refresh_token(host.agent)


# ─── (e) 更新スレッド ───────────────────────────────────────────────


def test_refresh_rewrites_sds_before_expiry(host, monkeypatch):
    broker = _ocs().broker
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, int(time.time()) + 1), (TOKEN2, _far())])
    with broker.session(host.agent, home=host.home, refresh_margin=0):
        (state,) = host.runtime.glob("pis-broker-*")
        assert _wait_for(lambda: _sds_token(state) == TOKEN2)
        assert stat.S_IMODE((state / "copilot-sds.json").stat().st_mode) == 0o600
    assert calls == [REFRESH, REFRESH]


def test_refresh_failure_is_logged_without_the_token_and_retried(host, monkeypatch):
    broker = _ocs().broker
    _fake_exchange(
        monkeypatch,
        broker,
        [
            (TOKEN1, int(time.time()) + 1),
            broker.BrokerError("Copilot のトークンを取れない (HTTP 500)"),
            (TOKEN2, _far()),
        ],
    )
    with broker.session(host.agent, home=host.home, refresh_margin=0, retry_seconds=0.1):
        (state,) = host.runtime.glob("pis-broker-*")
        assert _wait_for(lambda: _sds_token(state) == TOKEN2)
        log = (state / "broker.log").read_text(encoding="utf-8")
        assert "トークンの更新に失敗" in log and "HTTP 500" in log
        for secret in (REFRESH, "TOKEN_ONE_SECRET", "TOKEN_TWO_SECRET"):
            assert secret not in log


# ─── (f) トークンの値を出さない ─────────────────────────────────────


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def test_exchange_sends_the_copilot_headers_and_parses_the_reply(monkeypatch):
    broker = _ocs().broker
    seen = {}

    def urlopen(request, timeout):
        seen["request"] = request
        return _Response(json.dumps({"token": TOKEN1, "expires_at": 1234}).encode())

    monkeypatch.setattr(broker.urllib.request, "urlopen", urlopen)
    assert broker.exchange(REFRESH) == (TOKEN1, 1234)
    request = seen["request"]
    assert request.full_url == "https://api.github.com/copilot_internal/v2/token"
    assert request.get_header("Authorization") == f"Bearer {REFRESH}"
    assert request.get_header("Copilot-integration-id") == "vscode-chat"


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("https://x", 401, "bad", None, None),
        urllib.error.URLError("down"),
        TimeoutError("slow"),
    ],
)
def test_exchange_errors_do_not_carry_the_token(monkeypatch, failure):
    broker = _ocs().broker

    def urlopen(request, timeout):
        raise failure

    monkeypatch.setattr(broker.urllib.request, "urlopen", urlopen)
    with pytest.raises(broker.BrokerError) as info:
        broker.exchange(REFRESH)
    assert REFRESH not in str(info.value)


def test_exchange_rejects_an_unexpected_reply(monkeypatch):
    broker = _ocs().broker
    monkeypatch.setattr(
        broker.urllib.request, "urlopen", lambda request, timeout: _Response(b'{"token": 1}')
    )
    with pytest.raises(broker.BrokerError, match="形が想定と違う"):
        broker.exchange(REFRESH)


# ─── (g) pi.py の自動モード ─────────────────────────────────────────


def _recording_session(pi, events, url="http://127.0.0.1:18081"):
    @contextlib.contextmanager
    def session(*args, **kwargs):
        events.append(("enter", args, kwargs))
        try:
            yield pi.broker.BrokerSession(url, Path("/nonexistent/run/pis-broker-x"))
        finally:
            events.append(("exit",))

    return session


def _rules(tmp_path, monkeypatch, pi, copilot):
    """``broker.copilot`` だけを持つ rules.json を ``pi.RULES`` に差す (None なら ``broker`` 節なし)。"""
    path = tmp_path / "rules.json"
    body = {} if copilot is None else {"broker": {"copilot": copilot}}
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(pi, "RULES", path)


def _args(no_broker=False):
    return SimpleNamespace(no_broker=no_broker)


def _agent_home(pi, monkeypatch, tmp_path):
    """境界用 agent 置き場の親 (``AGENT_HOME``) を ``tmp_path`` へ差し替える (本物の置き場を汚さない)。"""
    home = tmp_path / "sandbox"
    monkeypatch.setattr(pi, "AGENT_HOME", home)
    return home


def test_auto_mode_enters_the_session_and_passes_the_url_on(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "Auto")

    def launch_with(args, passthrough, value, state=None, **kwargs):
        events.append(("launch", value))
        return 7

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    assert pi._launch(_args(), []) == 7
    assert [e[0] for e in events] == ["enter", "launch", "exit"]  # 起動の間ずっと有効
    assert events[0][1] == (pi.REAL_AGENT,)
    assert events[0][2] == {"copilot": True, "github_token": None, "github_socket": None}
    assert events[1] == ("launch", "http://127.0.0.1:18081")


def test_auto_mode_stops_the_broker_when_the_launch_raises(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "auto")

    def launch_with(args, passthrough, value, state=None, **kwargs):
        raise SystemExit(3)

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert events[-1] == ("exit",)


def test_auto_mode_turns_a_broker_error_into_die(monkeypatch, capsys, tmp_path):
    pi = _ocs().pi
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)

    @contextlib.contextmanager
    def failing(*args, **kwargs):
        raise pi.broker.BrokerError("envoy が見つからない", "導入の案内")
        yield  # pragma: no cover

    monkeypatch.setattr(pi.broker, "session", failing)
    _rules(tmp_path, monkeypatch, pi, "auto")
    monkeypatch.setattr(pi, "_launch_with", lambda *a, **k: pytest.fail("起動してはいけない"))
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    err = capsys.readouterr().err
    assert "envoy が見つからない" in err and "導入の案内" in err
    assert "--no-broker" in err  # 一時的に外す手段を案内する
    assert not list((tmp_path / "sandbox").glob("agent-*"))  # agent 置き場も残さない


def test_manual_mode_does_not_start_a_broker(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "http://127.0.0.1:18080")
    seen = []
    monkeypatch.setattr(
        pi, "_launch_with", lambda args, p, value, s=None, **k: seen.append(value) or 0
    )
    assert pi._launch(_args(), []) == 0
    assert events == [] and seen == ["http://127.0.0.1:18080"]


@pytest.mark.parametrize("copilot", ["off", None], ids=["off", "no-broker-section"])
def test_off_or_missing_setting_uses_no_broker(monkeypatch, tmp_path, copilot):
    pi = _ocs().pi
    events: list = []
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, copilot)
    seen = []
    monkeypatch.setattr(
        pi, "_launch_with", lambda args, p, value, s=None, **k: seen.append(value) or 0
    )
    assert pi._launch(_args(), []) == 0
    assert events == [] and seen == [None]


@pytest.mark.parametrize("copilot", ["auto", "http://127.0.0.1:18080"])
def test_no_broker_flag_overrides_the_setting_and_warns(monkeypatch, tmp_path, capsys, copilot):
    pi = _ocs().pi
    events: list = []
    _agent_home(pi, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, copilot)
    seen = []
    monkeypatch.setattr(
        pi, "_launch_with", lambda args, p, value, s=None, **k: seen.append(value) or 0
    )
    assert pi._launch(_args(no_broker=True), []) == 0
    assert events == [] and seen == [None]
    assert "ブローカー無し" in capsys.readouterr().err


def test_broker_setting_must_be_a_string(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    _rules(tmp_path, monkeypatch, pi, 1)
    with pytest.raises(SystemExit):
        pi.read_broker_setting()
    assert "broker.copilot" in capsys.readouterr().err


@pytest.mark.parametrize(
    "body",
    [{"broker": None}, {"broker": "auto"}, {"broker": []}, {"broker": {"copilot": None}}],
    ids=["null-section", "string-section", "list-section", "null-copilot"],
)
def test_broken_broker_setting_fails_closed(monkeypatch, tmp_path, capsys, body):
    pi = _ocs().pi
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(pi, "RULES", path)
    with pytest.raises(SystemExit):
        pi.read_broker_setting()
    assert "broker" in capsys.readouterr().err


def _stub_launch(pi, monkeypatch, tmp_path):
    """``_launch_with`` の前半 (境界の検証) を素通りさせ、agent 置き場を ``tmp_path`` に作る。"""
    runtime = tmp_path / "fence"
    runtime.write_text("", encoding="utf-8")
    agent = tmp_path / "agent-copy"
    agent.mkdir()
    monkeypatch.setattr(
        pi.boundary, "load_boundary", lambda *a, **k: {"runtime_path": str(runtime)}
    )
    for name in (
        "reject_unsafe_workspace",
        "reject_control_dirs",
        "reject_protected_workspace",
        "announce_request",
    ):
        monkeypatch.setattr(pi.boundary, name, lambda *a, **k: None)
    monkeypatch.setattr(pi.boundary, "read_request", lambda *a, **k: None)
    populated = []
    monkeypatch.setattr(pi, "populate_agent_dir", lambda a, *args, **k: populated.append(a))
    return agent, populated


def test_agent_dir_is_removed_when_a_later_step_raises(monkeypatch, tmp_path):
    pi = _ocs().pi
    agent, _ = _stub_launch(pi, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pi, "sessions_dir", boom)
    with pytest.raises(RuntimeError, match="boom"):
        pi._launch_with(_args(), [], None, agent=agent)
    assert not agent.exists()


@pytest.mark.parametrize("where", ["inside-workspace", "workspace-inside-base"])
def test_state_dir_overlapping_the_workspace_is_refused(monkeypatch, tmp_path, capsys, where):
    pi = _ocs().pi
    agent, populated = _stub_launch(pi, monkeypatch, tmp_path)
    work = tmp_path / "work"
    if where == "inside-workspace":
        state = work / "run" / "pis-broker-x"
    else:
        state = tmp_path / "run" / "pis-broker-x"
        work = tmp_path / "run" / "project"
    state.mkdir(parents=True)
    work.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(work)
    with pytest.raises(SystemExit):
        pi._launch_with(_args(), [], None, state, agent=agent)
    assert "重なる" in capsys.readouterr().err
    assert populated == []  # 中身を配置する前に断っている


def test_state_dir_apart_from_the_workspace_passes_the_overlap_check(monkeypatch, tmp_path):
    pi = _ocs().pi
    agent, populated = _stub_launch(pi, monkeypatch, tmp_path)
    state = tmp_path / "run" / "pis-broker-x"
    state.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(pi, "sessions_dir", lambda *a: (_ for _ in ()).throw(RuntimeError("next")))
    with pytest.raises(RuntimeError, match="next"):
        pi._launch_with(_args(), [], None, state, agent=agent)
    assert populated == [agent]  # 重複の検査を越えて先へ進んだ


def test_no_broker_is_parsed_by_pis_and_forwarded(monkeypatch):
    ocs = _ocs()
    assert ocs.pis.parse(["--no-broker", "--bypass", "-c"]).no_broker is True
    assert ocs.pis.parse(["-c"]).no_broker is False
    seen = {}
    monkeypatch.setattr(
        ocs.pi, "_launch", lambda args, rest: seen.update(no_broker=args.no_broker, rest=rest) or 0
    )
    assert ocs.pi.run_sandboxed(["--no-broker", "-c"]) == 0
    assert seen == {"no_broker": True, "rest": ["-c"]}
    assert ocs.pi.run_sandboxed(["-c"]) == 0 and seen["no_broker"] is False


# ─── (h) GitHub の PAT の出どころ (純関数) ────────────────────────────────────────

PAT = "ghp_ExamplePatValue0123456789"
BAD_SHAPES = [
    pytest.param("", id="empty"),
    pytest.param("\n", id="only-newline"),
    pytest.param("tok en", id="space-inside"),
    pytest.param("line1\nline2", id="newline-inside"),
    pytest.param("\u65e5\u672c\u8a9e", id="non-ascii"),
    pytest.param("a" * 256, id="too-long"),
    pytest.param(" leading", id="leading-space"),
    pytest.param("tab\tinside", id="tab-inside"),
]


def _token_file(directory: Path, body, mode=0o600, name="github-token") -> Path:
    path = directory / name
    path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    path.chmod(mode)
    return path


def _python_prints(value: str) -> list[str]:
    """``value`` を標準出力へそのまま (改行なしで) 出す argv。"""
    return [sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", value]


@pytest.fixture
def short_dir():
    """Unix ソケットのパス上限 (107 バイト) に収まる短い一時ディレクトリ。"""
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="pg") as name:
        yield Path(name)


@pytest.mark.parametrize("suffix", ["", "\n", "\r\n", " \t\n"])
def test_token_file_is_read_and_trailing_whitespace_is_stripped(tmp_path, suffix):
    broker = _ocs().broker
    assert broker.read_token_file(_token_file(tmp_path, PAT + suffix)) == PAT


def test_token_file_length_bounds(tmp_path):
    broker = _ocs().broker
    assert broker.read_token_file(_token_file(tmp_path, "a")) == "a"
    assert broker.read_token_file(_token_file(tmp_path, "a" * 255)) == "a" * 255


def test_missing_token_file_is_no_source(tmp_path):
    broker = _ocs().broker
    assert broker.read_token_file(tmp_path / "none") is None
    assert broker.read_token_file(tmp_path / "no-dir" / "none") is None


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666, 0o660])
def test_token_file_with_group_or_other_access_is_refused(tmp_path, mode):
    broker = _ocs().broker
    path = _token_file(tmp_path, PAT, mode)
    with pytest.raises(broker.BrokerError, match="権限") as info:
        broker.read_token_file(path)
    assert PAT not in str(info.value) and PAT not in info.value.hint


def test_token_file_symlink_is_refused(tmp_path):
    broker = _ocs().broker
    real = _token_file(tmp_path, PAT)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(broker.BrokerError):
        broker.read_token_file(link)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "gone")
    with pytest.raises(broker.BrokerError):  # 「無し」ではなく拒否
        broker.read_token_file(dangling)


def test_token_file_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    broker = _ocs().broker
    path = _token_file(tmp_path, PAT)
    real_uid = os.getuid()
    monkeypatch.setattr(broker.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(broker.BrokerError, match="所有者") as info:
        broker.read_token_file(path)
    assert PAT not in str(info.value)


def test_token_file_must_be_a_regular_file(tmp_path):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError, match="通常ファイル"):
        broker.read_token_file(tmp_path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(broker.BrokerError, match="通常ファイル"):  # 開いて止まらない
        broker.read_token_file(fifo)


def test_token_file_over_the_size_limit_is_refused(tmp_path):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError, match="大きすぎ"):
        broker.read_token_file(_token_file(tmp_path, "a" * 4097))


@pytest.mark.parametrize("body", BAD_SHAPES)
def test_token_file_with_a_bad_shape_is_refused_without_the_value(tmp_path, body):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError) as info:
        broker.read_token_file(_token_file(tmp_path, body))
    text = str(info.value) + info.value.hint
    if body.strip():
        assert body not in text


def test_token_file_that_is_not_utf8_is_refused(tmp_path):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError):
        broker.read_token_file(_token_file(tmp_path, b"\xff\xfe\xfa"))


def test_token_command_success_strips_trailing_whitespace():
    broker = _ocs().broker
    assert broker.run_token_command(_python_prints(PAT + "\n")) == PAT
    assert broker.run_token_command(_python_prints("a" * 255)) == "a" * 255


def test_token_command_inherits_the_host_environment(monkeypatch):
    broker = _ocs().broker
    monkeypatch.setenv("PIS_TEST_PAT", PAT)
    argv = [sys.executable, "-c", "import os; print(os.environ['PIS_TEST_PAT'])"]
    assert broker.run_token_command(argv) == PAT


def test_token_command_has_no_stdin_and_no_shell():
    broker = _ocs().broker
    argv = [sys.executable, "-c", "import sys; sys.stdout.write('x' + sys.stdin.read())"]
    assert broker.run_token_command(argv) == "x"  # stdin は空 (待たない)
    # シェルを通らない: メタ文字はそのまま引数になる
    assert broker.run_token_command(_python_prints("a$(echo)b;c")) == "a$(echo)b;c"


def test_token_command_failure_modes_are_no_source(monkeypatch, tmp_path):
    broker = _ocs().broker
    failing = [sys.executable, "-c", "import sys; sys.stdout.write('tok'); sys.exit(3)"]
    assert broker.run_token_command(failing) is None  # 終了コードが 0 でない
    assert broker.run_token_command(["/nonexistent/pis-test-command"]) is None
    not_executable = tmp_path / "plain"
    not_executable.write_text("x", encoding="utf-8")
    assert broker.run_token_command([str(not_executable)]) is None
    huge = [sys.executable, "-c", "print('a' * 5000)"]
    assert broker.run_token_command(huge) is None  # 4096 バイト超
    monkeypatch.setattr(broker, "GH_COMMAND_TIMEOUT_SECONDS", 0.5)
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    assert broker.run_token_command(slow) is None  # タイムアウト


def test_token_command_stderr_is_discarded(capfd):
    broker = _ocs().broker
    script = f"import sys; sys.stderr.write({PAT!r}); sys.exit(1)"
    assert broker.run_token_command([sys.executable, "-c", script]) is None
    captured = capfd.readouterr()
    assert PAT not in captured.out + captured.err


@pytest.mark.parametrize("value", BAD_SHAPES)
def test_token_command_with_a_bad_shape_is_refused_without_the_value(value, capfd):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError) as info:
        broker.run_token_command(_python_prints(value))
    if value.strip():
        assert value not in str(info.value) + info.value.hint
    captured = capfd.readouterr()
    if value.strip():
        assert value not in captured.out + captured.err


def test_token_command_rejects_empty_or_nul_argv():
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError):
        broker.run_token_command([])
    with pytest.raises(broker.BrokerError):
        broker.run_token_command(["echo", "a\0b"])


def test_resolve_github_token_picks_the_configured_source(tmp_path, monkeypatch):
    broker = _ocs().broker
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".config" / "pis").mkdir(parents=True)
    _token_file(tmp_path / ".config" / "pis", PAT)
    assert broker.resolve_github_token("~/.config/pis/github-token", None) == PAT  # ~ を展開
    assert broker.resolve_github_token(None, _python_prints(PAT)) == PAT
    assert broker.resolve_github_token("~/.config/pis/none", None) is None
    assert broker.resolve_github_token(None, None) is None
    with pytest.raises(broker.BrokerError, match="両方"):
        broker.resolve_github_token("~/x", ["echo"])


def test_github_origin_names_the_file_or_the_first_word(tmp_path, monkeypatch):
    broker = _ocs().broker
    monkeypatch.setenv("HOME", str(tmp_path))
    assert broker.github_origin("~/t", None) == str(tmp_path / "t")
    assert broker.github_origin(None, ["bw", "get", "password", "SECRET-ITEM"]) == "bw"
    assert broker.github_origin(None, None) is None


# ─── (i) Envoy の設定の生成 ──────────────────────────────────────────

SOCKET = Path("/tmp/pg-x/gh.sock")


def _github_config(broker, tmp_path, **kwargs):
    options = {"sds_dir": tmp_path, "ca_file": "/etc/ssl/ca.pem", "github_socket": SOCKET}
    return broker.build_config(**{**options, **kwargs})


def _http_manager(listener):
    return listener["filter_chains"][0]["filters"][0]["typed_config"]


def test_github_only_config_has_only_the_github_pieces(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    out = _github_config(broker, tmp_path)
    assert not re.search(r"@(PORT|HOST|SDS_DIR|CA_FILE|SOCKET|LISTENERS|CLUSTERS)@", out)
    data = yaml.safe_load(out)
    (listener,) = data["static_resources"]["listeners"]
    (cluster,) = data["static_resources"]["clusters"]
    assert listener["name"] == "github" and cluster["name"] == "github_upstream"
    assert listener["address"] == {"pipe": {"path": str(SOCKET), "mode": 0o600}}
    for absent in ("copilot_upstream", "copilot_token", "copilot-sds", "127.0.0.1"):
        assert absent not in out


def test_github_listener_routes_only_api_github_com(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    data = yaml.safe_load(_github_config(broker, tmp_path))
    manager = _http_manager(data["static_resources"]["listeners"][0])
    assert manager["stat_prefix"] == "github"
    assert manager["normalize_path"] is True and manager["merge_slashes"] is True
    allowed, denied = manager["route_config"]["virtual_hosts"]
    assert allowed["domains"] == ["api.github.com"]  # 完全一致
    (route,) = allowed["routes"]
    assert route["match"] == {"prefix": "/"}  # メソッド・パスは制限しない
    assert route["route"]["cluster"] == "github_upstream"
    assert route["route"]["host_rewrite_literal"] == "api.github.com"
    assert denied["domains"] == ["*"]
    (deny,) = denied["routes"]
    assert deny["direct_response"] == {
        "status": 403,
        "body": {"inline_string": "pis-broker: host not allowed"},
    }


def test_github_listener_replaces_authorization_with_a_bearer_secret(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    data = yaml.safe_load(_github_config(broker, tmp_path))
    manager = _http_manager(data["static_resources"]["listeners"][0])
    injector, router = manager["http_filters"]
    assert injector["name"] == "envoy.filters.http.credential_injector"
    assert router["name"] == "envoy.filters.http.router"
    config = injector["typed_config"]
    assert config["overwrite"] is True
    generic = config["credential"]["typed_config"]
    assert generic["header"] == "Authorization"
    assert generic["header_value_prefix"] == "Bearer "
    secret = generic["credential"]
    assert secret["name"] == "gh_token"
    source = secret["sds_config"]["path_config_source"]
    assert source["path"] == f"{tmp_path}/gh-sds.json"
    assert source["watched_directory"] == {"path": str(tmp_path)}


def test_github_access_log_has_method_authority_path_and_code_only(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    data = yaml.safe_load(_github_config(broker, tmp_path))
    (log,) = _http_manager(data["static_resources"]["listeners"][0])["access_log"]
    fmt = log["typed_config"]["log_format"]["text_format_source"]["inline_string"]
    assert fmt.split() == [
        "ACCESS",
        "github",
        "%REQ(:METHOD)%",
        "%REQ(:AUTHORITY)%",
        "%REQ(:PATH)%",
        "%RESPONSE_CODE%",
    ]


def test_github_upstream_verifies_the_certificate_and_the_exact_san(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    data = yaml.safe_load(_github_config(broker, tmp_path, ca_file="/etc/ssl/ca.pem"))
    (cluster,) = data["static_resources"]["clusters"]
    endpoint = cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]
    assert endpoint["address"]["socket_address"] == {"address": "api.github.com", "port_value": 443}
    context = cluster["transport_socket"]["typed_config"]
    assert context["sni"] == "api.github.com"
    validation = context["common_tls_context"]["validation_context"]
    assert validation["trusted_ca"] == {"filename": "/etc/ssl/ca.pem"}
    assert validation["match_typed_subject_alt_names"] == [
        {"san_type": "DNS", "matcher": {"exact": "api.github.com"}}
    ]


def test_both_brokers_share_one_config(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    out = _render(broker, tmp_path, github_socket=SOCKET)
    assert not re.search(r"@(PORT|HOST|SDS_DIR|CA_FILE|SOCKET|LISTENERS|CLUSTERS)@", out)
    data = yaml.safe_load(out)
    listeners = data["static_resources"]["listeners"]
    assert [item["name"] for item in listeners] == ["copilot", "github"]
    clusters = data["static_resources"]["clusters"]
    assert [item["name"] for item in clusters] == ["copilot_upstream", "github_upstream"]
    assert (
        f'path: "{tmp_path}/copilot-sds.json"' in out and f'path: "{tmp_path}/gh-sds.json"' in out
    )


def test_config_without_any_broker_is_refused(tmp_path):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError):
        broker.build_config(sds_dir=tmp_path, ca_file="/etc/ssl/ca.pem")


def test_a_too_long_socket_path_is_refused(tmp_path):
    broker = _ocs().broker
    long_path = Path("/tmp") / ("a" * 120) / "gh.sock"
    with pytest.raises(broker.BrokerError, match="長すぎ"):
        _github_config(broker, tmp_path, github_socket=long_path)


# ─── (j) GitHub のブローカーの session ───────────────────────────────────


def _gh_sds(state: Path) -> dict:
    body = json.loads((state / "gh-sds.json").read_text(encoding="utf-8"))
    (resource,) = body["resources"]
    return resource


def test_github_only_session_starts_envoy_on_a_unix_socket(host, monkeypatch, short_dir, capsys):
    broker = _ocs().broker
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    sock = short_dir / "gh.sock"
    with broker.session(
        host.agent, home=host.home, copilot=False, github_token=PAT, github_socket=sock
    ) as started:
        assert started.url is None and started.github_socket == sock
        (state,) = host.runtime.glob("pis-broker-*")
        assert started.state == state
        resource = _gh_sds(state)
        assert resource["name"] == "gh_token"
        assert resource["generic_secret"]["secret"]["inline_string"] == PAT
        assert stat.S_IMODE((state / "gh-sds.json").stat().st_mode) == 0o600
        assert not (state / "copilot-sds.json").exists()
        config = (state / "envoy.yaml").read_text(encoding="utf-8")
        assert f'pipe: {{path: "{sock}"' in config and PAT not in config
        assert "copilot_upstream" not in config
        pid = int((state / "fake.pid").read_text(encoding="utf-8"))
        os.kill(pid, 0)
    assert calls == []  # Copilot のトークンは取らない
    assert not list(host.runtime.glob("pis-broker-*"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    captured = capsys.readouterr()
    assert PAT not in captured.out + captured.err


def test_github_only_session_does_not_need_copilot_credentials(host, monkeypatch, short_dir):
    broker = _ocs().broker
    (host.agent / "auth.json").unlink()
    _fake_exchange(monkeypatch, broker, [broker.BrokerError("呼び出してはいけない")])
    sock = short_dir / "gh.sock"
    with broker.session(
        host.agent, home=host.home, copilot=False, github_token=PAT, github_socket=sock
    ):
        pass


def test_both_brokers_run_in_one_envoy(host, monkeypatch, short_dir):
    broker = _ocs().broker
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    sock = short_dir / "gh.sock"
    with broker.session(
        host.agent, home=host.home, github_token=PAT, github_socket=sock
    ) as started:
        assert started.url and re.fullmatch(r"http://127\.0\.0\.1:\d+", started.url)
        assert started.github_socket == sock
        (state,) = host.runtime.glob("pis-broker-*")  # Envoy は 1 つ、状態も 1 つ
        assert _sds_token(state) == TOKEN1
        assert _gh_sds(state)["generic_secret"]["secret"]["inline_string"] == PAT
        assert len(list(state.glob("fake.pid"))) == 1
    assert calls == [REFRESH]
    assert not list(host.runtime.glob("pis-broker-*"))


def test_session_needs_at_least_one_broker_and_a_socket_with_the_token(host, short_dir):
    broker = _ocs().broker
    with (
        pytest.raises(broker.BrokerError, match="有効なブローカー"),
        broker.session(host.agent, home=host.home, copilot=False),
    ):
        pass
    with (
        pytest.raises(broker.BrokerError, match="組"),
        broker.session(host.agent, home=host.home, copilot=False, github_token=PAT),
    ):
        pass
    assert not list(host.runtime.glob("pis-broker-*"))


def test_github_session_without_envoy_is_a_clear_error(host, short_dir):
    broker = _ocs().broker
    empty = host.runtime / "empty-path"
    empty.mkdir()
    os.environ["PATH"] = str(empty)  # host フィクスチャの monkeypatch が戻す
    with (
        pytest.raises(broker.BrokerError, match="envoy"),
        broker.session(
            host.agent,
            home=host.home,
            copilot=False,
            github_token=PAT,
            github_socket=short_dir / "gh.sock",
        ),
    ):
        pass
    assert not list(host.runtime.glob("pis-broker-*"))


def test_github_session_envoy_exiting_early_cleans_up_without_the_pat(host, short_dir):
    broker = _ocs().broker
    _install_envoy(host.bin, FAILING_ENVOY)
    with (
        pytest.raises(broker.BrokerError) as info,
        broker.session(
            host.agent,
            home=host.home,
            copilot=False,
            github_token=PAT,
            github_socket=short_dir / "gh.sock",
        ),
    ):
        pass
    assert "boom: bad config" in str(info.value) and PAT not in str(info.value)
    assert not list(host.runtime.glob("pis-broker-*"))


def test_unix_probe_is_false_until_something_answers(short_dir):
    broker = _ocs().broker
    assert broker._probe_unix(short_dir / "none.sock") is False


# ─── (k) pi.py: GitHub ブローカーの起動の流れ ──────────────────────────


def _broker_rules(tmp_path, monkeypatch, pi, **section):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"broker": section}), encoding="utf-8")
    monkeypatch.setattr(pi, "RULES", path)


def _flow(pi, monkeypatch, tmp_path):
    """``_launch`` を試す道具: agent 置き場を ``tmp_path`` へ、session と ``_launch_with`` を記録に差し替える。

    session に入る時点の agent 置き場の中身 (空のはず) も記録する。
    """
    home = _agent_home(pi, monkeypatch, tmp_path)
    flow = SimpleNamespace(home=home, sessions=[], exits=[], launches=[])
    monkeypatch.setattr(pi, "check_installed", lambda: None)

    @contextlib.contextmanager
    def session(*args, **kwargs):
        sock = kwargs["github_socket"]
        entries = sorted(p.name for p in sock.parent.iterdir()) if sock is not None else None
        flow.sessions.append({"args": args, "kwargs": kwargs, "entries": entries})
        url = "http://127.0.0.1:18081" if kwargs["copilot"] else None
        try:
            yield pi.broker.BrokerSession(url, Path("/nonexistent/run/pis-broker-x"), sock)
        finally:
            flow.exits.append(True)

    def launch_with(args, passthrough, value, state=None, *, agent, github_socket=None):
        flow.launches.append(
            {"value": value, "state": state, "agent": agent, "github_socket": github_socket}
        )
        return 0

    monkeypatch.setattr(pi.broker, "session", session)
    monkeypatch.setattr(pi, "_launch_with", launch_with)
    return flow


def test_github_auto_allocates_an_empty_agent_dir_before_the_broker_starts(monkeypatch, tmp_path):
    pi = _ocs().pi
    real = tmp_path / "real"
    real.mkdir()
    (real / "auth.json").write_text(json.dumps(_auth_for_flow()), encoding="utf-8")
    monkeypatch.setattr(pi, "REAL_AGENT", real)
    token_file = _token_file(tmp_path, PAT)
    _broker_rules(
        tmp_path, monkeypatch, pi, copilot="off", github="auto", github_token_file=str(token_file)
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    (entered,) = flow.sessions
    (launched,) = flow.launches
    agent = launched["agent"]
    assert entered["entries"] == []  # 起動の時点では空 (auth.json も、写しも無い)
    assert agent.parent == flow.home and agent.name.startswith("agent-")
    assert entered["kwargs"] == {
        "copilot": False,
        "github_token": PAT,
        "github_socket": agent / "gh.sock",
    }
    assert launched["github_socket"] == agent / "gh.sock"
    assert launched["value"] is None
    assert flow.exits == [True]
    assert not agent.exists()  # 終わったら消える


def _auth_for_flow() -> dict:
    return {"openai": {"type": "oauth", "refresh": "r", "expires": 1}}


def test_github_and_copilot_auto_share_one_session(monkeypatch, tmp_path):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, PAT)
    _broker_rules(
        tmp_path, monkeypatch, pi, copilot="auto", github="auto", github_token_file=str(token_file)
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    (entered,) = flow.sessions
    assert entered["kwargs"]["copilot"] is True and entered["kwargs"]["github_token"] == PAT
    (launched,) = flow.launches
    assert launched["value"] == "http://127.0.0.1:18081"
    assert launched["state"] == Path("/nonexistent/run/pis-broker-x")


def test_manual_copilot_url_with_github_starts_a_github_only_session(monkeypatch, tmp_path):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, PAT)
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        copilot="http://127.0.0.1:18080",
        github="auto",
        github_token_file=str(token_file),
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    assert flow.sessions[0]["kwargs"]["copilot"] is False
    assert flow.launches[0]["value"] == "http://127.0.0.1:18080"


def test_github_token_command_is_used_when_configured(monkeypatch, tmp_path):
    pi = _ocs().pi
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        github="auto",
        github_token_command=_python_prints(PAT),
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    assert flow.sessions[0]["kwargs"]["github_token"] == PAT


def test_missing_pat_degrades_to_no_github_broker_with_a_notice(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    missing = tmp_path / "nothing-here"
    _broker_rules(
        tmp_path, monkeypatch, pi, copilot="off", github="auto", github_token_file=str(missing)
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    assert flow.sessions == []  # Copilot も無効なので Envoy は立てない
    assert flow.launches[0]["github_socket"] is None
    err = capsys.readouterr().err
    assert "GitHub 認証なし" in err and str(missing) in err
    assert len([line for line in err.splitlines() if "GitHub 認証なし" in line]) == 1


def test_failing_pat_command_degrades_and_names_only_its_first_word(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    script = f"import sys; sys.stderr.write({PAT!r}); sys.exit(2)"
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        github="auto",
        github_token_command=[sys.executable, "-c", script],
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    assert flow.sessions == []
    err = capsys.readouterr().err
    assert f"PAT の出どころ: {sys.executable})" in err
    assert PAT not in err and "sys.exit" not in err


def test_missing_pat_keeps_copilot_running(monkeypatch, tmp_path):
    pi = _ocs().pi
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        copilot="auto",
        github="auto",
        github_token_file=str(tmp_path / "none"),
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    (entered,) = flow.sessions
    assert entered["kwargs"] == {"copilot": True, "github_token": None, "github_socket": None}


def test_wide_pat_file_permissions_refuse_to_start(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, PAT, mode=0o644)
    _broker_rules(tmp_path, monkeypatch, pi, github="auto", github_token_file=str(token_file))
    flow = _flow(pi, monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert flow.sessions == [] and flow.launches == []
    assert not list(flow.home.glob("agent-*"))  # 確保した agent 置き場も残さない
    err = capsys.readouterr().err
    assert "権限" in err and PAT not in err


def test_bad_pat_shape_refuses_to_start(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, "two words")
    _broker_rules(tmp_path, monkeypatch, pi, github="auto", github_token_file=str(token_file))
    flow = _flow(pi, monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert flow.sessions == [] and flow.launches == []
    assert "two words" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "section",
    [
        {"github": "yes"},
        {"github": True},
        {"github": "auto", "github_token_file": "~/t", "github_token_command": ["echo", "x"]},
        {"github": "auto", "github_token_file": 1},
        {"github": "auto", "github_token_file": ""},
        {"github": "auto", "github_token_command": "bw get"},
        {"github": "auto", "github_token_command": []},
        {"github": "auto", "github_token_command": ["bw", 1]},
    ],
)
def test_broken_github_settings_fail_closed(monkeypatch, tmp_path, section):
    pi = _ocs().pi
    _broker_rules(tmp_path, monkeypatch, pi, **section)
    flow = _flow(pi, monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert flow.sessions == [] and flow.launches == []
    assert not list(flow.home.glob("agent-*"))


def test_github_off_ignores_the_token_source(monkeypatch, tmp_path):
    pi = _ocs().pi
    marker = tmp_path / "ran"
    script = f"open({str(marker)!r}, 'w').close()"
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        github="off",
        github_token_command=[sys.executable, "-c", script],
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(), []) == 0
    assert flow.sessions == [] and flow.launches[0]["github_socket"] is None
    assert not marker.exists()


def test_launch_failure_after_the_broker_started_leaves_nothing(monkeypatch, tmp_path):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, PAT)
    _broker_rules(tmp_path, monkeypatch, pi, github="auto", github_token_file=str(token_file))
    flow = _flow(pi, monkeypatch, tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pi, "_launch_with", boom)
    with pytest.raises(RuntimeError, match="boom"):
        pi._launch(_args(), [])
    assert flow.exits == [True]  # Envoy (session) も止める
    assert not list(flow.home.glob("agent-*"))


def test_broker_failure_after_allocation_leaves_no_agent_dir(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    token_file = _token_file(tmp_path, PAT)
    _broker_rules(tmp_path, monkeypatch, pi, github="auto", github_token_file=str(token_file))
    flow = _flow(pi, monkeypatch, tmp_path)

    @contextlib.contextmanager
    def failing(*args, **kwargs):
        raise pi.broker.BrokerError("envoy が無い", "導入する")
        yield  # pragma: no cover

    monkeypatch.setattr(pi.broker, "session", failing)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert flow.launches == [] and not list(flow.home.glob("agent-*"))
    assert PAT not in capsys.readouterr().err


def test_no_broker_disables_github_too_and_never_reads_the_source(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    marker = tmp_path / "ran"
    script = f"open({str(marker)!r}, 'w').close()"
    _broker_rules(
        tmp_path,
        monkeypatch,
        pi,
        copilot="auto",
        github="auto",
        github_token_command=[sys.executable, "-c", script],
    )
    flow = _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(no_broker=True), []) == 0
    assert flow.sessions == [] and flow.launches[0]["github_socket"] is None
    assert not marker.exists()
    err = capsys.readouterr().err
    assert "ブローカー無し" in err and "GitHub" in err
    assert len([line for line in err.splitlines() if "ブローカー無し" in line]) == 1


def test_no_broker_notice_does_not_mention_github_when_it_was_off(monkeypatch, tmp_path, capsys):
    pi = _ocs().pi
    _broker_rules(tmp_path, monkeypatch, pi, copilot="auto", github="off")
    _flow(pi, monkeypatch, tmp_path)
    assert pi._launch(_args(no_broker=True), []) == 0
    assert "GitHub" not in capsys.readouterr().err
