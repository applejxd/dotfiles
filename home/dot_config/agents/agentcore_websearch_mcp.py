#!/usr/bin/env python3
"""Bedrock AgentCore Web Search の Gateway へ繋ぐ MCP サーバ (stdio) を起動する。

Gateway の URL はアカウント固有なので環境変数 ``AGENTCORE_GATEWAY_URL`` から読む。
引数はそのまま ``mcp-proxy-for-aws-cli`` へ渡す。

**使えない機では、失敗せずに「ツールの無い空のサーバ」になる** (家など、URL も AWS の認証も無い機で、
起動の失敗が毎回の通知になるのを避ける。認証が無ければ何も起きない)。空になるのは次のとき:

- ``AGENTCORE_GATEWAY_URL`` が無い・``https://`` で始まらない
- pi のサンドボックスの内側 (``PI_HARNESS_BOUNDARY=1``)。内側では AWS の認証情報を使えない
  (ブローカーでの中継は、Bedrock のブローカー (段 U7b) の後。CHG-0037)

see docs/spec/mcp-servers.md#agentcore-web-search
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROXY = "mcp-proxy-for-aws-cli==1.7.0"
URL_ENV = "AGENTCORE_GATEWAY_URL"
BOUNDARY_ENV = "PI_HARNESS_BOUNDARY"
DEFAULT_PROTOCOL = "2025-06-18"
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
        if method == "initialize":
            params = message.get("params") or {}
            reply(
                message,
                {
                    "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agentcore-websearch-idle", "version": "1"},
                },
            )
        elif method in EMPTY_LISTS:
            reply(message, EMPTY_LISTS[method])
        else:
            reply(message, error={"code": -32601, "message": f"method not found: {method}"})
    return 0


def main() -> int:
    url = os.environ.get(URL_ENV, "").strip()
    if not url.startswith("https://"):
        return serve_empty(f"{URL_ENV} が無い。Gateway の MCP URL (https://...) があれば使える")
    if os.environ.get(BOUNDARY_ENV) == "1":
        return serve_empty("サンドボックスの内側では AWS の認証情報を使えない")
    command = ["uvx", PROXY, url, *sys.argv[1:]]
    if os.name == "nt":
        # Windows の execvp は親を先に終わらせ、MCP クライアントとの stdio が切れる
        return subprocess.call(command)
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    sys.exit(main())
