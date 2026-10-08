#!/usr/bin/env python3
"""試験用。秘密に見える文字列を返すだけの stdio MCP サーバ（依存なし）。

see docs/spec/pi-harness.md
"""

import json
import sys

TOOL = {
    "name": "echo_secret",
    "description": "Return a line that contains a fake secret.",
    "inputSchema": {"type": "object", "properties": {}},
}


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    if "id" not in msg:
        continue
    if method == "initialize":
        reply(msg["id"], {
            "protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "spike", "version": "0"},
        })
    elif method == "tools/list":
        reply(msg["id"], {"tools": [TOOL]})
    elif method == "tools/call":
        text = "from mcp: SPIKE_TOKEN=mcp-raw-secret"
        content = [{"type": "text", "text": text}]
        reply(msg["id"], {"content": content, "structuredContent": {"line": text}})
    else:
        reply(msg["id"], {})
