"""社内プロキシ越しに、許可リストを保ったまま Fence の通信を出す小さな中継。

Fence は ``allowedDomains`` に当たる通信を**直接**つなぐ。外へ出るのに社内プロキシが要る
環境では、許可済みのドメインにも届かない。上流プロキシ (``upstreamProxy``) は、許可リストにも
拒否リストにも当たらない通信にしか使われない。
そこで許可リストを Fence から**この中継へ移し**、Fence には「当たらない通信は全部ここへ」と
渡す (``defaultAction: "proxy"``)。中継は許可リストと照合し、許可した宛先だけを社内プロキシへ
``CONNECT`` する。許可外は 403 で返し、社内プロキシへは何も送らない。

- 対象はホストに社内プロキシの環境変数 (``HTTPS_PROXY`` など) がある機械だけ。無ければ何もしない
- 通すのは ``CONNECT`` (HTTPS) だけ。平文の HTTP は、1 本の接続で別の宛先へ続けて送れて
  照合をすり抜けるので 403 にする
- 待ち受けは ``127.0.0.1`` の空きポート。接続できるのは同じ機械のプロセスで、
  通せるのは許可リストの宛先だけ

see docs/spec/pi-guard.md#社内プロキシ越しの通信
"""

from __future__ import annotations

import contextlib
import copy
import ipaddress
import os
import select
import socket
import socketserver
import sys
import threading
from base64 import b64encode
from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

PROXY_ENV = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
NO_PROXY_ENV = ("NO_PROXY", "no_proxy")
HEAD_LIMIT = 16 * 1024
HEAD_TIMEOUT = 10.0
DIAL_TIMEOUT = 10.0
IDLE_TIMEOUT = 900.0


def _first(env: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def corporate_proxy(env: dict | None = None) -> str | None:
    """ホストの社内プロキシの URL。無い・使えない形なら ``None``。

    対応は ``http://[user:pass@]host:port`` だけ。``https://`` や SOCKS は Fence 側も未対応なので
    使えない形として警告し、従来どおり (中継なし) にする。
    """
    value = _first(os.environ if env is None else env, PROXY_ENV)
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() != "http" or not parts.hostname:
        print(
            f"警告: 社内プロキシの形 ({parts.scheme}://) に未対応なので、通信の中継は使わない"
            " (http://host:port だけ対応)",
            file=sys.stderr,
        )
        return None
    return value


def _split_pattern(pattern: str) -> tuple[str, int | None]:
    """``host`` または ``host:port`` を分ける。"""
    host, sep, port = pattern.rpartition(":")
    if sep and port.isdigit() and ":" not in host:
        return host, int(port)
    return pattern, None


def host_allowed(host: str, port: int, patterns: list[str]) -> bool:
    """許可リストに当たるか。``*.x`` は ``x`` 自身を含まない (Fence と同じ)。"""
    host = host.lower().rstrip(".")
    for raw in patterns:
        name, want_port = _split_pattern(raw.lower().rstrip("."))
        if want_port is not None and want_port != port:
            continue
        if name == "*":
            return True
        if name.startswith("*."):
            if host.endswith(name[1:]) and host != name[2:]:
                return True
        elif host == name:
            return True
    return False


def bypass(host: str, no_proxy: str) -> bool:
    """``NO_PROXY`` に当たる宛先は、社内プロキシを通さず直接つなぐ。"""
    host = host.lower().rstrip(".")
    for raw in no_proxy.split(","):
        entry = raw.strip().lower()
        if not entry:
            continue
        if entry == "*":
            return True
        with contextlib.suppress(ValueError):
            if ipaddress.ip_address(host) in ipaddress.ip_network(entry, strict=False):
                return True
        entry = entry.lstrip("*").lstrip(".")
        if host == entry or host.endswith("." + entry):
            return True
    return False


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    """空行までを読む。返すのは (先頭部, その後ろに続いた分)。"""
    sock.settimeout(HEAD_TIMEOUT)
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) > HEAD_LIMIT:
            raise ValueError("ヘッダが長すぎる")
        chunk = sock.recv(4096)
        if not chunk:
            raise ValueError("途中で閉じられた")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """2 つのソケットの間を、両方が閉じるまで流す。"""
    a.settimeout(None)
    b.settimeout(None)
    watch = [a, b]
    while watch:
        ready, _, _ = select.select(watch, [], [], IDLE_TIMEOUT)
        if not ready:
            return
        for src in ready:
            dst = b if src is a else a
            try:
                data = src.recv(65536)
            except OSError:
                data = b""
            if not data:
                # この向きは終わった: 相手へ終わりを伝え、逆向きが終わるまで流し続ける
                with contextlib.suppress(OSError):
                    dst.shutdown(socket.SHUT_WR)
                watch.remove(src)
                continue
            try:
                dst.sendall(data)
            except OSError:
                return


