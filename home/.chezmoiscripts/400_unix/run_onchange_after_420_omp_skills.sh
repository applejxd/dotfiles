#!/bin/bash

set -euo pipefail

# omp (oh-my-pi) は ~/.claude を設定探索ルートに含むが、**他ツールの
# ユーザ領域 skills の読み込みは opt-in** で、既定は無効。
#   skills.enableClaudeUser = false
# そのため素のままでは ~/.claude/skills の自作 skills が 1 つも見えない。
#
# フラグ (enableClaudeUser) ではなく customDirectories で明示する。
# フラグは ~/.claude 配下の何が有効になるかが読めないが、パス指定なら
# 「どこから来た skill か」が設定を見るだけで分かる。
#
# ★omp 自身が ~/.omp/agent/config.yml を書き換える。ここでは omp の
#   writer を使い、既存の項目を壊さない。追記のみで、既にあるものは触らない。
# see docs/change/0006-pi-harness-trial.md

omp_path="${HOME}/.local/bin/omp"
if [[ ! -x "$omp_path" ]]; then
    if ! omp_path="$(command -v omp 2>/dev/null)"; then
        echo "omp が無いので skills の登録を飛ばします"
        exit 0
    fi
fi

target="${HOME}/.claude/skills"

# 既に入っていれば何もしない。他のエントリは保つ (置き換えない)。
# ★`omp config get --json` は配列ではなく {"key":…, "value":[…]} を返す。
#   配列として読むと必ず解析に失敗し、毎回「未登録」と判定してしまう。
current="$("$omp_path" config get skills.customDirectories --json 2>/dev/null || echo '{}')"
next="$(TARGET="$target" CURRENT="$current" python3 - <<'PY'
import json
import os

target = os.environ["TARGET"]
try:
    parsed = json.loads(os.environ["CURRENT"])
except json.JSONDecodeError:
    parsed = None

# {"key":…, "value":[…]} と素の配列の両方を受ける (出力形式の変化に備える)。
if isinstance(parsed, dict):
    current = parsed.get("value")
else:
    current = parsed
if not isinstance(current, list):
    current = []

if target in current:
    print("")
else:
    print(json.dumps([*current, target]))
PY
)"

if [[ -z "$next" ]]; then
    echo "omp の skills 参照先は登録済みです"
    exit 0
fi

"$omp_path" config set skills.customDirectories "$next" >/dev/null
echo "omp へ ${target} を登録しました"
