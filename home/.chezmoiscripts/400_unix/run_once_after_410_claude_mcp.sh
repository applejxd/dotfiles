#!/bin/bash

set -euo pipefail

# バイナリの有無では判定しない。移行済み・途中失敗からの再実行でも設定を保つ。
deepwiki_configured="$(python3 - <<'PY'
import json
from pathlib import Path

try:
    with (Path.home() / ".claude.json").open(encoding="utf-8") as stream:
        config = json.load(stream)
except FileNotFoundError:
    config = {}
print("deepwiki" in config.get("mcpServers", {}))
PY
)"
if [[ "$deepwiki_configured" == "False" ]]; then
    mise_path="${HOME}/.local/bin/mise"
    if [[ ! -x "$mise_path" ]]; then
        mise_path="$(command -v mise)"
    fi
    claude_path="$("$mise_path" -C "$HOME" which claude)"
    "$claude_path" mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp
fi
