"""試験用の認証なしプロキシ（HTTP と HTTPS の CONNECT）。標準ライブラリだけ。

127.0.0.1 のみで待ち受ける。アクセスログには宛先の ホスト:ポート だけを出す（パス・ヘッダーは出さない）。
  --allow ホスト名   許可リスト（複数指定可）。指定すると、リスト外は 403
  --deny-all         すべて拒否（403）
T9（proxy-only の実測）の擬似プロキシとして使う。本番用ではない。
"""

from __future__ import annotations

import argparse
import contextlib
import select
import socket
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

HOST = "127.0.0.1"


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, allow: frozenset[str], deny_all: bool, log=None):
        super().__init__((HOST, port), _Handler)
        self.allow = allow
        self.deny_all = deny_all
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self.seen: list[str] = []  # 試験用: 通した・拒否した宛先


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _permitted(self, host: str, port: int) -> bool:
        target = f"{host}:{port}"
        ok = not self.server.deny_all and (not self.server.allow or host in self.server.allow)
        self.server.seen.append(f"{'ALLOW' if ok else 'DENY'} {target}")
        self.server.log(f"{'ALLOW' if ok else 'DENY'} {target}")
        return ok

    def _deny(self) -> None:
        self.send_error(403, "denied by fake_proxy")

    def do_CONNECT(self) -> None:
        host, _, port_s = self.path.rpartition(":")
        port = int(port_s) if port_s.isdigit() else 443
        if not self._permitted(host, port):
            return self._deny()
        try:
            upstream = socket.create_connection((host, port), timeout=10)
        except OSError:
            return self.send_error(502, "upstream failed")
        self.send_response(200, "Connection established")
        self.end_headers()
        self.close_connection = True
        socks = [self.connection, upstream]
        try:
            while True:
                readable, _, _ = select.select(socks, [], [], 30)
                if not readable:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is self.connection else self.connection).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()

    def _forward(self) -> None:
        parts = urlsplit(self.path)
        host = parts.hostname or ""
        port = parts.port or 80
        if not self._permitted(host, port):
            return self._deny()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = Request(self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in ("proxy-connection", "connection", "host", "content-length"):
                req.add_header(k, v)
        try:
            # 環境変数のプロキシは使わない（自分自身への迷い込みを避ける）
            with build_opener(ProxyHandler({})).open(req, timeout=10) as resp:
                data = resp.read()
                status, headers = resp.status, resp.getheaders()
        except Exception:
            return self.send_error(502, "upstream failed")
        self.send_response(status)
        for k, v in headers:
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = _forward


def make_server(
    port: int = 0, allow: tuple[str, ...] = (), deny_all: bool = False, log=None
) -> _Server:
    """サーバーを作る（port=0 で自動割当。server.server_address[1] で確認）。"""
    return _Server(port, frozenset(allow), deny_all, log)


def serve_in_thread(server: _Server) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=3128)
    ap.add_argument("--allow", action="append", default=[], metavar="ホスト名")
    ap.add_argument("--deny-all", action="store_true")
    args = ap.parse_args(argv)
    server = make_server(args.port, tuple(args.allow), args.deny_all)
    print(f"fake_proxy: {HOST}:{server.server_address[1]}", file=sys.stderr, flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
