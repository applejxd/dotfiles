#!/bin/bash

set -euo pipefail

# omp (oh-my-pi) から、このリポジトリが既に持っている Claude 側の資産を使う。
#
# ★`enabledProviders` の既定は空で、**他ツールのユーザ領域は 1 つも読まれない**。
#   `~/.claude.json` の mcpServers も、`~/.claude/commands/` もここで閉じている。
#   (プロジェクト直下の .claude/ は既定で読まれる。閉じているのはユーザ領域だけ)
#
# `*` / `all` ではなく `claude` だけを入れる。codex / gemini / opencode /
# cursor / windsurf / github / claude-plugins まで一度に開くと、どの定義が
# 採用されたか追えなくなる。
#
# ★omp 自身が ~/.omp/agent/config.yml を書き換える。ここでは omp の writer を
#   使い、既存の項目を壊さない。
# see docs/change/0006-pi-harness-trial.md

omp_path="${HOME}/.local/bin/omp"
if [[ ! -x "$omp_path" ]]; then
    if ! omp_path="$(command -v omp 2>/dev/null)"; then
        echo "omp が無いので Claude 資産の接続を飛ばします"
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# (A) 配列への追記。他のエントリは保つ (置き換えない)
# ---------------------------------------------------------------------------
# ★`omp config get --json` は配列ではなく {"key":…, "value":[…]} を返す。
#   配列として読むと必ず解析に失敗し、毎回「未登録」と判定してしまう。
current="$("$omp_path" config get enabledProviders --json 2>/dev/null || echo '{}')"
next="$(CURRENT="$current" python3 - <<'PY'
import json
import os

try:
    parsed = json.loads(os.environ["CURRENT"])
except json.JSONDecodeError:
    parsed = None

# {"key":…, "value":[…]} と素の配列の両方を受ける (出力形式の変化に備える)。
current = parsed.get("value") if isinstance(parsed, dict) else parsed
if not isinstance(current, list):
    current = []

# enabledProviders は素の文字列のほかに path スコープ付きの dict も取る。
# 文字列だけを見る (dict は "どこでも有効" ではないので判定に使えない)。
names = {item for item in current if isinstance(item, str)}

# `*` / `all` は全ソースを開く指定なので、既に claude を含んでいる。
if names & {"claude", "*", "all"}:
    print("")
else:
    print(json.dumps([*current, "claude"]))
PY
)"

if [[ -z "$next" ]]; then
    echo "omp の claude ソースは有効化済みです"
else
    "$omp_path" config set enabledProviders "$next" >/dev/null
    echo "omp へ claude ソースを登録しました (~/.claude.json の MCP 等)"
fi

# ---------------------------------------------------------------------------
# (B) 真偽値の初期値。一度だけ置き、以後はユーザのものとして触らない
# ---------------------------------------------------------------------------
# 配列と違い真偽値は「未設定」と「既定値と同じ値を明示した」を区別できない
# (`omp config get` は実効値を返す)。毎回入れ直すと、UI や `omp config set` で
# 意図して戻した設定を次の `chezmoi apply` が黙って覆す。
#
# 置いた鍵を控えておき、2 回目以降は触らない。omp が無い回は控えないので、
# 導入が後になっても取りこぼさない (run_once_ だとここを取りこぼす)。
marker="${HOME}/.omp/agent/.chezmoi-seeded"

seed() {
    local key="$1" value="$2" reason="$3"
    if [[ -f "$marker" ]] && grep -qxF "$key" "$marker"; then
        return 0
    fi
    "$omp_path" config set "$key" "$value" >/dev/null
    mkdir -p "$(dirname "$marker")"
    printf '%s\n' "$key" >>"$marker"
    echo "omp の ${key} を ${value} にしました (${reason}。以後は上書きしません)"
}

# ~/.claude/commands/*.md を /ask /commit などとして出す。
seed commands.enableClaudeUser true "既存の Claude コマンドを使う"

# bash を read / grep / glob / edit / write / hub へ振り替える。**実行の可否は
# 決めない**ので permission ではない。omp 内蔵の既定パターンが common.toml の
# 誘導規則とほぼ同じ内容なので、パターンを書かずに他の CLI と挙動が揃う。
seed bashInterceptor.enabled true "bash を専用ツールへ誘導する"
