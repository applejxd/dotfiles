"""``pis`` の Copilot ブローカー (``PIS_COPILOT_BROKER=auto``) を、pis と同じ寿命で動かす。

ホスト側 (Fence の外) で自分専用の Envoy を空きポートに立て、pis の終了で止める。
本物の認証情報 (GitHub の長期トークンと短命の Copilot トークン) はホストと Envoy だけが持ち、
内側の pi にはダミーしか渡さない。Envoy は ``credential_injector`` で ``Authorization`` を付ける。

- 状態ディレクトリ (0700) に SDS ファイル・Envoy の設定・ログを置き、終了時に丸ごと消す
- 短命トークンは期限の少し前に取り直し、SDS ファイルを rename で置き換える (Envoy が監視している)
- トークンの値は、標準出力・標準エラー・例外メッセージ・ログに出さない

see docs/change/0037-pis-usability-and-telemetry.md
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

# pi-ai (dist/auth/oauth/github-copilot.js) の COPILOT_HEADERS と同じ
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
PROVIDER = "github-copilot"
SECRET_NAME = "copilot_token"
SDS_NAME = "copilot-sds.json"
CONFIG_NAME = "envoy-copilot.yaml"
LOG_NAME = "broker.log"
ENVOY_LOG_NAME = "envoy.log"
TEMPLATE = Path(__file__).resolve().parent / CONFIG_NAME
DEFAULT_HOST = "api.individual.githubcopilot.com"
IDENTITY_PATH = "/__pis_broker"
IDENTITY_PREFIX = "pis-broker-copilot"

REFRESH_MARGIN_SECONDS = 5 * 60  # 期限のこれだけ前に取り直す
RETRY_SECONDS = 60  # 取り直しに失敗したときの待ち
READY_TIMEOUT_SECONDS = 10.0
READY_INTERVAL_SECONDS = 0.2
EXCHANGE_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 5

INSTALL_HINT = (
    "Envoy の公式リリースの Linux x86_64 バイナリと、同じリリースの sha256 を取り、"
    "照合してから ~/.local/bin/envoy へ置いて実行権限を付ける"
)


class BrokerError(RuntimeError):
    """ブローカーを立てられない。``hint`` は次の手 (``pi.py`` が ``die`` へ渡す)。"""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def find_envoy(home: Path | None = None) -> str:
    """``envoy`` の実行ファイル。PATH、無ければ ``~/.local/bin/envoy``。"""
    found = shutil.which("envoy")
    if found:
        return found
    base = home if home is not None else Path.home()
    local = base / ".local" / "bin" / "envoy"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise BrokerError("envoy が見つからない (PATH にも ~/.local/bin/envoy にも無い)", INSTALL_HINT)


def agent_dir() -> Path:
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")


def load_refresh_token(agent: Path) -> str:
    """ホストの ``auth.json`` から、長期の GitHub トークン (``refresh``) を読む。"""
    path = agent / "auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BrokerError(
            f"{path} を読めない ({type(e).__name__})", "pi で /login して auth.json を作る"
        ) from None
    entry = data.get(PROVIDER) if isinstance(data, dict) else None
    refresh = entry.get("refresh") if isinstance(entry, dict) else None
    if not isinstance(refresh, str) or not refresh:
        raise BrokerError(
            f"{path} に {PROVIDER} の OAuth の資格情報が無い", "pi で /login して先に作る"
        )
    return refresh


def exchange(refresh: str) -> tuple[str, int]:
    """長期トークンで、短命の Copilot トークンと ``expires_at`` (UNIX 秒) を得る。

    例外にはトークンも要求ヘッダーも入れない (型名と HTTP の状態だけ)。
    """
    request = urllib.request.Request(
        TOKEN_URL, headers={**HEADERS, "Authorization": f"Bearer {refresh}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=EXCHANGE_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BrokerError(f"Copilot のトークンを取れない (HTTP {e.code})") from None
    except (OSError, ValueError) as e:
        raise BrokerError(f"Copilot のトークンを取れない ({type(e).__name__})") from None
    token = raw.get("token") if isinstance(raw, dict) else None
    expires_at = raw.get("expires_at") if isinstance(raw, dict) else None
    if not isinstance(token, str) or not token or not isinstance(expires_at, int):
        raise BrokerError("Copilot のトークンの応答の形が想定と違う")
    return token, expires_at


def upstream_host(token: str) -> str:
    """トークンの ``proxy-ep=`` から中継先を決める (``proxy.`` → ``api.``)。無い・不正なら既定。"""
    match = re.search(r"proxy-ep=([^;]+)", token)
    if not match:
        return DEFAULT_HOST
    host = match.group(1).replace("proxy.", "api.", 1)
    # 設定へ埋め込むので、ホスト名の文字だけを通す
    return host if re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", host) else DEFAULT_HOST


def write_sds(path: Path, token: str) -> None:
    """Envoy が監視するディレクトリへ、rename でアトミックに置く (0600)。"""
    body = {
        "resources": [
            {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.Secret",
                "name": SECRET_NAME,
                "generic_secret": {"secret": {"inline_string": token}},
            }
        ]
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sds-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def render_config(template: str, port: int, host: str, sds_dir: Path) -> str:
    """雛形の ``@PORT@`` / ``@HOST@`` / ``@SDS_DIR@`` を置き換える。"""
    return (
        template.replace(
            '"@PORT@"', str(port)
        )  # 雛形では引用符で囲み (YAML として有効)、置換後は整数
        .replace("@HOST@", host)
        .replace("@SDS_DIR@", str(sds_dir))
    )


def free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ得る (閉じてから Envoy が使う)。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_state_dir(home: Path | None = None) -> Path:
    """起動ごとの状態ディレクトリ (0700)。``$XDG_RUNTIME_DIR`` の下、無ければ ``~/.local/state/pis``。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        base = Path(runtime)
    else:
        base = (home if home is not None else Path.home()) / ".local" / "state" / "pis"
        base.mkdir(parents=True, exist_ok=True)
    state = Path(tempfile.mkdtemp(prefix="pis-broker-", dir=str(base)))
    os.chmod(state, 0o700)
    return state


