#!/usr/bin/env python3
"""Bedrock ブローカーの実機確認 (CHG-0037 の段 U7b)。結果は 1 行の「報告コード」にまとめて出す。

ホスト側の Envoy が AWS の認証情報を持ち、内側にはダミーの認証だけを渡す形 (Copilot ブローカーと同じ型) が、
Bedrock の ConverseStream で成り立つかを確かめる。認証情報はファイルで Envoy に渡し (Envoy の環境変数には入れない)、
値は一切表示しない。表示するのは、HTTP の状態・エラー型の名前・時間・環境変数の「名前」だけ。

使い方 (リポジトリの根で):

    python3 scripts/agents/bedrock_probe.py selftest
        AWS へつながずに、Envoy の設定・署名・ストリーミング・鍵ファイルの更新を、偽の上流で確かめる (数秒)

    python3 scripts/agents/bedrock_probe.py run --region <リージョン> --model <モデル ID> [--profile <名前>]
        実機の確認。--profile は ~/.aws/credentials の静的キーのプロファイル (既定 default)。
        環境変数 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (/ AWS_SESSION_TOKEN) があればそちらを使う

手順と、報告コードの読み方は docs/research/agents/bedrock-broker-field-test.md。
依存は標準ライブラリだけ。AWS の CLI は要らない。
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import hashlib
import hmac
import http.client
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve()
OCS_DIRS = (
    HERE.parents[2] / "home" / "dot_local" / "share" / "ocs",
    Path.home() / ".local/share/ocs",
)
SERVICE = "bedrock"
ORDER = ("E1", "E2", "K1", "S1", "S2", "S3", "S4", "S5", "P1", "P2", "F1")
TITLES = {
    "E1": "Envoy が実行できる",
    "E2": "Fence が実行できる",
    "K1": "認証情報 (静的キー) を用意できる",
    "S1": "Envoy の設定が通り、起動する",
    "S2": "Converse (非ストリーム) が 200",
    "S3": "ConverseStream が 200 で、応答が増分で届く",
    "S4": "鍵ファイルの更新が次の要求から反映される",
    "S5": "大きい要求 (約 1.5MB) が 413 にならない",
    "P1": "ホストのプロキシ経由で Bedrock の宛先に HTTP 応答が返る",
    "P2": "Envoy → 橋 (relay) → プロキシで Converse が 200",
    "F1": "Fence の内側から Envoy のポートへ届く",
}
CONVERSE = {
    "messages": [{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
    "inferenceConfig": {"maxTokens": 16},
}
STREAM = {
    "messages": [
        {"role": "user", "content": [{"text": "Count from 1 to 60, one number per line."}]}
    ],
    "inferenceConfig": {"maxTokens": 300},
}


def _load(name: str):
    for directory in OCS_DIRS:
        path = directory / f"{name}.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location(f"probe_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise SystemExit(f"{name}.py が見つからない (探した場所: {', '.join(map(str, OCS_DIRS))})")


broker = _load("broker")
relay = _load("relay")


# ─── Envoy の設定 ───────────────────────────────────────────────────────


def build_config(
    port: int,
    region: str,
    cred_file: Path,
    host: str,
    *,
    ca_file: str | None = None,
    plain_port: int | None = None,
    bridge_port: int | None = None,
) -> str:
    """127.0.0.1:<port> で受けて SigV4 で署名し、Bedrock (または偽の上流 ``plain_port``) へ送る設定。

    ``bridge_port`` があれば、上流へは、その橋 (relay) に ``CONNECT`` してから TLS を張る。
    """
    typed = broker._typed
    signing = {
        "name": "envoy.filters.http.aws_request_signing",
        "typed_config": typed(
            "filters.http.aws_request_signing.v3.AwsRequestSigning",
            service_name=SERVICE,
            region=region,
            host_rewrite=host,
            credential_provider={
                "custom_credential_provider_chain": True,
                "credentials_file_provider": {
                    "credentials_data_source": {
                        "filename": str(cred_file),
                        "watched_directory": {"path": str(cred_file.parent)},
                    },
                },
            },
        ),
    }
    routes = [
        {"match": {"path": "/__probe"}, **broker._direct(200, "probe-ok")},
        {"match": {"prefix": "/"}, "route": broker._upstream_route("bedrock", host)},
    ]
    manager = broker._http_manager(
        "bedrock",
        "ACCESS %REQ(:METHOD)% %RESPONSE_CODE%\n",
        [{"name": "bedrock", "domains": ["*"], "routes": routes}],
    )
    manager["typed_config"]["http_filters"].insert(0, signing)
    listener = broker._listener(
        "bedrock", {"socket_address": {"address": "127.0.0.1", "port_value": port}}, manager
    )
    listener["per_connection_buffer_limit_bytes"] = 32 * 1024 * 1024  # 署名のための本文の保持の上限
    if plain_port is not None:
        cluster = {
            "name": "bedrock",
            "type": "STATIC",
            "load_assignment": {
                "cluster_name": "bedrock",
                "endpoints": [
                    {
                        "lb_endpoints": [
                            {
                                "endpoint": {
                                    "address": {
                                        "socket_address": {
                                            "address": "127.0.0.1",
                                            "port_value": plain_port,
                                        }
                                    }
                                }
                            }
                        ]
                    }
                ],
            },
        }
    else:
        cluster = broker._upstream_cluster(
            "bedrock", host, ca_file or "", {"suffix": "amazonaws.com"}
        )
        if bridge_port is not None:
            cluster["transport_socket"] = {
                "name": "envoy.transport_sockets.http_11_proxy",
                "typed_config": typed(
                    "transport_sockets.http_11_proxy.v3.Http11ProxyUpstreamTransport",
                    transport_socket=cluster["transport_socket"],
                    default_proxy_address={
                        "socket_address": {"address": "127.0.0.1", "port_value": bridge_port}
                    },
                ),
            }
    config = {
        "node": {"id": "bedrock-probe", "cluster": "bedrock-probe"},
        "static_resources": {"listeners": [listener], "clusters": [cluster]},
    }
    return json.dumps(config, indent=2)


def write_credentials(path: Path, key_id: str, secret: str, token: str = "") -> None:
    """鍵ファイルを atomic に書く (Envoy は ``watched_directory`` の rename を見て読み直す)。"""
    lines = ["[default]", f"aws_access_key_id = {key_id}", f"aws_secret_access_key = {secret}"]
    if token:
        lines.append(f"aws_session_token = {token}")
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


class EnvoyRun:
    """Envoy を起動して待つ。環境変数は PATH と HOME だけ (鍵は環境に入れない)。"""

    def __init__(self, directory: Path, config: str) -> None:
        self.dir = directory
        self.config_path = directory / "envoy.json"
        fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(config)
        self.log = directory / "envoy.log"
        self.port = json.loads(config)["static_resources"]["listeners"][0]["address"][
            "socket_address"
        ]["port_value"]
        self.proc: subprocess.Popen | None = None

    def start(self) -> str | None:
        """起動して ``/__probe`` に答えるまで待つ。失敗なら短い理由 (ログの最後の 1 行)。"""
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())}
        with self.log.open("ab") as out:
            self.proc = subprocess.Popen(
                [broker.find_envoy(), "--config-path", str(self.config_path), "--log-level", "warning",
                 "--disable-hot-restart"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=out, env=env, start_new_session=True,
            )  # fmt: skip
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return "envoy exit: " + _last_line(self.log)
            with contextlib.suppress(OSError, http.client.HTTPException):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
                conn.request("GET", "/__probe")
                if conn.getresponse().status == 200:
                    return None
            time.sleep(0.3)
        return "timeout: " + _last_line(self.log)

    def stop(self) -> None:
        broker._terminate(self.proc)


def _last_line(path: Path) -> str:
    try:
        lines = [x for x in path.read_text(errors="replace").splitlines() if x.strip()]
    except OSError:
        return "(no log)"
    # ログに値は出ない (設定の項目名とエラーの種類だけ)。念のため 120 字で切る
    return (lines[-1] if lines else "(empty)")[:120]


# ─── 要求 ──────────────────────────────────────────────────────────────


def post(port: int, path: str, body: bytes | dict, timeout: float = 120.0) -> dict:
    """ダミーの Authorization で POST し、状態・エラー型・時間 (最初の本文 / 全体)・バイト数を返す。"""
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    start = time.monotonic()
    out = {"status": 0, "err": "", "ttfb": 0.0, "total": 0.0, "bytes": 0, "sig": "", "note": ""}
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request(
            "POST", path, body=data,
            headers={"Content-Type": "application/json", "Authorization": "dummy"},
        )  # fmt: skip
        resp = conn.getresponse()
        out["status"] = resp.status
        out["err"] = (resp.getheader("x-amzn-errortype") or "").split(":", 1)[0][:60]
        out["sig"] = resp.getheader("x-sig-ok") or ""
        first = resp.read1(65536)
        out["ttfb"] = time.monotonic() - start
        out["bytes"] = len(first)
        while chunk := resp.read(65536):
            out["bytes"] += len(chunk)
        out["total"] = time.monotonic() - start
    except (OSError, http.client.HTTPException) as e:
        out["note"] = type(e).__name__
        out["total"] = time.monotonic() - start
    return out


def model_path(model: str, action: str, *, raw_colon: bool = False) -> str:
    return f"/model/{quote(model, safe=':' if raw_colon else '')}/{action}"


# ─── 段 ────────────────────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {k: "-" for k in ORDER}
        self.detail: dict[str, str] = {}
        self.facts: list[str] = []
        self.suffix = ""  # run のときだけ: プロキシの種類 1 文字 + Fence の内側の AWS 系の名前の数

    def set(self, key: str, ok: bool | str, detail: str = "") -> None:
        self.codes[key] = ok if isinstance(ok, str) else ("1" if ok else "0")
        if detail:
            self.detail[key] = detail
        mark = {"1": "OK ", "0": "NG ", "2": "OK*", "-": "-- "}.get(self.codes[key], "?? ")
        print(f"  [{mark}] {key} {TITLES[key]}" + (f"  ({detail})" if detail else ""), flush=True)

    def print_summary(self) -> None:
        code = "".join(self.codes[k] for k in ORDER)
        print("\n" + "=" * 60)
        print("順番: " + " ".join(ORDER))
        print("1=OK 0=NG 2=別の形で OK -=実施せず")
        print(f"報告コード: BP1-{code}{self.suffix}")
        if self.suffix:
            print(
                "  末尾: -<プロキシ n=なし h=http t=https s=socks o=他><内側に残る AWS 系の環境変数の数>"
            )
        for key, text in self.detail.items():
            if self.codes[key] != "1":
                print(f"  {key}: {text}")
        for fact in self.facts:
            print(f"  {fact}")
        print("=" * 60)


def stages_signing(rep: Report, region: str, model: str, key_id: str, secret: str, token: str,
                   *, plain_port: int | None = None, host: str | None = None, bridge_port: int | None = None,
                   prefix: str = "S") -> None:  # fmt: skip
    """S1〜S5 (橋のときは P2)。"""
    host = host or f"bedrock-runtime.{region}.amazonaws.com"
    with tempfile.TemporaryDirectory(prefix="bedrock-probe-") as d:
        directory = Path(d)
        os.chmod(directory, 0o700)
        cred = directory / "credentials"
        write_credentials(cred, key_id, secret, token)
        ca = None if plain_port else broker.find_ca_file()
        port = broker.free_port()
        config = build_config(
            port, region, cred, host, ca_file=ca, plain_port=plain_port, bridge_port=bridge_port
        )
        envoy = EnvoyRun(directory, config)
        reason = envoy.start()
        first = "P2" if prefix == "P" else "S1"
        try:
            if prefix != "P":
                rep.set("S1", reason is None, reason or "")
            if reason:
                if prefix == "P":
                    rep.set("P2", False, reason)
                return
            ok2 = post(port, model_path(model, "converse"), CONVERSE)
            alt = False
            if (
                ok2["status"] != 200
                and ok2["err"]
                in ("InvalidSignatureException", "SignatureDoesNotMatch", "IncompleteSignature")
                and ":" in model
            ):
                again = post(port, model_path(model, "converse", raw_colon=True), CONVERSE)
                if again["status"] == 200:
                    ok2, alt = again, True
            detail2 = f"{ok2['status']} {ok2['err'] or ok2['note']}".strip()
            if prefix == "P":
                rep.set("P2", ok2["status"] == 200, detail2)
                return
            if plain_port is not None:
                detail2 += f" sig={ok2['sig']}"
            rep.set(
                "S2",
                "2" if alt and ok2["status"] == 200 else ok2["status"] == 200,
                detail2 + (" (: を生で送ると通る)" if alt else ""),
            )
            st = post(port, model_path(model, "converse-stream"), STREAM)
            incremental = (
                st["status"] == 200 and st["total"] > 0 and st["ttfb"] <= st["total"] * 0.8
            )
            rep.set(
                "S3",
                incremental,
                f"{st['status']} {st['err'] or st['note']} ttfb={st['ttfb']:.1f}s total={st['total']:.1f}s bytes={st['bytes']}".replace(
                    "  ", " "
                ),
            )
            # S4: 鍵ファイルを壊した値に差し替えると 403、戻すと 200 になる (読み直しの確認)
            write_credentials(cred, "AKIAPROBEINVALID0000", "x" * 40)
            time.sleep(4)
            bad = post(port, model_path(model, "converse"), CONVERSE)
            write_credentials(cred, key_id, secret, token)
            time.sleep(4)
            good = post(port, model_path(model, "converse"), CONVERSE)
            rep.set(
                "S4",
                bad["status"] == 403 and good["status"] == 200,
                f"壊すと {bad['status']} {bad['err']}、戻すと {good['status']} {good['err']}".strip(),
            )
            big = post(port, model_path(model, "converse"), {
                "messages": [{"role": "user", "content": [{"text": "a" * 1_500_000}]}],
                "inferenceConfig": {"maxTokens": 8},
            }, timeout=60)  # fmt: skip
            rep.set(
                "S5",
                big["status"] not in (0, 413, 502, 503, 504),
                f"{big['status']} {big['err'] or big['note']}".strip(),
            )
        finally:
            envoy.stop()
            del first


# ─── 偽の上流 (selftest) ─────────────────────────────────────────────────


def _sigv4_ok(handler: http.server.BaseHTTPRequestHandler, body: bytes, secret: str) -> bool:
    """受け取った要求の SigV4 を、既知の秘密鍵で検算する (Envoy の署名が正しいかの確認)。"""
    auth = handler.headers.get("Authorization", "")
    m = re.match(
        r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/([^/]+)/aws4_request, SignedHeaders=([^,]+), Signature=([0-9a-f]+)",
        auth,
    )
    if not m:
        return False
    _, date, region, service, signed, signature = m.groups()
    uri = quote(handler.path.split("?", 1)[0], safe="/-_.~")
    headers = "".join(
        f"{h}:{' '.join((handler.headers.get(h) or '').split())}\n" for h in signed.split(";")
    )
    payload = handler.headers.get("x-amz-content-sha256") or hashlib.sha256(body).hexdigest()
    canonical = "\n".join([handler.command, uri, "", headers, signed, payload])
    amz_date = handler.headers.get("x-amz-date", "")
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            f"{date}/{region}/{service}/aws4_request",
            hashlib.sha256(canonical.encode()).hexdigest(),
        ]
    )
    key = ("AWS4" + secret).encode()
    for part in (date, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(
        hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest(), signature
    )


def fake_upstream(secret: str):
    """偽の Bedrock。署名を検算し、ストリームは 0.4 秒おきに 6 個のかたまりで返す。"""

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_a):
            return

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            key = (
                re.search(r"Credential=([^/]+)/", self.headers.get("Authorization", ""))
                or [None, ""]
            )[1]
            if key == "AKIAPROBEINVALID0000":
                self.send_response(403)
                self.send_header("x-amzn-ErrorType", "UnrecognizedClientException:http://x")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            ok = "1" if _sigv4_ok(self, body, secret) else "0"
            if len(body) > 1_000_000:
                self.send_response(400)
                self.send_header("x-amzn-ErrorType", "ValidationException:http://x")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("x-sig-ok", ok)
            if self.path.endswith("/converse-stream"):
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for i in range(6):
                    chunk = f"frame-{i}\n".encode()
                    self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                    time.sleep(0.4)
                self.wfile.write(b"0\r\n\r\n")
            else:
                payload = b'{"output":"OK"}'
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ─── 実機の段 ────────────────────────────────────────────────────────────


def read_credentials(profile: str) -> tuple[str, str, str] | None:
    """環境変数か ~/.aws/credentials の静的キー。無ければ None。値は返すだけで、表示しない。"""
    env = os.environ
    if env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"):
        return (
            env["AWS_ACCESS_KEY_ID"],
            env["AWS_SECRET_ACCESS_KEY"],
            env.get("AWS_SESSION_TOKEN", ""),
        )
    path = Path(env.get("AWS_SHARED_CREDENTIALS_FILE") or Path.home() / ".aws" / "credentials")
    parser = configparser.RawConfigParser()
    try:
        parser.read(path)
        section = parser[profile]
        return (
            section["aws_access_key_id"],
            section["aws_secret_access_key"],
            section.get("aws_session_token", ""),
        )
    except (OSError, KeyError, configparser.Error):
        return None


def find_fence() -> str | None:
    found = shutil.which("fence")
    if found:
        return found
    matches = sorted(
        (Path.home() / ".local/share/mise/installs").glob("github-fencesandbox-fence/*/fence")
    )
    return str(matches[-1]) if matches else None


def proxy_kind() -> str:
    value = next(
        (
            os.environ[k]
            for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
            if os.environ.get(k)
        ),
        "",
    )
    if not value:
        return "none"
    scheme = value.split("://", 1)[0].lower() if "://" in value else "http"
    return scheme if scheme in ("http", "https", "socks5", "socks5h") else "other"


def stage_fence(rep: Report, fence: str, port: int) -> None:
    """Fence の内側から Envoy のポートへ届くか (F1)と、内側の環境変数に AWS 系の名前が残るか (事実)。"""
    with tempfile.TemporaryDirectory(prefix="bedrock-probe-") as d:
        settings = Path(d) / "fence.json"
        settings.write_text(
            json.dumps(
                {
                    "network": {
                        "allowedDomains": [],
                        "allowLocalOutbound": True,
                        "allowLocalOutboundPorts": [port],
                    }
                }
            )
        )

        def run(cmd: list[str]) -> str:
            res = subprocess.run(
                [fence, "--settings", str(settings), "--", *cmd],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return res.stdout.strip()

        code = run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--max-time",
                "10",
                f"http://127.0.0.1:{port}/__probe",
            ]
        )
        rep.set("F1", code == "200", code or "no response")
        names = run(
            ["sh", "-c", "env | cut -d= -f1 | grep -E '^AWS_|BEDROCK|BEARER' | sort | tr '\\n' ' '"]
        )
        rep.facts.append("Fence の内側に残る AWS 系の環境変数の名前: " + (names or "(なし)"))
        rep.suffix = rep.suffix.rstrip("-") + f"{min(len(names.split()), 9)}"


def cmd_run(args: argparse.Namespace) -> int:
    rep = Report()
    print("Bedrock ブローカーの実機確認 (値は表示しません)\n")
    kind = proxy_kind()
    rep.facts.append(f"プロキシの環境変数: {kind} / python {sys.version.split()[0]}")
    letters = {"none": "n", "http": "h", "https": "t", "socks5": "s", "socks5h": "s", "other": "o"}
    rep.suffix = f"-{letters[kind]}-"
    try:
        envoy = broker.find_envoy()
        version = subprocess.run(
            [envoy, "--version"], capture_output=True, text=True, timeout=15, check=False
        ).stdout
        rep.set("E1", True, (re.search(r"/(\d+\.\d+\.\d+)/", version) or [None, "?"])[1])
    except Exception as e:
        rep.set("E1", False, str(e).split("\n")[0][:80])
        rep.print_summary()
        return 1
    fence = find_fence()
    rep.set("E2", fence is not None, "" if fence else "fence が見つからない")
    creds = read_credentials(args.profile)
    rep.set(
        "K1",
        creds is not None,
        "" if creds else "静的キーのプロファイルが見つからない (--profile / 環境変数)",
    )
    if creds is None:
        rep.print_summary()
        return 1
    key_id, secret, token = creds
    host = f"bedrock-runtime.{args.region}.amazonaws.com"
    stages_signing(rep, args.region, args.model, key_id, secret, token)
    if kind != "none":
        if shutil.which("curl"):
            res = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--max-time",
                    "20",
                    f"https://{host}/",
                ],
                capture_output=True,
                text=True,
                timeout=40,
                check=False,
            )
            ok = res.returncode == 0
            rep.set(
                "P1",
                ok,
                res.stdout.strip()
                if ok
                else (
                    "TLS 検査の CA が無い? (curl 60)"
                    if res.returncode == 60
                    else f"curl rc={res.returncode}"
                ),
            )
        proxy_url = relay.corporate_proxy()
        if proxy_url:
            captured: list[str] = []
            original = relay._Handler._via_upstream

            def spy(self, h, p):
                captured.append("ip" if relay._is_ip(h) else "host")
                return original(self, h, p)

            relay._Handler._via_upstream = spy
            bridge = relay.Relay([], proxy_url, "", deny=[])
            bport = bridge.start()
            try:
                stages_signing(
                    rep,
                    args.region,
                    args.model,
                    key_id,
                    secret,
                    token,
                    bridge_port=bport,
                    prefix="P",
                )
            finally:
                bridge.stop()
                relay._Handler._via_upstream = original
            rep.facts.append(
                "橋が受けた CONNECT の宛先の形: " + (",".join(sorted(set(captured))) or "(なし)")
            )
    if fence:
        # F1 用に、短時間だけ Envoy を立てる (S の Envoy は終了済み)
        with tempfile.TemporaryDirectory(prefix="bedrock-probe-") as d:
            directory = Path(d)
            os.chmod(directory, 0o700)
            cred = directory / "credentials"
            write_credentials(cred, key_id, secret, token)
            port = broker.free_port()
            run = EnvoyRun(
                directory,
                build_config(port, args.region, cred, host, ca_file=broker.find_ca_file()),
            )
            reason = run.start()
            try:
                if reason:
                    rep.set("F1", False, reason)
                else:
                    stage_fence(rep, fence, port)
            finally:
                run.stop()
    rep.print_summary()
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    rep = Report()
    print("selftest: 偽の上流で、Envoy の署名・ストリーミング・鍵ファイルの更新を確認します\n")
    secret = "selftest-secret-" + "k" * 24
    server = fake_upstream(secret)
    try:
        host = f"127.0.0.1:{server.server_address[1]}"
        stages_signing(
            rep,
            "us-east-1",
            "test.model-v1:0",
            "AKIASELFTEST000000",
            secret,
            "",
            plain_port=server.server_address[1],
            host=host,
        )
    finally:
        server.shutdown()
    rep.print_summary()
    ok = all(rep.codes[k] in ("1", "2") for k in ("S1", "S2", "S3", "S4", "S5"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    run = sub.add_parser("run")
    run.add_argument("--region", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--profile", default="default")
    run.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
