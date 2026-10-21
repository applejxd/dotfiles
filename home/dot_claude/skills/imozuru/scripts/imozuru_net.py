"""検証した IP にだけ接続する (DNS rebinding への対策)。

上流 (MaryCache/imozuru) の fetch.py / watch.py は、名前を引いて宛先を検査したあと、urllib がもう一度
名前を引いて接続する。その間に引き先を変えられると、内側の宛先へ届く (上流の docstring も限界として認めている)。
ここでは、接続の直前に 1 回だけ名前を引き、全部の IP が公開アドレスなら、その IP へ接続する。
元のホスト名は Host ヘッダ・TLS の SNI と証明書の検証に使う。
プロキシ経由の接続（要求がプロキシ宛てのとき）だけは、プロキシが名前を引くので stdlib の接続のままにする
（宛先の検査は上流の `url_problem` が残る）。`no_proxy` で直接つなぐ宛先は、環境変数の有無に関わらず固定する。

see docs/spec/imozuru.md#接続の固定
"""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import urllib.request


def _addresses_inside(ip):
    """IP と、その IPv6 の中に埋め込まれた IPv4 を返す (fetch.py の同名の関数と同じ)。"""
    found = [ip]
    if ip.version == 6:
        low32 = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if ip.ipv4_mapped:
            found.append(ip.ipv4_mapped)
        if ip.sixtofour:
            found.append(ip.sixtofour)
        if ip.teredo:
            found.extend(ip.teredo)
        if (
            ip in ipaddress.ip_network("::/96")
            or ip in ipaddress.ip_network("64:ff9b::/96")
            or ip in ipaddress.ip_network("64:ff9b:1::/48")
        ):
            found.append(low32)
    return found


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return all(a.is_global for a in _addresses_inside(ip))


def connect_pinned(host, port, timeout, source_address=None):
    """名前を 1 回だけ引き、全部が公開アドレスならその IP のどれかへ接続したソケットを返す。"""
    if os.environ.get("IMOZURU_ALLOW_PRIVATE") == "1":
        return socket.create_connection((host, port), timeout, source_address)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for info in infos:
        if not _is_public(info[4][0]):
            raise OSError(f"手元や内側の宛先（{info[4][0]}）には接続しない")
    error: OSError | None = None
    for info in infos:
        try:
            # IP のまま渡すので、ここでは名前を引き直さない
            return socket.create_connection(info[4][:2], timeout, source_address)
        except OSError as e:
            error = e
    raise error or OSError(f"{host} に接続できない")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = connect_pinned(self.host, self.port, self.timeout, self.source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = connect_pinned(self.host, self.port, self.timeout, self.source_address)
        context = getattr(self, "_context", None) or ssl.create_default_context()
        self.sock = context.wrap_socket(sock, server_hostname=self.host)


def _via_proxy(req) -> bool:
    """この要求がプロキシ宛て (HTTP のプロキシ、または HTTPS の CONNECT トンネル) か。"""
    return req.has_proxy() or bool(getattr(req, "_tunnel_host", None))


class PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(
            http.client.HTTPConnection if _via_proxy(req) else _PinnedHTTPConnection, req
        )


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        conn = http.client.HTTPSConnection if _via_proxy(req) else _PinnedHTTPSConnection
        return self.do_open(conn, req, context=self._context)