def _log(path: Path, message: str) -> None:
    """失敗の事実を状態ディレクトリのログへ追記する (トークンの値は書かない)。"""
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def _refresh_loop(
    stop: threading.Event,
    refresh: str,
    sds: Path,
    log: Path,
    expires_at: int,
    margin: float,
    retry: float,
) -> None:
    """期限の ``margin`` 秒前に取り直して SDS を書き直す。失敗したら ``retry`` 秒後に再試行する。"""
    while True:
        if stop.wait(max(0.0, expires_at - time.time() - margin)):
            return
        try:
            token, expires_at = exchange(refresh)
            write_sds(sds, token)
        except (BrokerError, OSError) as e:
            if stop.is_set():
                return  # 終了処理中に状態ディレクトリが消えただけ
            _log(log, f"トークンの更新に失敗: {type(e).__name__}: {e}")
            if stop.wait(retry):
                return


def _tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(ログを読めない)"
    return "\n".join(text.splitlines()[-lines:])


def _probe(opener: urllib.request.OpenerDirector, url: str) -> bool:
    """身元の確認 1 回。200 かつ本文が ``pis-broker-copilot`` で始まれば True。まだなら False。"""
    try:
        with opener.open(url + IDENTITY_PATH, timeout=1) as response:
            body = response.read(256).decode("utf-8", errors="replace")
            return response.status == 200 and body.startswith(IDENTITY_PREFIX)
    except OSError:
        return False  # まだ待ち受けていない (呼び出し側が期限まで再試行する)


def _wait_ready(url: str, proc: subprocess.Popen, log: Path, timeout: float) -> None:
    """``/__pis_broker`` が応答するまで待つ (プロキシは使わない)。出なければログ末尾を添えて例外。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while True:
        if proc.poll() is not None:
            raise BrokerError(
                f"Envoy が起動直後に終了した (code={proc.returncode})\n{_tail(log)}",
                f"{log} を見る",
            )
        if _probe(opener, url):
            return
        if time.monotonic() >= deadline:
            raise BrokerError(
                f"Envoy が {timeout:g} 秒以内に応答しなかった ({url})\n{_tail(log)}",
                f"{log} を見る",
            )
        time.sleep(READY_INTERVAL_SECONDS)


def _terminate(proc: subprocess.Popen | None) -> None:
    """SIGTERM、``STOP_TIMEOUT_SECONDS`` 待って、残れば SIGKILL。"""
    if proc is None:
        return
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@contextlib.contextmanager
def session(
    agent: Path | None = None,
    *,
    home: Path | None = None,
    refresh_margin: float = REFRESH_MARGIN_SECONDS,
    retry_seconds: float = RETRY_SECONDS,
    ready_timeout: float = READY_TIMEOUT_SECONDS,
) -> Iterator[str]:
    """自分専用の Envoy を立て、``http://127.0.0.1:<port>`` を返す。抜けると止めて状態を消す。

    ``agent`` はホストの agent 置き場 (``auth.json`` がある所。既定は ``PI_CODING_AGENT_DIR`` か
    ``~/.pi/agent``)。立てられなければ :class:`BrokerError` (呼び出し側が ``die`` に変える)。
    ``refresh_margin`` ``retry_seconds`` ``ready_timeout`` は試験で短くするための引数。
    """
    envoy = find_envoy(home)
    refresh = load_refresh_token(agent if agent is not None else agent_dir())
    token, expires_at = exchange(refresh)
    host = upstream_host(token)
    state = make_state_dir(home)
    stop = threading.Event()
    proc: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    try:
        sds = state / SDS_NAME
        write_sds(sds, token)
        del token
        port = free_port()
        config = state / CONFIG_NAME
        config.write_text(
            render_config(TEMPLATE.read_text(encoding="utf-8"), port, host, state),
            encoding="utf-8",
        )
        os.chmod(config, 0o600)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home or Path.home())}
        envoy_log = state / ENVOY_LOG_NAME
        with envoy_log.open("ab") as out:
            proc = subprocess.Popen(
                [
                    envoy,
                    "--config-path",
                    str(config),
                    "--log-level",
                    "warning",
                    "--disable-hot-restart",
                ],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                start_new_session=True,
                env=env,
            )
        thread = threading.Thread(
            target=_refresh_loop,
            args=(stop, refresh, sds, state / LOG_NAME, expires_at, refresh_margin, retry_seconds),
            daemon=True,
        )
        thread.start()
        url = f"http://127.0.0.1:{port}"
        _wait_ready(url, proc, envoy_log, ready_timeout)
        yield url
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=STOP_TIMEOUT_SECONDS)
        _terminate(proc)
        shutil.rmtree(state, ignore_errors=True)