class _Handler(socketserver.BaseRequestHandler):
    server: _Server

    def handle(self) -> None:
        client = self.request
        try:
            head, rest = _read_head(client)
            line = head.split(b"\r\n", 1)[0].decode("latin-1")
            method, _, target = line.partition(" ")
            target = target.rsplit(" ", 1)[0]
            if method.upper() != "CONNECT":
                self._reply(client, 403, "平文の HTTP は中継しない (HTTPS だけ)")
                self.server.denied.append(f"{method} (HTTP)")
                return
            host, _, port_text = target.rpartition(":")
            host = host.strip("[]")
            if not host or not port_text.isdigit():
                self._reply(client, 400, "宛先の形が不正")
                return
            port = int(port_text)
            if not host_allowed(host, port, self.server.allowed):
                self.server.denied.append(f"{host}:{port}")
                self._reply(client, 403, "許可リストに無い宛先")
                return
            upstream, leftover = self._dial(host, port)
            if upstream is None:
                self._reply(client, 502, "上流へつなげない")
                return
            with upstream:
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if leftover:
                    client.sendall(leftover)
                if rest:
                    upstream.sendall(rest)
                _pipe(client, upstream)
        except (OSError, ValueError):
            pass

    @staticmethod
    def _reply(client: socket.socket, status: int, text: str) -> None:
        body = text.encode("utf-8")
        reason = {400: "Bad Request", 403: "Forbidden", 502: "Bad Gateway"}.get(status, "Error")
        head = (
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode("latin-1")
        with contextlib.suppress(OSError):
            client.sendall(head + body)

    def _dial(self, host: str, port: int) -> tuple[socket.socket | None, bytes]:
        """宛先へのトンネルを張る。``NO_PROXY`` なら直接、でなければ社内プロキシ経由。"""
        server = self.server
        try:
            if bypass(host, server.no_proxy):
                return socket.create_connection((host, port), timeout=DIAL_TIMEOUT), b""
            sock = socket.create_connection(server.upstream, timeout=DIAL_TIMEOUT)
        except OSError:
            return None, b""
        try:
            request = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if server.auth:
                request += f"Proxy-Authorization: Basic {server.auth}\r\n"
            sock.sendall((request + "\r\n").encode("latin-1"))
            head, rest = _read_head(sock)
            status = head.split(b"\r\n", 1)[0].split(b" ")
            if len(status) < 2 or status[1] != b"200":
                sock.close()
                return None, b""
            return sock, rest
        except (OSError, ValueError):
            sock.close()
            return None, b""


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, allowed: list[str], proxy_url: str, no_proxy: str) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        parts = urlsplit(proxy_url)
        self.allowed = list(allowed)
        self.no_proxy = no_proxy
        self.upstream = (parts.hostname or "", parts.port or 80)
        # 認証情報は URL からここへ取り出し、ログにも設定にも出さない
        self.auth = ""
        if parts.username:
            raw = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
            self.auth = b64encode(raw.encode()).decode()
        self.denied: list[str] = []


class Relay:
    """許可リストで絞って社内プロキシへ中継する。``start`` で待ち受けを始める。"""

    def __init__(self, allowed: list[str], proxy_url: str, no_proxy: str = "") -> None:
        self._server = _Server(allowed, proxy_url, no_proxy)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def denied(self) -> list[str]:
        return self._server.denied

    def start(self) -> int:
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def fence_config(config_: dict, port: int) -> dict:
    """許可リストを中継へ移した Fence の設定。拒否リストは Fence に残す (先に効く)。"""
    out = copy.deepcopy(config_)
    out["network"] = {
        **out.get("network", {}),
        "allowedDomains": [],
        "defaultAction": "proxy",
        "upstreamProxy": f"http://127.0.0.1:{port}",
    }
    return out


@contextlib.contextmanager
def session(config_: dict, env: dict | None = None) -> Iterator[dict]:
    """必要なら中継を起動し、Fence へ渡す設定を返す。要らなければ設定をそのまま返す。

    要るのは、社内プロキシの環境変数があり、許可リストがあり、``*`` を含まないとき。
    ``*`` は Fence が直接の通信を許す緩い形なので、許可リストの照合を中継へ移す意味が無い。
    """
    source = os.environ if env is None else env
    allowed = config_.get("network", {}).get("allowedDomains") or []
    url = corporate_proxy(source)
    if not url or not allowed or "*" in allowed:
        yield config_
        return
    relay = Relay(allowed, url, _first(source, NO_PROXY_ENV))
    port = relay.start()
    try:
        yield fence_config(config_, port)
    finally:
        relay.stop()
