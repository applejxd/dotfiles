"""copilot ブローカーの計画。本物の長期トークンはホストの Envoy と更新プロセスだけが持つ。箱へ入れるのは
ダミーの COPILOT_GITHUB_TOKEN と、models.json（providers.github-copilot.baseUrl）の差分だけ。

仕様は既存の pis 用ブローカーに合わせる（docs/spec/sandbox/broker.md の「Copilot ブローカー」）:
- 通すのは POST /v1/messages・/responses・/chat/completions の完全一致だけ。他は 403
- 身元確認 GET /__box_broker（pis の /__pis_broker を box 用に改名）。200 で本文 box-broker-copilot
- 認証: 長期トークンで短命の Copilot トークンを交換（refresh サブコマンド）し、SDS へ rename で置く。
  Envoy が Authorization を Bearer で上書きする。期限の 5 分前に取り直し、失敗は 60 秒後に再試行
- 上流は既定の api.individual.githubcopilot.com、上流 TLS は CA と SAN（githubcopilot.com の suffix）で検証

pis との違い（箱の都合）: Node の fetch は unix ソケットを使えないので、箱の baseUrl は loopback の TCP
（127.0.0.1:7112。proxy デバイスでホストの unix ソケットへ中継）にする。

未確認: トークンの proxy-ep で上流を変える挙動（この版は固定の既定ホスト）・Node の fetch が baseUrl の
loopback へ届くか・SDS の再読み込み。models.json を丸ごと置くので、箱側の既存の models.json は上書きされる。
refresh は systemd の unit で動かす（PYTHONPATH は ROOT_HELPER_DIR の親。配備の前提は未確認）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from box import model
from box.broker import (
    cleanup_op,
    curl_unix_op,
    ensure_command_op,
    ensure_dirs_op,
    host_sock,
    loopback_proxy_device,
    prepare_op,
    require_secret,
    start_unit_op,
    state_dir,
    stop_unit_op,
)
from box.broker.gh import (
    SDS_NAME,
    direct,
    http_manager,
    upstream_cluster,
    upstream_route,
)

COPILOT_PORT = 7112
UPSTREAM_HOST = "api.individual.githubcopilot.com"
UPSTREAM_SUFFIX = "githubcopilot.com"
PATHS = ("/v1/messages", "/responses", "/chat/completions")
IDENTITY_PATH = "/__box_broker"
IDENTITY_BODY = "box-broker-copilot"
SECRET_NAME = "copilot_token"
DUMMY_TOKEN = "box-dummy-copilot-token"
PROVIDER = "github-copilot"
TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}
REFRESH_MARGIN_SECONDS = 5 * 60
RETRY_SECONDS = 60
EXCHANGE_TIMEOUT_SECONDS = 30
MODELS_JSON = f"{model.BOX_HOME}/.pi/agent/models.json"
SECRET_REF_NAME = "copilot"


def envoy_config(socket_path: str, sds_dir: str) -> str:
    """copilot 用の Envoy 設定（純粋。トークンは入らない）。"""
    post = {"name": ":method", "string_match": {"exact": "POST"}}
    routes: list[dict[str, Any]] = [
        {"match": {"path": IDENTITY_PATH}, **direct(200, IDENTITY_BODY)}
    ]
    routes += [
        {
            "match": {"path": path, "headers": [post]},
            "route": upstream_route("copilot_upstream", UPSTREAM_HOST),
        }
        for path in PATHS
    ]
    routes.append(
        {"match": {"prefix": "/"}, **direct(403, "box-broker: path or method not allowed")}
    )
    manager = http_manager(
        "copilot", [{"name": "copilot", "domains": ["*"], "routes": routes}], sds_dir, SECRET_NAME
    )
    listener = {
        "name": "copilot",
        "address": {"pipe": {"path": socket_path, "mode": 0o600}},
        "filter_chains": [{"filters": [manager]}],
    }
    config = {
        "node": {"id": "box-broker", "cluster": "box-broker"},  # SDS（generic secret）に必須
        "static_resources": {
            "listeners": [listener],
            "clusters": [
                upstream_cluster("copilot_upstream", UPSTREAM_HOST, {"suffix": UPSTREAM_SUFFIX})
            ],
        },
    }
    return json.dumps(config, sort_keys=True)


def models_json() -> str:
    """箱の models.json（baseUrl の差分だけ。本物の認証・他の設定を含まない）。"""
    body = {"providers": {PROVIDER: {"baseUrl": f"http://{model.LOOPBACK}:{COPILOT_PORT}"}}}
    return json.dumps(body, indent=2) + "\n"


def plan(cfg: model.BoxConfig, policy: model.RepoPolicy) -> model.BrokerPlan:
    ref = require_secret(policy, SECRET_REF_NAME)
    sock = host_sock(cfg.repo_id, "copilot")
    sdir = state_dir(cfg.repo_id, "copilot")
    pythonpath = os.path.dirname(model.ROOT_HELPER_DIR)
    refresh = ("python3", "-m", "box.broker.copilot", "refresh", "--state-dir", sdir)
    host_ops = (
        ensure_command_op(
            "envoy", "envoy が無い（ホストに Envoy を入れる。docs/spec/sandbox/broker.md）"
        ),
        stop_unit_op(cfg.repo_id, "copilot"),
        stop_unit_op(cfg.repo_id, "copilot", "refresh"),
        ensure_dirs_op(cfg.repo_id),
        prepare_op(cfg.repo_id, "copilot", ref),
        # Envoy の起動前に、短命トークンの SDS を 1 回作る（無いと Envoy の SDS が待つ）
        model.Op(
            "host",
            ("env", f"PYTHONPATH={pythonpath}", *refresh, "--once"),
            "短命の Copilot トークンを 1 回取得して SDS を作る",
        ),
        start_unit_op(
            cfg.repo_id,
            "copilot",
            (f"--setenv=PYTHONPATH={pythonpath}", *refresh),
            "Copilot トークンの更新を常駐させる",
            "refresh",
        ),
        start_unit_op(
            cfg.repo_id,
            "copilot",
            (
                "envoy",
                "--config-yaml",
                envoy_config(sock, sdir),
                "--disable-hot-restart",
                "--log-level",
                "warning",
            ),
            "copilot のブローカー（Envoy）を常駐させる",
        ),
    )
    return model.BrokerPlan(
        kind="copilot",
        host_ops=host_ops,
        devices=(loopback_proxy_device(cfg, "copilot", COPILOT_PORT),),
        files=(
            model.FilePut(
                "box", MODELS_JSON, "0600", f"{cfg.uid}:{cfg.uid}", content=models_json()
            ),
        ),
        env={"COPILOT_GITHUB_TOKEN": DUMMY_TOKEN},
        readiness=curl_unix_op(sock, IDENTITY_PATH, "copilot のブローカーが応答するか確かめる"),
        stop_ops=(
            stop_unit_op(cfg.repo_id, "copilot"),
            stop_unit_op(cfg.repo_id, "copilot", "refresh"),
            cleanup_op(cfg.repo_id, "copilot"),
        ),
        routes=(
            model.Route(
                "copilot",
                "loopback → proxy デバイス → unix ソケット → ホストの Envoy → githubcopilot.com",
                ("nat", "proxy-only"),
            ),
        ),
    )


# ---- 更新プロセス（ホスト側。`python3 -m box.broker.copilot refresh`） ----


class ExchangeError(RuntimeError):
    """トークンの交換の失敗。メッセージに値を入れない（型名と HTTP の状態だけ）。"""


def exchange(
    long_token: str, opener: Callable[..., Any] = urllib.request.urlopen
) -> tuple[str, int]:
    request = urllib.request.Request(
        TOKEN_URL, headers={**HEADERS, "Authorization": f"Bearer {long_token}"}
    )
    try:
        with opener(request, timeout=EXCHANGE_TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ExchangeError(f"Copilot のトークンを取れない (HTTP {e.code})") from None
    except (OSError, ValueError) as e:
        raise ExchangeError(f"Copilot のトークンを取れない ({type(e).__name__})") from None
    token = raw.get("token") if isinstance(raw, dict) else None
    expires_at = raw.get("expires_at") if isinstance(raw, dict) else None
    if not isinstance(token, str) or not token or not isinstance(expires_at, int):
        raise ExchangeError("Copilot のトークンの応答の形が想定と違う")
    return token, expires_at


def write_sds(path: Path, token: str) -> None:
    """Envoy が監視するディレクトリへ、rename で置く（0600）。"""
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


def refresh_loop(
    state: Path,
    once: bool = False,
    exchange_fn: Callable[[str], tuple[str, int]] = exchange,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> int:
    long_token = re.sub(r"[\r\n]", "", (state / "token").read_text(encoding="utf-8"))
    while True:
        try:
            token, expires_at = exchange_fn(long_token)
            write_sds(state / SDS_NAME, token)
            wait = max(RETRY_SECONDS, expires_at - clock() - REFRESH_MARGIN_SECONDS)
        except ExchangeError as e:
            print(f"copilot の更新に失敗: {e}", file=sys.stderr)
            if once:
                return 1
            wait = RETRY_SECONDS
        if once:
            return 0
        sleep(wait)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="box-copilot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh")
    r.add_argument("--state-dir", required=True)
    r.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        return refresh_loop(Path(args.state_dir), args.once)
    except OSError as e:
        print(f"起動できない: {type(e).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
