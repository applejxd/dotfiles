"""``pis`` の Copilot ブローカー自動起動 (``PIS_COPILOT_BROKER=auto``) の試験。

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
    finally:
        sys.dont_write_bytecode = saved
    return SimpleNamespace(pi=sys.modules["ocs_lib.pi"], broker=sys.modules["ocs_lib.broker"])


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
    assert "PIS_COPILOT_BROKER" in capsys.readouterr().err


# ─── (b) 設定の置換 ─────────────────────────────────────────────────


def test_render_config_fills_every_placeholder(tmp_path):
    broker = _ocs().broker
    out = broker.render_config(
        broker.TEMPLATE.read_text(encoding="utf-8"), 12345, "api.example.test", tmp_path
    )
    assert not re.search(r"@(PORT|HOST|SDS_DIR)@", out)
    assert "port_value: 12345}" in out
    assert out.count('"api.example.test"') == 3  # host_rewrite_literal・接続先・SNI
    assert f'path: "{tmp_path}/copilot-sds.json"' in out
    assert f'watched_directory: {{path: "{tmp_path}"}}' in out
    assert '"@type"' in out  # 型の指定は置換の対象ではない


def test_rendered_config_is_valid_yaml(tmp_path):
    yaml = pytest.importorskip("yaml")
    broker = _ocs().broker
    out = broker.render_config(
        broker.TEMPLATE.read_text(encoding="utf-8"), 12345, "api.example.test", tmp_path
    )
    data = yaml.safe_load(out)
    listener = data["static_resources"]["listeners"][0]
    assert listener["address"]["socket_address"] == {"address": "127.0.0.1", "port_value": 12345}


def test_upstream_host_follows_proxy_ep_and_rejects_odd_values():
    broker = _ocs().broker
    assert broker.upstream_host(TOKEN1) == "api.individual.githubcopilot.com"
    assert broker.upstream_host("a=b;proxy-ep=proxy.business.githubcopilot.com") == (
        "api.business.githubcopilot.com"
    )
    assert broker.upstream_host("no endpoint") == broker.DEFAULT_HOST
    assert broker.upstream_host("proxy-ep=proxy.x.com\nevil: 1") == broker.DEFAULT_HOST


# ─── (c) session のライフサイクル ───────────────────────────────────


def test_session_starts_envoy_and_cleans_up(host, monkeypatch, capsys):
    broker = _ocs().broker
    calls = _fake_exchange(monkeypatch, broker, [(TOKEN1, _far())])
    with broker.session(host.agent, home=host.home) as url:
        match = re.fullmatch(r"http://127\.0\.0\.1:(\d+)", url)
        assert match
        (state,) = host.runtime.glob("pis-broker-*")
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
        assert first != second
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
            yield url
        finally:
            events.append(("exit",))

    return session


def test_auto_mode_enters_the_session_and_passes_the_url_on(monkeypatch):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    monkeypatch.setenv(pi.BROKER_ENV, "Auto")

    def launch_with(args, passthrough, value):
        events.append(("launch", value))
        return 7

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    assert pi._launch(SimpleNamespace(), []) == 7
    assert [e[0] for e in events] == ["enter", "launch", "exit"]  # 起動の間ずっと有効
    assert events[0][1] == (pi.REAL_AGENT,)
    assert events[1] == ("launch", "http://127.0.0.1:18081")


def test_auto_mode_stops_the_broker_when_the_launch_raises(monkeypatch):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    monkeypatch.setenv(pi.BROKER_ENV, "auto")

    def launch_with(args, passthrough, value):
        raise SystemExit(3)

    monkeypatch.setattr(pi, "_launch_with", launch_with)
    with pytest.raises(SystemExit):
        pi._launch(SimpleNamespace(), [])
    assert events[-1] == ("exit",)


def test_auto_mode_turns_a_broker_error_into_die(monkeypatch, capsys):
    pi = _ocs().pi
    monkeypatch.setattr(pi, "check_installed", lambda: None)

    @contextlib.contextmanager
    def failing(*args, **kwargs):
        raise pi.broker.BrokerError("envoy が見つからない", "導入の案内")
        yield  # pragma: no cover

    monkeypatch.setattr(pi.broker, "session", failing)
    monkeypatch.setenv(pi.BROKER_ENV, "auto")
    monkeypatch.setattr(pi, "_launch_with", lambda *a: pytest.fail("起動してはいけない"))
    with pytest.raises(SystemExit):
        pi._launch(SimpleNamespace(), [])
    err = capsys.readouterr().err
    assert "envoy が見つからない" in err and "導入の案内" in err


def test_manual_mode_does_not_start_a_broker(monkeypatch):
    pi = _ocs().pi
    events: list = []
    monkeypatch.setattr(pi, "check_installed", lambda: None)
    monkeypatch.setattr(pi.broker, "session", _recording_session(pi, events))
    monkeypatch.setenv(pi.BROKER_ENV, "http://127.0.0.1:18080")
    seen = []
    monkeypatch.setattr(pi, "_launch_with", lambda args, p, value: seen.append(value) or 0)
    assert pi._launch(SimpleNamespace(), []) == 0
    assert events == [] and seen == ["http://127.0.0.1:18080"]
