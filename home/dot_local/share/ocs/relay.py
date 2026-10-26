"""認証つき HTTP プロキシ越しに、許可リストを保ったまま Fence の通信を出す小さな中継。

Fence は ``allowedDomains`` に当たる通信を**直接**つなぐ。外へ出るのにプロキシが要る
環境では、許可済みのドメインにも届かない。上流プロキシ (``upstreamProxy``) は、許可リストにも
拒否リストにも当たらない通信にしか使われない。
そこで許可リストを Fence から**この中継へ移し**、Fence には「当たらない通信は全部ここへ」と
渡す (``defaultAction: "proxy"``)。中継は許可リストと照合し、許可した宛先だけを上流のプロキシへ
``CONNECT`` する。許可外は 403 で返し、上流のプロキシへは何も送らない。

- 対象はホストにプロキシの環境変数 (``HTTPS_PROXY`` など) がある機械だけ。無ければ何もしない
- 通すのは ``CONNECT`` (HTTPS) だけ。平文の HTTP は、1 本の接続で別の宛先へ続けて送れて
  照合をすり抜けるので 403 にする
- 待ち受けは ``127.0.0.1`` の空きポート。接続できるのは同じ機械のプロセスで、
  通せるのは許可リストの宛先だけ

拒否リスト型 (``Relay(deny=[...])``。上流のプロキシが無い機械向け): 拒否に当たらない宛先は
**中継が直接つなぐ**。Fence 側は ``allowedDomains: []`` + ``deniedDomains`` + ``defaultAction: "proxy"``
(``fence_config_deny``)。ネットワーク名前空間の隔離は保たれ、プロキシを使わない通信は届かない。
中継が穴にならないよう、**名前解決の結果が 1 つでも公開アドレスでなければ拒否**し、検査済みの
アドレスへつなぐ (ループバックだけ ``allow_loopback`` で開けられる)。
``NO_PROXY`` は安全の判断に使わない。

see docs/spec/guard/pi-guard.md#プロキシ必須の環境での通信
see docs/change/0037-pis-usability-and-telemetry.md (候補 E1')
"""

from __future__ import annotations

import contextlib
import copy
import ipaddress
import os
import re
import select
import socket
import socketserver
import sys
import threading
import time
from base64 import b64encode
from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

PROXY_ENV = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
NO_PROXY_ENV = ("NO_PROXY", "no_proxy")
HEAD_LIMIT = 16 * 1024
HEAD_TIMEOUT = 10.0
DIAL_TIMEOUT = 10.0
IDLE_TIMEOUT = 900.0
# 拒否リスト型の直接接続。IPv6 が届かない環境で 1 アドレスごとに長く待たない (IPv4 を先に試す)
CANDIDATE_TIMEOUT = 4.0
DIRECT_TIMEOUT = 15.0


