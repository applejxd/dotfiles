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
import sys

cfg = sys.argv[sys.argv.index("--config-path") + 1]
text = open(cfg, encoding="utf-8").read()
port = int(re.search(r"port_value: (\\d+)", text).group(1))
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


http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
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
    path.write_text(script.format(python=sys.executable), encoding="utf-8")
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


def _render(broker, tmp_path, host="api.example.test", ca="/etc/ssl/ca.pem"):
    return broker.render_config(
        broker.TEMPLATE.read_text(encoding="utf-8"), 12345, host, tmp_path, ca
    )


def test_render_config_fills_every_placeholder(tmp_path):
    broker = _ocs().broker
    out = _render(broker, tmp_path)
    assert not re.search(r"@(PORT|HOST|SDS_DIR|CA_FILE)@", out)
    assert "port_value: 12345}" in out
    assert out.count('"api.example.test"') == 3  # host_rewrite_literal・接続先・SNI
    assert f'path: "{tmp_path}/copilot-sds.json"' in out
    assert f'watched_directory: {{path: "{tmp_path}"}}' in out
    assert '"@type"' in out  # 型の指定は置換の対象ではない


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


@pytest.mark.parametrize("bad", ['/tmp/a"b.pem', "/tmp/a\nb.pem"])
def test_render_config_rejects_paths_that_break_the_yaml_string(tmp_path, bad):
    broker = _ocs().broker
    with pytest.raises(broker.BrokerError):
        _render(broker, tmp_path, ca=bad)


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
    listener = data["static_resources"]["listeners"][0]
    assert listener["address"]["socket_address"] == {"address": "127.0.0.1", "port_value": 12345}
    context = data["static_resources"]["clusters"][0]["transport_socket"]["typed_config"]
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
        config = (state / "envoy-copilot.yaml").read_text(encoding="utf-8")
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


def test_auto_mode_enters_the_session_and_passes_the_url_on(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "Auto")

    def launch_with(args, passthrough, value, state=None):
        events.append(("launch", value))
        return 7

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    assert pi._launch(_args(), []) == 7
    assert [e[0] for e in events] == ["enter", "launch", "exit"]  # 起動の間ずっと有効
    assert events[0][1] == (pi.REAL_AGENT,)
    assert events[1] == ("launch", "http://127.0.0.1:18081")


def test_auto_mode_stops_the_broker_when_the_launch_raises(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "auto")

    def launch_with(args, passthrough, value, state=None):
        raise SystemExit(3)

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    assert events[-1] == ("exit",)


def test_auto_mode_turns_a_broker_error_into_die(monkeypatch, capsys, tmp_path):
    pi = _ocs().pi
    monkeypatch.setattr(pi, "check_installed", lambda: None)

    @contextlib.contextmanager
    def failing(*args, **kwargs):
        raise pi.broker.BrokerError("envoy が見つからない", "導入の案内")
        yield  # pragma: no cover

    monkeypatch.setattr(pi.broker, "session", failing)
    _rules(tmp_path, monkeypatch, pi, "auto")
    monkeypatch.setattr(pi, "_launch_with", lambda *a: pytest.fail("起動してはいけない"))
    with pytest.raises(SystemExit):
        pi._launch(_args(), [])
    err = capsys.readouterr().err
    assert "envoy が見つからない" in err and "導入の案内" in err
    assert "--no-broker" in err  # 一時的に外す手段を案内する


def test_manual_mode_does_not_start_a_broker(monkeypatch, tmp_path):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, "http://127.0.0.1:18080")
    seen = []
    monkeypatch.setattr(pi, "_launch_with", lambda args, p, value, s=None: seen.append(value) or 0)
    assert pi._launch(_args(), []) == 0
    assert events == [] and seen == ["http://127.0.0.1:18080"]


@pytest.mark.parametrize("copilot", ["off", None], ids=["off", "no-broker-section"])
def test_off_or_missing_setting_uses_no_broker(monkeypatch, tmp_path, copilot):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, copilot)
    seen = []
    monkeypatch.setattr(pi, "_launch_with", lambda args, p, value, s=None: seen.append(value) or 0)
    assert pi._launch(_args(), []) == 0
    assert events == [] and seen == [None]


@pytest.mark.parametrize("copilot", ["auto", "http://127.0.0.1:18080"])
def test_no_broker_flag_overrides_the_setting_and_warns(monkeypatch, tmp_path, capsys, copilot):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    _rules(tmp_path, monkeypatch, pi, copilot)
    seen = []
    monkeypatch.setattr(pi, "_launch_with", lambda args, p, value, s=None: seen.append(value) or 0)
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
    prepared = []
    monkeypatch.setattr(pi, "prepare_agent_dir", lambda **k: prepared.append(agent) or agent)
    return agent, prepared


def test_agent_dir_is_removed_when_a_later_step_raises(monkeypatch, tmp_path):
    pi = _ocs().pi
    agent, _ = _stub_launch(pi, monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pi, "sessions_dir", boom)
    with pytest.raises(RuntimeError, match="boom"):
        pi._launch_with(_args(), [], None)
    assert not agent.exists()


@pytest.mark.parametrize("where", ["inside-workspace", "workspace-inside-base"])
def test_state_dir_overlapping_the_workspace_is_refused(monkeypatch, tmp_path, capsys, where):
    pi = _ocs().pi
    _, prepared = _stub_launch(pi, monkeypatch, tmp_path)
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
        pi._launch_with(_args(), [], None, state)
    assert "重なる" in capsys.readouterr().err
    assert prepared == []  # agent 置き場を作る前に断っている


def test_state_dir_apart_from_the_workspace_passes_the_overlap_check(monkeypatch, tmp_path):
    pi = _ocs().pi
    agent, prepared = _stub_launch(pi, monkeypatch, tmp_path)
    state = tmp_path / "run" / "pis-broker-x"
    state.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(pi, "sessions_dir", lambda *a: (_ for _ in ()).throw(RuntimeError("next")))
    with pytest.raises(RuntimeError, match="next"):
        pi._launch_with(_args(), [], None, state)
    assert prepared == [agent]  # 重複の検査を越えて先へ進んだ


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
