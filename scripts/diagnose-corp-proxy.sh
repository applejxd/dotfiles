#!/bin/sh
set -eu

# 社内プロキシ必須の PC で、境界（Fence / srt）の通信が通らない原因を切り分ける。
# 実行: sh scripts/diagnose-corp-proxy.sh [許可ドメイン] [許可外ドメイン]
# 出力は貼り付けて共有できる (プロキシの認証情報は伏せる)。何も書き換えない。
# see docs/research/agents/corp-proxy-boundary.md

ALLOWED="${1:-github.com}"
DENIED="${2:-example.com}"
T=15
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mask() { sed -E 's#(//)[^@/]*@#\1***@#'; }
say() { printf '\n== %s\n' "$1"; }

# --- 0. 前提 ---
say "0. プロキシ設定 (値は認証情報を伏せて表示)"
for v in HTTP_PROXY http_proxy HTTPS_PROXY https_proxy NO_PROXY no_proxy ALL_PROXY all_proxy; do
  eval "val=\${$v:-}"
  [ -n "$val" ] && printf '%s=%s\n' "$v" "$(printf '%s' "$val" | mask)"
done
PROXY="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}"
if [ -z "$PROXY" ]; then
  echo "プロキシ変数なし。この診断は社内プロキシ環境向け"
else
  case "$PROXY" in
    http://*) echo "scheme: http (Fence の upstreamProxy が使える形)" ;;
    https://*) echo "scheme: https (★Fence の upstreamProxy は http:// のみ対応)" ;;
    *) echo "scheme: 不明な形 ($(printf '%s' "$PROXY" | cut -d: -f1))" ;;
  esac
  case "$PROXY" in *@*) echo "認証: URL に埋め込みあり" ;; *) echo "認証: URL に無し (NTLM / Kerberos などの可能性は別途)" ;; esac
fi

say "1. 道具の版"
FENCE="$(command -v fence 2>/dev/null || true)"
# PATH の srt は別物 (字幕ツール) のことがある。--settings を持つ Anthropic 版だけ採る
SRT=""
for c in "$(command -v srt 2>/dev/null || true)" \
  "$HOME"/.local/share/mise/installs/npm-anthropic-ai-sandbox-runtime/*/node_modules/.bin/srt; do
  if [ -x "$c" ] && "$c" --help 2>&1 | grep -q -e '--settings'; then SRT="$c"; break; fi
done
printf 'fence: %s\n' "${FENCE:-なし}"
[ -n "$FENCE" ] && "$FENCE" --version 2>&1 | sed -n 2p
printf 'srt (Anthropic 版): %s\n' "${SRT:-なし}"

# --- 2. ホストから ---
say "2. ホストから ($ALLOWED)"
code="$(curl -s -m "$T" -o /dev/null -w '%{http_code}' "https://$ALLOWED" 2>&1 || true)"
echo "プロキシ変数を使う: $code"
code="$(env -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy curl -s -m "$T" -o /dev/null -w '%{http_code}' "https://$ALLOWED" 2>&1 || true)"
echo "プロキシ変数を外す: $code (000 なら社内プロキシ必須)"

# 境界内から curl で試す。$1=道具 $2=設定 $3=ホスト
inside() {
  case "$1" in
    fence) "$FENCE" -d --settings "$2" -- curl -s -m "$T" -o /dev/null -w '%{http_code}' "https://$3" 2>"$WORK/err" || true ;;
    srt) "$SRT" --settings "$2" -c "curl -s -m $T -o /dev/null -w '%{http_code}' https://$3" 2>"$WORK/err" || true ;;
  esac
}

# --- 3. Fence: 許可リストのみ (現状の ocs / pis の形) ---
if [ -n "$FENCE" ]; then
  say "3. Fence 許可リストのみ (現状の形)。許可=$ALLOWED"
  cat >"$WORK/f1.json" <<EOF
{"network":{"allowedDomains":["$ALLOWED"]},"filesystem":{"allowWrite":[]}}
EOF
  printf '許可済み: %s\n' "$(inside fence "$WORK/f1.json" "$ALLOWED")"
  echo "-- Fence のログ (dial / CONNECT の行だけ):"
  grep -E '^\[fence:(http|filter)\]' "$WORK/err" | mask | head -8 || true

  # --- 4. Fence: 上流プロキシ (許可リストは無効になる。仕組みの確認だけ) ---
  if [ -n "$PROXY" ]; then
    say "4. Fence upstreamProxy (全通信を社内プロキシへ。仕組みの確認用)"
    cat >"$WORK/f2.json" <<EOF
{"network":{"allowedDomains":[],"defaultAction":"proxy","upstreamProxy":"$PROXY"},"filesystem":{"allowWrite":[]}}
EOF
    printf '許可済み相当: %s\n' "$(inside fence "$WORK/f2.json" "$ALLOWED")"
    grep -E '^\[fence:(http|filter)\]' "$WORK/err" | mask | head -5 || true
  fi
fi

# --- 5. srt: parentProxy (環境変数から拾う) ---
if [ -n "$SRT" ]; then
  say "5. srt 許可リスト + 環境変数のプロキシ"
  cat >"$WORK/s1.json" <<EOF
{"network":{"allowedDomains":["$ALLOWED"],"deniedDomains":[]},"filesystem":{"denyRead":[],"allowWrite":[],"denyWrite":[]}}
EOF
  printf '許可済み (%s): %s\n' "$ALLOWED" "$(inside srt "$WORK/s1.json" "$ALLOWED")"
  printf '許可外 (%s): %s (000 / 403 が期待)\n' "$DENIED" "$(inside srt "$WORK/s1.json" "$DENIED")"
fi

say "読み方"
cat <<'EOF'
- 2 でプロキシ変数を外すと 000、使うと 200 → 社内プロキシ必須
- 3 が 000 で Fence のログに dial 失敗 → 許可済み通信を Fence が直接つないでいる (仮説どおり)
- 4 が 200 → upstreamProxy の仕組みと URL の形式は使える (ただし許可リストは効かない)
- 5 の許可済みが 200・許可外が 000/403 → srt なら許可リストを保ったまま通る
EOF
