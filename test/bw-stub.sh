#!/usr/bin/env bash
# 2 フェーズ bootstrap の検証用に Bitwarden CLI (bw) を置き換えるスタブ。
# 秘密は持たない。値はすべてダミーで、呼ばれた引数を BW_STUB_LOG に残す。
# see docs/spec/testing.md#bootstrap-モード
set -eu

log="${BW_STUB_LOG:-/tmp/bw-stub.log}"
printf '%s\n' "$*" >>"$log"

# chezmoi が足すフラグ (--raw / --session <値> など) は位置引数から外す
positional=()
skip_next=0
for arg in "$@"; do
    if [ "$skip_next" = 1 ]; then
        skip_next=0
        continue
    fi
    case "$arg" in
        --session) skip_next=1 ;;
        --*) ;;
        *) positional+=("$arg") ;;
    esac
done
set -- "${positional[@]}"

fail() {
    echo "bw-stub: $*" >&2
    exit 1
}

case "${1:-}" in
    status)
        printf '%s\n' '{"serverUrl":null,"lastSync":"2026-01-01T00:00:00.000Z","userEmail":"bw-stub@example.invalid","userId":"00000000-0000-0000-0000-000000000000","status":"unlocked"}'
        ;;
    unlock) echo "bw-stub-session" ;;
    lock) echo "Your vault is locked." ;;
    sync) echo "Syncing complete." ;;
    get)
        [ "${2:-}" = "item" ] || fail "unsupported: get ${2:-}"
        case "${3:-}" in
            gitconfig)
                printf '%s\n' '{"object":"item","id":"00000000-0000-0000-0000-000000000001","name":"gitconfig","type":1,"notes":null,"login":{"username":"bw-stub-user","password":null},"fields":[{"name":"email","value":"bw-stub@example.invalid","type":0}]}'
                ;;
            "SOPS age identity personal")
                printf '%s\n' '{"object":"item","id":"00000000-0000-0000-0000-000000000002","name":"SOPS age identity personal","type":2,"notes":"# bw-stub: dummy age identity (not a real key)","fields":[]}'
                ;;
            *) fail "Not found: ${3:-}" ;;
        esac
        ;;
    *) fail "unsupported: $*" ;;
esac