def _first(env: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def corporate_proxy(env: dict | None = None) -> str | None:
    """ホストのプロキシの URL。無い・使えない形なら ``None``。

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
            f"警告: プロキシの形 ({parts.scheme}://) に未対応なので、通信の中継は使わない"
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
    """``NO_PROXY`` に当たる宛先は、プロキシを通さず直接つなぐ。"""
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


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class Blocked(Exception):
    """宛先のアドレスが公開でない。中継は 403 を返す。"""


# イントラネットを読む環境向けに ``allow_private`` で開けられる範囲。共有アドレス空間 (100.64/10) や予約済みは入れない
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def blocked_address(
    text: str, allow_loopback: bool = False, allow_private: bool = False
) -> str | None:
    """中継がつなぐべきでないアドレスなら理由、つなてよければ ``None``。

    通すのはグローバルなアドレスだけ (``is_global``)。IPv4-mapped の IPv6 は IPv4 として見る。
    ループバックだけ ``allow_loopback`` で、RFC1918 と ULA だけ ``allow_private`` で通せる。
    リンクローカル (メタデータを含む)・未指定・マルチキャスト・共有アドレス空間は常に拒否。
    読めない・迷うものは拒否 (fail closed)。
    """
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return "アドレスとして読めない"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return None if allow_loopback else "ループバック"
    if ip.is_unspecified:
        return "未指定アドレス"
    if ip.is_link_local:
        return "リンクローカル (クラウドのメタデータを含む)"
    if ip.is_multicast:
        return "マルチキャスト"
    if allow_private and any(ip.version == n.version and ip in n for n in _PRIVATE_NETS):
        return None
    if not ip.is_global:
        return "非公開・予約済みのアドレス (私設・ULA・共有アドレス空間など)"
    return None


_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
_NAME_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")


def parse_authority(target: str) -> tuple[str, int]:
    """``CONNECT`` の authority-form (``host:port`` / ``[v6]:port``) を厳密に読む。不正は ``ValueError``。

    ホストは小文字・末尾のドットなしに正規化し、中継が判定した値をそのまま上流へ渡す。
    数字だけ・16 進・省略形の IPv4 (``2852039166``、``0x7f.1``) は、上流が別のアドレスと解釈しうるので拒否する
    (最後のラベルは英字で始める。IPv4 リテラルは 4 つの 10 進数のときだけ)。
    """
    if not target or any(ord(c) < 0x21 or ord(c) > 0x7E for c in target):
        raise ValueError("authority の形が不正")
    if target.startswith("["):
        end = target.find("]")
        if end < 0 or target[end + 1 : end + 2] != ":":
            raise ValueError("IPv6 リテラルの括弧が不正")
        host, port_text = target[1:end], target[end + 2 :]
        if "%" in host:
            raise ValueError("スコープ ID は拒否")
        host = str(ipaddress.IPv6Address(host))  # 不正なら ValueError
    else:
        host, sep, port_text = target.rpartition(":")
        if not sep or ":" in host:
            raise ValueError("host:port の形ではない")
        host = host.lower().rstrip(".")
        if not _NAME_RE.fullmatch(host):
            raise ValueError("ホスト名が不正")
        if re.fullmatch(r"[0-9.]+", host):
            host = str(ipaddress.IPv4Address(host))  # 4 つの 10 進数以外は ValueError
        elif not host.rsplit(".", 1)[-1][:1].isalpha():
            raise ValueError("最後のラベルが英字で始まらない")
    if not port_text.isascii() or not port_text.isdigit() or len(port_text) > 5:
        raise ValueError("ポートが不正")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise ValueError("ポートが範囲外")
    return host, port


def resolve_public(
    host: str, port: int, allow_loopback: bool = False, allow_private: bool = False
) -> list[tuple]:
    """名前解決し、結果の**どれか 1 つでも**公開でないと ``Blocked``。IPv4 を先に並べて返す。

    解決結果の一部だけを見て残りを通すと、DNS の細工 (公開と内部の混在) で穴になる。
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise OSError("名前を解決できない")
    for info in infos:
        reason = blocked_address(info[4][0], allow_loopback, allow_private)
        if reason:
            raise Blocked(f"{info[4][0]} は{reason}")
    return sorted(infos, key=lambda i: 0 if i[0] == socket.AF_INET else 1)


def dial_public(
    host: str, port: int, allow_loopback: bool = False, allow_private: bool = False
) -> socket.socket:
    """公開アドレスだけを検査し、**検査したアドレスそのもの**へつなぐ (再解決しない)。"""
    deadline = time.monotonic() + DIRECT_TIMEOUT
    last: OSError = OSError("つなげない")
    for family, kind, proto, _, sockaddr in resolve_public(
        host, port, allow_loopback, allow_private
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock = socket.socket(family, kind, proto)
        sock.settimeout(min(CANDIDATE_TIMEOUT, remaining))
        try:
            sock.connect(sockaddr)
        except OSError as exc:
            last = exc
            sock.close()
            continue
        return sock
    raise last


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
            try:
                host, port = parse_authority(target)
            except ValueError:
                self._reply(client, 400, "宛先の形が不正")
                return
            if self.server.deny is not None:
                upstream, leftover = self._dial_open(client, host, port)
                if upstream is None:
                    return
            else:
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

    def _dial_open(
        self, client: socket.socket, host: str, port: int
    ) -> tuple[socket.socket | None, bytes]:
        """拒否リスト型: 拒否に当たらない宛先へつなぐ。つなげないときは応答を返して None。

        直接接続の機械と、``NO_PROXY`` に当たる宛先は、中継が名前解決してアドレスを検査し、検査した
        アドレスへつなぐ。上流のプロキシがある機械でそれ以外の名前は、上流が名前を解決するのでアドレスを
        検査できない (IP リテラルと localhost 系の名前だけ、上流へ送る前に拒否する)。
        """
        server = self.server
        assert server.deny is not None
        if host_allowed(host, port, server.deny):
            server.denied.append(f"{host}:{port}")
            self._reply(client, 403, "拒否リストに当たる宛先")
            return None, b""
        flags = (server.allow_loopback, server.allow_private)
        try:
            if _is_ip(host):
                reason = blocked_address(host, *flags)
                if reason:
                    raise Blocked(f"{host} は{reason}")
            elif (host == "localhost" or host.endswith(".localhost")) and not server.allow_loopback:
                raise Blocked("localhost はループバック")
            if not server.proxy_url or bypass(host, server.no_proxy):
                return dial_public(host, port, *flags), b""
            sock, rest = self._via_upstream(host, port)
            if sock is None:
                self._reply(client, 502, "上流へつなげない")
            return sock, rest
        except Blocked as exc:
            server.denied.append(f"{host}:{port}")
            self._reply(client, 403, f"公開でない宛先: {exc}")
        except OSError:
            self._reply(client, 502, "つなげない")
        return None, b""

    def _dial(self, host: str, port: int) -> tuple[socket.socket | None, bytes]:
        """許可リスト型: 宛先へのトンネルを張る。``NO_PROXY`` なら直接、でなければプロキシ経由。"""
        server = self.server
        if bypass(host, server.no_proxy):
            try:
                return socket.create_connection((host, port), timeout=DIAL_TIMEOUT), b""
            except OSError:
                return None, b""
        return self._via_upstream(host, port)

    def _via_upstream(self, host: str, port: int) -> tuple[socket.socket | None, bytes]:
        """上流のプロキシへ ``CONNECT`` する。中継が判定した正規化済みの authority をそのまま渡す。"""
        server = self.server
        try:
            sock = socket.create_connection(server.upstream, timeout=DIAL_TIMEOUT)
        except OSError:
            return None, b""
        try:
            authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
            request = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
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

    def __init__(
        self,
        allowed: list[str],
        proxy_url: str,
        no_proxy: str,
        deny: list[str] | None = None,
        allow_loopback: bool = False,
        allow_private: bool = False,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        # deny が None でないときは拒否リスト型 (allowed は使わない)。proxy_url が空なら直接接続
        self.deny = None if deny is None else list(deny)
        self.allow_loopback = allow_loopback
        self.allow_private = allow_private
        self.proxy_url = proxy_url
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
    """許可リストで絞って上流のプロキシへ中継する。``deny`` を渡すと拒否リスト型。

    拒否リスト型で ``proxy_url`` が空なら直接接続、あれば拒否に当たらない名前を上流へ送る。
    ``start`` で待ち受けを始める。
    """

    def __init__(
        self,
        allowed: list[str],
        proxy_url: str,
        no_proxy: str = "",
        *,
        deny: list[str] | None = None,
        allow_loopback: bool = False,
        allow_private: bool = False,
    ) -> None:
        self._server = _Server(allowed, proxy_url, no_proxy, deny, allow_loopback, allow_private)
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


def fence_config_deny(config_: dict, port: int, deny: list[str]) -> dict:
    """拒否リスト型の Fence の設定: 許可リストを空にし、拒否を Fence に渡し (hard 403)、残りは中継へ。"""
    out = copy.deepcopy(config_)
    network = out.get("network", {})
    out["network"] = {
        **network,
        "allowedDomains": [],
        "deniedDomains": list(dict.fromkeys([*(network.get("deniedDomains") or []), *deny])),
        "defaultAction": "proxy",
        "upstreamProxy": f"http://127.0.0.1:{port}",
    }
    return out


@contextlib.contextmanager
def session(config_: dict, env: dict | None = None, network: dict | None = None) -> Iterator[dict]:
    """必要なら中継を起動し、Fence へ渡す設定を返す。要らなければ設定をそのまま返す。

    拒否リスト型 (``network["mode"] == "denylist"``) は常に中継を立てる。ホストにプロキシの環境変数が
    無ければ直接接続 (中継が名前解決後のアドレスを検査できる)。あれば、拒否に当たらない名前を
    上流のプロキシへ送る (上流が名前を解決するので、中継は該当の名前のアドレスを検査できない。
    内部宛先の保護は上流プロキシの出口制御に依存する)。

    許可リスト型で中継が要るのは、プロキシの環境変数があり、許可リストがあり、``*`` を含まないとき。
    ``*`` は Fence が直接の通信を許す緩い形なので、許可リストの照合を中継へ移す意味が無い。
    """
    source = os.environ if env is None else env
    url = corporate_proxy(source)
    if network and network.get("mode") == "denylist":
        deny = list(network.get("deny") or [])
        server = Relay(
            [],
            url or "",
            _first(source, NO_PROXY_ENV) if url else "",
            deny=deny,
            allow_loopback=bool(network.get("allow_loopback")),
            allow_private=bool(network.get("allow_private_direct")),
        )
        port = server.start()
        try:
            yield fence_config_deny(config_, port, deny)
        finally:
            server.stop()
        return
    allowed = config_.get("network", {}).get("allowedDomains") or []
    if not url or not allowed or "*" in allowed:
        yield config_
        return
    relay = Relay(allowed, url, _first(source, NO_PROXY_ENV))
    port = relay.start()
    try:
        yield fence_config(config_, port)
    finally:
        relay.stop()
