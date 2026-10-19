#!/usr/bin/env bash
# 圧縮の実機の試験を、モデルと思考レベルの組で順に回す。結果の RESULT 行だけを集める。
set -u
cd "$(dirname "$0")/../.." || exit 1
run() {
  uv run --with pytest --with pyyaml --no-project python3 scripts/pi-harness-spike/compact-real.py "$@" 2>&1
}
for combo in \
  "github-copilot/claude-sonnet-5.5 medium" \
  "github-copilot/claude-sonnet-5.5 high" \
  "github-copilot/claude-sonnet-5.5 low" \
  "github-copilot/claude-sonnet-5.5 off" \
  "github-copilot/claude-haiku-5.5 medium" \
  "github-copilot/gemini-3.8-flash medium" \
  "github-copilot/grok-4.7 medium"; do
  # shellcheck disable=SC2086
  run $combo
done
echo "--- 2 回圧縮 (前の要約を引き継ぐ経路) ---"
COMPACTS=2 run github-copilot/claude-sonnet-5.5 medium 3
