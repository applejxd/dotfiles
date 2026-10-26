"""プロキシ必須の環境での中継 (``relay``) の試験。

- 判定: 許可リストの照合・``NO_PROXY``・プロキシの URL の読み方
- 中継: 許可した宛先だけが上流のプロキシへ届く。許可外・平文 HTTP は上流へ何も送らない
- 設定: 中継が要るときだけ Fence の設定が変わる

see docs/spec/guard/pi-guard.md#プロキシ必須の環境での通信
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
from base64 import b64encode
from pathlib import Path

import pytest
from agents_common import ROOT

SRC = ROOT / "home" / "dot_local" / "share" / "ocs" / "relay.py"


def _load():
    spec = importlib.util.spec_from_file_location("relay_under_test", SRC)
    module = importlib.util.module_from_spec(spec)
    # source state に __pycache__ を残さない (配備先と中身を揃える試験が見る)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


relay = _load()


# ─── 判定 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "port", "patterns", "expected"),
    [
        ("github.com", 443, ["github.com"], True),
        ("GitHub.com.", 443, ["github.com"], True),
        ("api.github.com", 443, ["github.com"], False),
        ("api.github.com", 443, ["*.github.com"], True),
        # ★ *.x は x 自身を含まない (Fence と同じ)
        ("github.com", 443, ["*.github.com"], False),
        ("evilgithub.com", 443, ["*.github.com"], False),
        ("example.com", 443, ["github.com", "*.githubcopilot.com"], False),
        ("example.com", 443, ["*"], True),
        ("github.com", 443, ["github.com:443"], True),
        ("github.com", 22, ["github.com:443"], False),
        ("github.com", 443, [], False),
    ],
)
def test_host_allowed(host, port, patterns, expected):
    assert relay.host_allowed(host, port, patterns) is expected


@pytest.mark.parametrize(
    ("host", "no_proxy", "expected"),
    [
        ("intra.corp", "intra.corp", True),
        ("a.intra.corp", ".intra.corp", True),
        ("a.intra.corp", "*.intra.corp", True),
        ("evilintra.corp", "intra.corp", False),
        ("10.1.2.3", "10.0.0.0/8", True),
        ("11.1.2.3", "10.0.0.0/8", False),
        ("github.com", "*", True),
        ("github.com", "", False),
        ("github.com", "localhost,127.0.0.1", False),
    ],
)
def test_bypass(host, no_proxy, expected):
    assert relay.bypass(host, no_proxy) is expected


def test_corporate_proxy_reads_the_first_variable_in_priority_order():
    env = {"http_proxy": "http://low:1", "HTTPS_PROXY": "http://high:2"}
    assert relay.corporate_proxy(env) == "http://high:2"


def test_corporate_proxy_adds_the_missing_scheme():
    assert relay.corporate_proxy({"HTTPS_PROXY": "proxy.corp:8080"}) == "http://proxy.corp:8080"


def test_corporate_proxy_is_none_without_variables():
    assert relay.corporate_proxy({}) is None


def test_corporate_proxy_rejects_unsupported_schemes_with_a_warning(capsys):
    assert relay.corporate_proxy({"HTTPS_PROXY": "https://proxy.corp:8080"}) is None
    assert "未対応" in capsys.readouterr().err


# ─── 中継 ───────────────────────────────────────────────────────────


class FakeProxy:
    """プロキシの代役。CONNECT を記録し、つないだ先でエコーする。"""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[str] = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            self.requests.append(data.decode("latin-1"))
            conn.sendall(f"HTTP/1.1 {self.status} X\r\n\r\n".encode())
            if self.status != 200:
                return
            while chunk := conn.recv(4096):
                conn.sendall(chunk)

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def upstream():
    proxy = FakeProxy()
    yield proxy
    proxy.close()


def _exchange(port: int, request: bytes, payload: bytes = b"") -> tuple[bytes, bytes]:
    """中継へ要求を送り、(応答の先頭部, トンネルで返った分) を得る。"""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        if payload and head.startswith(b"HTTP/1.1 200"):
            sock.sendall(payload)
            while len(rest) < len(payload):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                rest += chunk
        return head, rest


def _relay(upstream, allowed, no_proxy="", url=None):
    server = relay.Relay(allowed, url or f"http://127.0.0.1:{upstream.port}", no_proxy)
    server.start()
    return server


def test_allowed_host_reaches_the_corporate_proxy_and_data_flows(upstream):
    server = _relay(upstream, ["github.com"])
    try:
        head, echoed = _exchange(
            server.port, b"CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n", b"ping"
        )
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 200")
    assert echoed == b"ping"
    assert upstream.requests[0].startswith("CONNECT github.com:443 HTTP/1.1")


def test_denied_host_gets_403_and_nothing_reaches_the_corporate_proxy(upstream):
    server = _relay(upstream, ["github.com"])
    try:
        head, _ = _exchange(server.port, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 403")
    assert upstream.requests == []
    assert server.denied == ["example.com:443"]


def test_plain_http_is_refused_even_for_an_allowed_host(upstream):
    """★平文は 1 本の接続で別の宛先へ続けて送れるので、照合をすり抜ける。"""
    server = _relay(upstream, ["github.com"])
    try:
        head, _ = _exchange(
            server.port, b"GET http://github.com/ HTTP/1.1\r\nHost: github.com\r\n\r\n"
        )
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 403")
    assert upstream.requests == []


def test_credentials_in_the_proxy_url_become_a_basic_header(upstream):
    server = _relay(upstream, ["github.com"], url=f"http://us%40er:p%3Aw@127.0.0.1:{upstream.port}")
    try:
        _exchange(server.port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n", b"x")
    finally:
        server.stop()
    expected = b64encode(b"us@er:p:w").decode()
    assert f"Proxy-Authorization: Basic {expected}" in upstream.requests[0]


def test_no_header_without_credentials(upstream):
    server = _relay(upstream, ["github.com"])
    try:
        _exchange(server.port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n", b"x")
    finally:
        server.stop()
    assert "Proxy-Authorization" not in upstream.requests[0]


def test_upstream_refusal_becomes_502():
    proxy = FakeProxy(status=407)
    server = _relay(proxy, ["github.com"])
    try:
        head, _ = _exchange(server.port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
        proxy.close()
    assert head.startswith(b"HTTP/1.1 502")


def test_unreachable_corporate_proxy_becomes_502():
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()
    server = relay.Relay(["github.com"], f"http://127.0.0.1:{port}")
    server.start()
    try:
        head, _ = _exchange(server.port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 502")


def test_no_proxy_hosts_are_dialed_directly(upstream):
    echo = socket.socket()
    echo.bind(("127.0.0.1", 0))
    echo.listen(1)
    port = echo.getsockname()[1]

    def serve():
        conn, _ = echo.accept()
        with conn:
            while chunk := conn.recv(4096):
                conn.sendall(chunk)

    threading.Thread(target=serve, daemon=True).start()
    server = _relay(upstream, ["127.0.0.1"], no_proxy="127.0.0.1")
    try:
        head, echoed = _exchange(
            server.port, f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode(), b"direct"
        )
    finally:
        server.stop()
        echo.close()
    assert head.startswith(b"HTTP/1.1 200")
    assert echoed == b"direct"
    assert upstream.requests == []


def test_garbage_request_does_not_crash_the_relay(upstream):
    server = _relay(upstream, ["github.com"])
    try:
        head, _ = _exchange(server.port, b"CONNECT\r\n\r\n")
        assert head.startswith((b"HTTP/1.1 400", b"HTTP/1.1 403"))
        # その後も普通に使える
        head, _ = _exchange(server.port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n", b"x")
        assert head.startswith(b"HTTP/1.1 200")
    finally:
        server.stop()


# ─── 設定 ───────────────────────────────────────────────────────────


def _config(allowed):
    return {
        "network": {"allowedDomains": allowed, "deniedDomains": ["bad.example"]},
        "filesystem": {"allowWrite": ["/w"]},
    }


def test_session_without_a_corporate_proxy_changes_nothing():
    config = _config(["github.com"])
    with relay.session(config, env={}) as got:
        assert got is config


@pytest.mark.parametrize("allowed", [[], ["*"], ["github.com", "*"]])
def test_session_leaves_empty_and_wildcard_allow_lists_alone(allowed):
    config = _config(allowed)
    with relay.session(config, env={"HTTPS_PROXY": "http://proxy.corp:8080"}) as got:
        assert got is config


def test_session_moves_the_allow_list_to_the_relay():
    config = _config(["github.com", "*.githubcopilot.com"])
    with relay.session(config, env={"HTTPS_PROXY": "http://proxy.corp:8080"}) as got:
        network = got["network"]
        assert network["allowedDomains"] == []
        assert network["defaultAction"] == "proxy"
        assert network["upstreamProxy"].startswith("http://127.0.0.1:")
        # ★拒否リストは Fence に残す。ほかの項目は触らない
        assert network["deniedDomains"] == ["bad.example"]
        assert got["filesystem"] == config["filesystem"]
        port = int(network["upstreamProxy"].rsplit(":", 1)[1])
        # 元の設定 (境界チェックが許可済みの検査先を引く) は変えない
        assert config["network"]["allowedDomains"] == ["github.com", "*.githubcopilot.com"]
        assert "defaultAction" not in config["network"]
    with pytest.raises(OSError):  # 終わったら待ち受けを止める
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_session_relay_enforces_the_allow_list_end_to_end(upstream):
    env = {"HTTPS_PROXY": f"http://127.0.0.1:{upstream.port}"}
    with relay.session(_config(["github.com"]), env=env) as got:
        port = int(got["network"]["upstreamProxy"].rsplit(":", 1)[1])
        ok, _ = _exchange(port, b"CONNECT github.com:443 HTTP/1.1\r\n\r\n", b"x")
        no, _ = _exchange(port, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    assert ok.startswith(b"HTTP/1.1 200")
    assert no.startswith(b"HTTP/1.1 403")


def test_module_has_no_relative_imports():
    """★単独の部品として読めること (入口が絶対パスで読む信頼の鎖に載るため、依存を増やさない)。"""
    assert "from ." not in Path(SRC).read_text(encoding="utf-8")


# ─── 拒否リスト型 (直接接続) ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("address", "allow_loopback", "blocked"),
    [
        ("93.184.216.34", False, False),  # 公開
        ("2606:2800:220:1:248:1893:25c8:1946", False, False),  # 公開 (IPv6)
        ("127.0.0.1", False, True),
        ("127.0.0.1", True, False),  # ループバックだけ設定で開けられる
        ("::1", False, True),
        ("::1", True, False),
        ("::ffff:127.0.0.1", False, True),  # IPv4-mapped は IPv4 として見る
        ("::ffff:10.0.0.1", True, True),  # ループバックを開けても私設は開かない
        ("10.1.2.3", False, True),
        ("172.16.0.1", False, True),
        ("192.168.1.1", False, True),
        ("100.64.0.1", False, True),  # 共有アドレス空間
        ("169.254.169.254", False, True),  # クラウドのメタデータ
        ("169.254.169.254", True, True),
        ("fe80::1", False, True),
        ("fd00::1", False, True),  # ULA
        ("0.0.0.0", False, True),
        ("224.0.0.1", False, True),
        ("not-an-ip", False, True),  # 読めないものは拒否 (fail closed)
    ],
)
def test_blocked_address(address, allow_loopback, blocked):
    assert (relay.blocked_address(address, allow_loopback) is not None) is blocked


def _fake_resolver(monkeypatch, answers):
    """getaddrinfo を差し替える。answers は [(family, address), ...]。"""

    def fake(host, port, **_kw):
        return [(family, socket.SOCK_STREAM, 6, "", (addr, port)) for family, addr in answers]

    monkeypatch.setattr(relay.socket, "getaddrinfo", fake)


def test_resolve_public_refuses_when_any_answer_is_not_public(monkeypatch):
    """★公開と内部が混ざる応答 (DNS の細工) は、全体を拒否する。"""
    _fake_resolver(monkeypatch, [(socket.AF_INET, "93.184.216.34"), (socket.AF_INET, "10.0.0.5")])
    with pytest.raises(relay.Blocked):
        relay.resolve_public("evil.example", 443)


def test_resolve_public_puts_ipv4_first(monkeypatch):
    _fake_resolver(
        monkeypatch,
        [
            (socket.AF_INET6, "2606:2800:220:1:248:1893:25c8:1946"),
            (socket.AF_INET, "93.184.216.34"),
        ],
    )
    families = [info[0] for info in relay.resolve_public("example.test", 443)]
    assert families == [socket.AF_INET, socket.AF_INET6]


def _echo_server():
    echo = socket.socket()
    echo.bind(("127.0.0.1", 0))
    echo.listen(2)

    def serve():
        while True:
            try:
                conn, _ = echo.accept()
            except OSError:
                return
            with conn:
                while chunk := conn.recv(4096):
                    conn.sendall(chunk)

    threading.Thread(target=serve, daemon=True).start()
    return echo, echo.getsockname()[1]


def _deny_relay(deny=(), allow_loopback=False):
    server = relay.Relay([], "", deny=list(deny), allow_loopback=allow_loopback)
    server.start()
    return server


def test_deny_mode_dials_a_loopback_target_only_when_allowed():
    echo, port = _echo_server()
    request = f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n\r\n".encode()
    try:
        closed = _deny_relay()
        try:
            head, _ = _exchange(closed.port, request)
        finally:
            closed.stop()
        assert head.startswith(b"HTTP/1.1 403")
        assert closed.denied == [f"127.0.0.1:{port}"]

        opened = _deny_relay(allow_loopback=True)
        try:
            head, echoed = _exchange(opened.port, request, b"hello")
        finally:
            opened.stop()
        assert head.startswith(b"HTTP/1.1 200")
        assert echoed == b"hello"
    finally:
        echo.close()


def test_deny_mode_refuses_the_metadata_address_even_with_loopback_allowed():
    server = _deny_relay(allow_loopback=True)
    try:
        head, _ = _exchange(server.port, b"CONNECT 169.254.169.254:80 HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 403")


def test_deny_list_match_is_refused_before_any_name_resolution(monkeypatch):
    calls = []
    real = socket.getaddrinfo

    def spy(host, *a, **k):
        if host == "127.0.0.1":  # 試験のクライアント自身の接続
            return real(host, *a, **k)
        calls.append(host)
        return []

    monkeypatch.setattr(relay.socket, "getaddrinfo", spy)
    server = _deny_relay(deny=["pastebin.com", "*.files.example"])
    try:
        for target in ("pastebin.com:443", "a.files.example:443"):
            head, _ = _exchange(server.port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
            assert head.startswith(b"HTTP/1.1 403")
    finally:
        server.stop()
    assert calls == []


def test_deny_mode_ignores_no_proxy_and_refuses_plain_http():
    """★NO_PROXY は安全の判断に使わない。平文 HTTP は拒否のまま。"""
    server = _deny_relay()
    try:
        head, _ = _exchange(server.port, b"GET http://example.com/ HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 403")


def test_deny_mode_unresolvable_name_becomes_502(monkeypatch):
    real = socket.getaddrinfo

    def fail(host, *a, **k):
        if host == "127.0.0.1":  # 試験のクライアント自身の接続
            return real(host, *a, **k)
        raise socket.gaierror("no such host")

    monkeypatch.setattr(relay.socket, "getaddrinfo", fail)
    server = _deny_relay()
    try:
        head, _ = _exchange(server.port, b"CONNECT nowhere.invalid:443 HTTP/1.1\r\n\r\n")
    finally:
        server.stop()
    assert head.startswith(b"HTTP/1.1 502")


def test_fence_config_deny_empties_the_allow_list_and_keeps_existing_denies():
    config = {
        "network": {"allowedDomains": ["github.com"], "deniedDomains": ["a.example"]},
        "filesystem": {"allowRead": ["/x"]},
    }
    out = relay.fence_config_deny(config, 4321, ["b.example", "a.example"])
    assert out["network"]["allowedDomains"] == []
    assert out["network"]["deniedDomains"] == ["a.example", "b.example"]
    assert out["network"]["defaultAction"] == "proxy"
    assert out["network"]["upstreamProxy"] == "http://127.0.0.1:4321"
    assert out["filesystem"] == config["filesystem"]
    assert config["network"]["allowedDomains"] == ["github.com"]  # 元は変えない


def test_session_denylist_without_a_host_proxy_starts_a_direct_relay():
    config = {"network": {"allowedDomains": ["github.com"]}}
    network = {"mode": "denylist", "deny": ["x.example"], "allow_loopback": False}
    with relay.session(config, {}, network) as out:
        assert out is not config
        assert out["network"]["allowedDomains"] == []
        assert out["network"]["deniedDomains"] == ["x.example"]
        assert out["network"]["defaultAction"] == "proxy"


def test_session_denylist_falls_back_to_the_allowlist_relay_when_the_host_needs_a_proxy():
    """★上流のプロキシが名前を解決するので、中継はアドレスを検査できない。従来の許可リスト型のまま。"""
    config = {"network": {"allowedDomains": ["github.com"]}}
    network = {"mode": "denylist", "deny": ["x.example"]}
    with relay.session(config, {"HTTPS_PROXY": "http://proxy.corp:8080"}, network) as out:
        assert out["network"]["allowedDomains"] == []  # 許可リストは中継へ移る (従来どおり)
        assert out["network"]["upstreamProxy"].startswith("http://127.0.0.1:")
        assert "deniedDomains" not in out["network"]  # 拒否リスト型にはならない


def test_session_without_network_setting_is_unchanged_for_the_allowlist():
    config = {"network": {"allowedDomains": ["github.com"]}}
    with relay.session(config, {}, None) as out:
        assert out is config
