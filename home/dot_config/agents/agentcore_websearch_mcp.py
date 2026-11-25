#!/usr/bin/env python3
"""Bedrock AgentCore Web Search の Gateway へ繋ぐ MCP サーバ (stdio) を起動する。

Gateway の URL はアカウント固有なので環境変数 ``AGENTCORE_GATEWAY_URL`` から読む。
引数はそのまま ``mcp-proxy-for-aws-cli`` へ渡す。

**使えない機では、失敗せずに「ツールの無い空のサーバ」になる** (家など、URL も AWS の認証も無い機で、
起動の失敗が毎回の通知になるのを避ける。認証が無ければ何も起きない)。空になるのは次のとき:

- ``AGENTCORE_GATEWAY_URL`` が無い・``https://`` で始まらない

空のサーバは、旧式 (``initialize`` の握手。2025-11-25 以前) と、新式 (握手なし・リクエストごとに ``_meta`` で版を運ぶ
2026-07-28) の両方に答える (spec の「dual-era」)。新式は ``server/discover`` と、``_meta`` に版を持つリクエストで始まる。

see docs/spec/mcp-servers.md#agentcore-web-search
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROXY = "mcp-proxy-for-aws-cli==1.7.0"
URL_ENV = "AGENTCORE_GATEWAY_URL"
DEFAULT_PROTOCOL = "2025-11-25"  # 旧式の initialize が版を持たないときの既定 (通常はクライアントの版を返す)
MODERN_VERSIONS = ["2026-07-28"]  # 握手なしで答える版
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
SERVER_INFO = {"name": "agentcore-websearch-idle", "version": "1"}
UNSUPPORTED_VERSION = -32022  # UnsupportedProtocolVersionError (spec が MCP 用に予約した -32020..-32099)
CACHE_TTL_MS = 3_600_000  # 空のまま変わらない。プロセスの寿命の間は再取得が要らない
EMPTY_LISTS = {
    "tools/list": {"tools": []},
    "resources/list": {"resources": []},
    "resources/templates/list": {"resourceTemplates": []},
    "prompts/list": {"prompts": []},
    "ping": {},
}


def reply(message: dict, result: dict | None = None, error: dict | None = None) -> None:
    body = {"jsonrpc": "2.0", "id": message["id"]}
    body.update({"error": error} if error is not None else {"result": result})
    sys.stdout.write(json.dumps(body, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve_modern(message: dict, method: str | None, requested: object) -> None:
    """新式 (2026-07-28) のリクエストに答える。握手も状態も無く、リクエストごとに完結する。"""
    if requested is not None and requested not in MODERN_VERSIONS:
        reply(
            message,
            error={
                "code": UNSUPPORTED_VERSION,
                "message": "Unsupported protocol version",
                "data": {"supported": MODERN_VERSIONS, "requested": requested},
            },
        )
        return
    common = {
        "resultType": "complete",
        "_meta": {META_SERVER_INFO: SERVER_INFO},
        "ttlMs": CACHE_TTL_MS,
        "cacheScope": "private",
    }
    if method == "server/discover":
        reply(message, {**common, "supportedVersions": MODERN_VERSIONS, "capabilities": {"tools": {}}})
    elif method in EMPTY_LISTS and method != "ping":  # ping は 2026-07-28 で廃止
        reply(message, {**EMPTY_LISTS[method], **common})
    else:
        reply(message, error={"code": -32601, "message": f"method not found: {method}"})


def serve_empty(reason: str) -> int:
    """ツールの無い MCP サーバ (stdio。1 行 1 メッセージの JSON-RPC)。stdin が閉じたら 0 で終わる。"""
    print(f"agentcore-websearch: ツール無しで待機します ({reason})", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or "id" not in message:
            continue  # 通知 (initialized など) には答えない
        method = message.get("method")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        if method == "initialize":
            reply(
                message,
                {
                    "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            )
        elif method == "server/discover" or META_VERSION in meta:
            serve_modern(message, method, meta.get(META_VERSION))
        elif method in EMPTY_LISTS:
            reply(message, EMPTY_LISTS[method])
        else:
            reply(message, error={"code": -32601, "message": f"method not found: {method}"})
    return 0


def main() -> int:
    url = os.environ.get(URL_ENV, "").strip()
    if not url.startswith("https://"):
        return serve_empty(f"{URL_ENV} が無い。Gateway の MCP URL (https://...) があれば使える")
    command = ["uvx", PROXY, url, *sys.argv[1:]]
    if os.name == "nt":
        # Windows の execvp は親を先に終わらせ、MCP クライアントとの stdio が切れる
        return subprocess.call(command)
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    sys.exit(main())
