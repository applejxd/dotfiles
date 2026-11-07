"""擬似プロキシ（box.tools.fake_proxy）の試験。127.0.0.1 のポート 0 だけを使い、外へは出ない。"""

from __future__ import annotations

import http.client
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from box.tools.fake_proxy import make_server, serve_in_thread


class _Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"origin-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(self.request.recv(100).upper())


@pytest.fixture()
def origin():
    http_srv = HTTPServer(("127.0.0.1", 0), _Origin)
    echo_srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    echo_srv.daemon_threads = True
    for s in (http_srv, echo_srv):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield http_srv.server_address[1], echo_srv.server_address[1]
    for s in (http_srv, echo_srv):
        s.shutdown()
        s.server_close()


def _start(**kw):
    server = make_server(0, log=lambda line: None, **kw)
    serve_in_thread(server)
    return server


def _get(server, port):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    conn.request("GET", f"http://127.0.0.1:{port}/x")
    resp = conn.getresponse()
    return resp.status, resp.read()


def _connect(server, port):
    s = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5)
    s.sendall(f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += s.recv(1024)
    return s, int(head.split()[1])


def test_待受は_127_0_0_1_だけ():
    server = _start()
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.shutdown()
        server.server_close()


def test_http_の_get_が通る(origin):
    server = _start()
    try:
        assert _get(server, origin[0]) == (200, b"origin-ok")
        assert server.seen == [f"ALLOW 127.0.0.1:{origin[0]}"]
    finally:
        server.shutdown()
        server.server_close()


def test_connect_が通る(origin):
    server = _start()
    try:
        s, status = _connect(server, origin[1])
        assert status == 200
        s.sendall(b"abc")
        assert s.recv(10) == b"ABC"
        s.close()
    finally:
        server.shutdown()
        server.server_close()


def test_deny_all_は_get_も_connect_も拒否(origin):
    server = _start(deny_all=True)
    try:
        assert _get(server, origin[0])[0] == 403
        s, status = _connect(server, origin[1])
        assert status == 403
        s.close()
    finally:
        server.shutdown()
        server.server_close()


def test_許可リスト外は拒否_内は通る(origin):
    server = _start(allow=("localhost",))
    try:
        assert _get(server, origin[0])[0] == 403  # 127.0.0.1 は許可リスト外
        assert any(line.startswith("DENY") for line in server.seen)
    finally:
        server.shutdown()
        server.server_close()
    server = _start(allow=("127.0.0.1",))
    try:
        assert _get(server, origin[0])[0] == 200
    finally:
        server.shutdown()
        server.server_close()
