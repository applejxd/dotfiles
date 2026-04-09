#!/bin/bash
# Read existing AGENTS.md content, or report absence
test -f AGENTS.md && cat AGENTS.md || echo "(既存 AGENTS.md なし)"
