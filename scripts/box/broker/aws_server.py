"""aws の認証情報サーバー（ホスト側。標準ライブラリだけ）。

AWS の「コンテナ認証情報エンドポイント」の形で、固定ロールの短期認証情報を返す。
unix ソケットの HTTP で、`GET /creds` だけに答える。箱の中の loopback の TCP は proxy デバイスが中継する。

方針:
- ロール・TTL・セッション名は起動時の引数（ロールは root 専用ファイル）で固定する。要求（パス・クエリ・ヘッダー）からは選べない。
  広いロールへの代替は作らない（契約 C1）
- 認証情報はキャッシュするが、ログ・標準エラー・例外には出さない。assume-role の失敗は 503（理由の定型文だけ）
- ホストの aws CLI の認証（SSO など）は、このプロセスの実行ユーザーのものを使う。起動の主体は未確認（申し送り）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEFAULT_TTL = 3600
MIN_TTL = 900
MAX_TTL = 43200
CACHE_MARGIN_SECONDS = 300  # 期限のこれだけ前に取り直す
ASSUME_TIMEOUT_SECONDS = 30
_ARN = re.compile(r"arn:aws[a-z-]*:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}")
_SESSION = re.compile(r"[A-Za-z0-9+=,.@_-]{2,64}")

# aws の呼び出しを差し替えられる型（argv → (終了コード, 標準出力)）
Runner = Callable[[Sequence[str]], tuple[int, str]]


class CredsError(RuntimeError):
    """認証情報を得られない。メッセージは定型文だけ（認証情報・ロールの値を入れない）。"""


def clamp_ttl(ttl: int) -> int:
    return max(MIN_TTL, min(int(ttl), MAX_TTL))


def _default_runner(argv: Sequence[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ASSUME_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return done.returncode, done.stdout  # 標準エラーは捨てる（捨てないと値が漏れうる）


def assume_role_argv(role_arn: str, session_name: str, ttl: int) -> tuple[str, ...]:
    return (
        "aws",
        "sts",
        "assume-role",
        "--role-arn",
        role_arn,
        "--role-session-name",
        session_name,
        "--duration-seconds",
        str(clamp_ttl(ttl)),
        "--output",
        "json",
    )


def _to_utc_z(value: str) -> tuple[str, float]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ"), parsed.timestamp()


class CredentialSource:
    """固定ロールの短期認証情報（キャッシュつき）。"""

    def __init__(
        self,
        role_arn: str,
        session_name: str,
        ttl: int = DEFAULT_TTL,
        runner: Runner | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not _ARN.fullmatch(role_arn):
            raise ValueError("ロールの ARN の形が不正")
        if not _SESSION.fullmatch(session_name):
            raise ValueError("セッション名の形が不正")
        self._role = role_arn
        self._session = session_name
        self._ttl = clamp_ttl(ttl)
        self._run = runner or _default_runner
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: tuple[dict[str, str], float] | None = None

    def get(self) -> dict[str, str]:
        with self._lock:
            if self._cache and self._cache[1] - self._clock() > CACHE_MARGIN_SECONDS:
                return dict(self._cache[0])
            creds, expires = self._fetch()
            self._cache = (creds, expires)
            return dict(creds)

    def _fetch(self) -> tuple[dict[str, str], float]:
        code, out = self._run(assume_role_argv(self._role, self._session, self._ttl))
        if code != 0:
            raise CredsError("assume-role に失敗した")
        try:
            raw = json.loads(out)["Credentials"]
            expiration, expires = _to_utc_z(str(raw["Expiration"]))
            creds = {
                "AccessKeyId": str(raw["AccessKeyId"]),
                "SecretAccessKey": str(raw["SecretAccessKey"]),
                "Token": str(raw["SessionToken"]),
                "Expiration": expiration,
            }
        except (ValueError, KeyError, TypeError):
            raise CredsError("assume-role の応答の形が想定と違う") from None
        return creds, expires


def make_handler(source: CredentialSource) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "box-aws-creds"

        def log_message(self, format: str, *args: object) -> None:
            return  # アクセスログは出さない（認証情報・要求の中身を残さない）

        def _send(self, status: int, body: dict[str, str]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0]
            if route == "/healthz":  # 起動の確認用（STS を呼ばない・認証情報なし）
                self._send(200, {"message": "box-aws-creds"})
                return
            if route != "/creds":
                self._send(404, {"message": "not found"})
                return
            try:
                creds = source.get()
            except CredsError as e:
                self._send(503, {"message": str(e)})
                return
            self._send(200, creds)

        def _deny(self) -> None:
            self._send(405, {"message": "method not allowed"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _deny

    return Handler


class UnixHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True

    def server_bind(self) -> None:
        path = self.server_address
        if isinstance(path, bytes):
            path = path.decode()
        Path(str(path)).unlink(missing_ok=True)
        old = os.umask(0o177)  # ソケットは作成時から 0600
        try:
            self.socket.bind(path)
        finally:
            os.umask(old)
        os.chmod(str(path), 0o600)
        self.server_name = "box-aws"
        self.server_port = 0

    def client_address_string(self) -> str:  # pragma: no cover
        return "unix"


def make_server(socket_path: str, source: CredentialSource) -> UnixHTTPServer:
    return UnixHTTPServer(socket_path, make_handler(source))  # type: ignore[arg-type]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="box-aws-creds")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--role-arn-file", required=True)
    parser.add_argument("--session-name", required=True)
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    args = parser.parse_args(argv)
    try:
        role = Path(args.role_arn_file).read_text(encoding="utf-8").strip()
        source = CredentialSource(role, args.session_name, args.ttl)
    except (OSError, ValueError) as e:
        print(f"起動できない: {type(e).__name__}", file=sys.stderr)  # 値は出さない
        return 2
    server = make_server(args.socket, source)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
