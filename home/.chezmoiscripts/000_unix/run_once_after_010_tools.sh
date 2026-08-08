#!/bin/bash

set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

if ! command -v copilot >/dev/null 2>&1; then
    curl -fsSL https://gh.io/copilot-install | bash
fi

if ! command -v codex >/dev/null 2>&1; then
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
fi

if ! command -v claude >/dev/null 2>&1; then
    curl -fsSL https://claude.ai/install.sh | bash
    # deepwiki MCP
    claude mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp
fi
