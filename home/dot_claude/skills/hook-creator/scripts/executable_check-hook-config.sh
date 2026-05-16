#!/usr/bin/env bash
# check-hook-config.sh — ユーザの hook 設定を解析し、よくある問題を検出する。
#
# - JSON 形式エラー
# - 参照されているスクリプトの実在性
# - matcher の anchored 規則 (Copilot)
# - exit 2 + stderr のみで deny しようとしている疑い (実機検証ベース)
#
# Usage:
#   check-hook-config.sh        # ~/.copilot/hooks/*.json と ~/.claude/settings.json を対象
#   check-hook-config.sh <path> # 任意のパスを対象
set -eu

WARN=0
INFO=0
ERR=0

ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
info() { printf '  \033[36mℹ\033[0m %s\n' "$1"; INFO=$((INFO+1)); }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
err() { printf '  \033[31m✗\033[0m %s\n' "$1"; ERR=$((ERR+1)); }

need_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "jq is required but not installed." >&2
        exit 1
    fi
}

# JSON ファイル単体をチェック
check_copilot_json() {
    local file="$1"
    echo
    echo "--- $file ---"
    if ! jq . "$file" >/dev/null 2>&1; then
        err "JSON parse error"
        return
    fi
    ok "valid JSON"

    # 各 hook entry の command が存在するか
    jq -r '
      .hooks // {} | to_entries[] |
      .key as $event |
      .value[]? |
      [$event, (.matcher // "(any)"), (.bash // .command // .powershell // "")] | @tsv
    ' "$file" 2>/dev/null | while IFS=$'\t' read -r event matcher command; do
        [ -z "$command" ] && continue
        # command の最初のトークン (実行ファイル) を抽出
        # 例: "python /path/to/script.py" → /path/to/script.py
        script_path=$(echo "$command" | awk '{
            # python/bash/sh の引数を実体パスとする
            if ($1 == "python" || $1 == "python3" || $1 == "bash" || $1 == "sh") {
                print $2; exit
            }
            print $1
        }')
        # $HOME 展開
        script_path="${script_path//\$HOME/$HOME}"
        script_path="${script_path//\$\{HOME\}/$HOME}"
        if [ -n "$script_path" ] && [ "${script_path#/}" != "$script_path" ]; then
            if [ ! -e "$script_path" ]; then
                warn "$event ($matcher): script not found — $script_path"
            else
                ok "$event ($matcher): script exists — $script_path"
            fi
        else
            info "$event ($matcher): inline command — $command"
        fi
        # matcher の anchored 確認
        case "$matcher" in
            "(any)") ;;
            "^"*"$") ;;
            *)
                warn "$event: matcher '$matcher' not anchored. Copilot anchors as ^(?:pattern)\$ — write '^${matcher}\$' explicitly to be safe"
                ;;
        esac
    done
}

# Claude の hooks 節を抽出してチェック
check_claude_settings() {
    local file="$1"
    echo
    echo "--- $file ---"
    if ! jq . "$file" >/dev/null 2>&1; then
        err "JSON parse error"
        return
    fi
    ok "valid JSON"

    jq -r '
      .hooks // {} | to_entries[] |
      .key as $event |
      .value[]? |
      .matcher as $matcher |
      .hooks[]? |
      [$event, ($matcher // "(any)"), (.command // .bash // "")] | @tsv
    ' "$file" 2>/dev/null | while IFS=$'\t' read -r event matcher command; do
        [ -z "$command" ] && continue
        script_path=$(echo "$command" | awk '{
            if ($1 == "python" || $1 == "python3" || $1 == "bash" || $1 == "sh") {
                print $2; exit
            }
            print $1
        }')
        script_path="${script_path//\$HOME/$HOME}"
        script_path="${script_path//\$\{HOME\}/$HOME}"
        if [ -n "$script_path" ] && [ "${script_path#/}" != "$script_path" ]; then
            if [ ! -e "$script_path" ]; then
                warn "$event ($matcher): script not found — $script_path"
            else
                ok "$event ($matcher): script exists — $script_path"
            fi
        else
            info "$event ($matcher): inline command — $command"
        fi
    done
}

main() {
    need_jq

    if [ $# -ge 1 ]; then
        # 指定されたファイルを推定で振り分け
        for f in "$@"; do
            case "$f" in
                *settings.json) check_claude_settings "$f" ;;
                *)              check_copilot_json "$f" ;;
            esac
        done
    else
        # デフォルト: 既知の場所を全部チェック
        echo "=== Copilot CLI hooks (~/.copilot/hooks/*.json) ==="
        for f in "$HOME"/.copilot/hooks/*.json; do
            [ -f "$f" ] || continue
            check_copilot_json "$f"
        done
        echo
        echo "=== Claude Code settings (~/.claude/settings.json) ==="
        if [ -f "$HOME/.claude/settings.json" ]; then
            check_claude_settings "$HOME/.claude/settings.json"
        else
            info "no Claude settings.json found"
        fi
    fi

    echo
    echo "=== summary ==="
    echo "  errors  : $ERR"
    echo "  warnings: $WARN"
    echo "  infos   : $INFO"

    [ "$ERR" -eq 0 ]
}

main "$@"
