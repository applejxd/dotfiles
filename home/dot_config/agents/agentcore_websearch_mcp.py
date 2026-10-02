#!/usr/bin/env python3
"""Bedrock AgentCore Web Search の Gateway へ繋ぐ MCP サーバ (stdio) を起動する。

Gateway の URL はアカウント固有なので環境変数 ``AGENTCORE_GATEWAY_URL`` から読む。
引数はそのまま ``mcp-proxy-for-aws-cli`` へ渡す。
see docs/spec/agent-config-generation.md#agentcore-web-search
"""

from __future__ import annotations

import os
import subprocess
import sys

PROXY = "mcp-proxy-for-aws-cli==1.7.0"
URL_ENV = "AGENTCORE_GATEWAY_URL"


def main() -> int:
    url = os.environ.get(URL_ENV, "").strip()
    if not url.startswith("https://"):
        print(
            f"{URL_ENV} に Gateway の MCP URL (https://...) を設定してから起動する",
            file=sys.stderr,
        )
        return 1
    command = ["uvx", PROXY, url, *sys.argv[1:]]
    if os.name == "nt":
        # Windows の execvp は親を先に終わらせ、MCP クライアントとの stdio が切れる
        return subprocess.call(command)
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    sys.exit(main())
