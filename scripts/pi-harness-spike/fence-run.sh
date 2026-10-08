#!/usr/bin/env bash
# CHG-0019 段 4: pi をプロセスごと Fence で包む。保存・再開・制御ファイルの保護・実際のモデルとの通信を見る。
# F3 だけ実際のモデル（既定 github-copilot/claude-haiku-5.5）を呼ぶ。
# see docs/research/agents/pi-harness-spike.md
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MODEL=${1:-github-copilot/claude-haiku-5.5}
# 認証の写しを置くので、リポジトリの外に作る
mkdir -p "$HOME/.cache"
WORK=$(mktemp -d "$HOME/.cache/pi-spike-fence.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/agent/sessions" "$WORK/proj" "$WORK/tmp" "$WORK/outside"
echo '{}' > "$WORK/agent/settings.json"
export SPIKE_POLICY="$HERE/policy.py" SPIKE_RENAME=1

# 境界: 読めるのは道具の置き場・ハーネス・作業ツリー・agent 置き場。書けるのは作業ツリー・agent 置き場・
# 一時ディレクトリ。pi は設定と認証を読むときにも隣に .lock を mkdir するので、agent 置き場は書ける必要がある
# （試作の結果 F1 の 1 回目）。設定・拡張・導入物は denyWrite で守る
boundary() {
  agent=$1
  for p in settings.json trust.json mcp.json; do [ -e "$agent/$p" ] || echo '{}' > "$agent/$p"; done
  mkdir -p "$agent/extensions"
  python3 - "$WORK" "$HERE" "$HOME" "$agent" > "$WORK/fence.json" <<'PY'
import json, sys
work, here, home, agent = sys.argv[1:]
print(json.dumps({
    "network": {"allowedDomains": [
        "api.githubcopilot.com", "*.githubcopilot.com", "api.github.com", "github.com",
    ]},
    "filesystem": {
        "defaultDenyRead": True,
        "allowRead": [
            f"{home}/.pi/agent/install", f"{home}/.pi/agent/bin", f"{home}/bin",
            f"{home}/.local/share/mise", here, f"{work}/proj", f"{work}/tmp", agent,
        ],
        "allowWrite": [f"{work}/proj", f"{work}/tmp", agent],
        "denyWrite": [
            here,
            *(f"{agent}/{p}" for p in (
                "settings.json", "trust.json", "mcp.json", "extensions", "install", "bin",
            )),
        ],
    },
    "allowPty": True,
}))
PY
}

in_fence() {
  (cd "$WORK/proj" && TMPDIR="$WORK/tmp" timeout 180 fence --settings "$WORK/fence.json" -- "$@")
}

# 境界の内側から外へ手を伸ばすスクリプト
cat > "$WORK/proj/escape.py" <<PY
import os
def attempt(label, fn):
    try:
        fn()
        print(f"{label}: できた")
    except Exception as e:
        print(f"{label}: できない ({type(e).__name__})")
attempt("設定を書く", lambda: open("$WORK/agent/settings.json", "a").write("x"))
attempt("拡張を置く", lambda: open("$WORK/agent/extensions/evil.ts", "w").write("x"))
attempt("ハーネスを書く", lambda: open("$HERE/harness/index.ts", "a").write(""))
attempt("作業ツリーの外へ書く", lambda: open("$WORK/outside/x", "w").write("x"))
attempt("~/.ssh を読む", lambda: os.listdir(os.path.expanduser("~/.ssh")))
attempt("本物の auth.json を読む", lambda: open(os.path.expanduser("~/.pi/agent/auth.json")).read())
attempt("作業ツリーに書く", lambda: open("inside.txt", "w").write("x"))
PY

echo "=== F0 Fence の設定が壊れているとき"
echo '{ broken' > "$WORK/bad.json"
set +e
(cd "$WORK/proj" && fence --settings "$WORK/bad.json" -- true >/dev/null 2>&1)
echo "exit=$?"
set -e

boundary "$WORK/agent"
export PI_CODING_AGENT_DIR="$WORK/agent"
echo "=== F1 境界の内側で起動し、セッションを保存する（偽のモデル）"
set +e
FAUX_TOOL_CALLS='[{"name":"guarded_bash","args":{"command":"python3 escape.py"}}]' \
  in_fence pi -p --model faux/spike -nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts" "first" 2>&1
echo "exit=$?"
set -e
echo "セッションのファイル: $(find "$WORK/agent/sessions" -name '*.jsonl' | wc -l) 件"
echo "設定: $(cat "$WORK/agent/settings.json")、作業ツリーの外: $(find "$WORK/outside" -mindepth 1 | wc -l) 件"

echo "=== F2 境界の外で同じセッションを再開する（-c）"
(cd "$WORK/proj" && FAUX_TOOL_CALLS='[]' pi -p -c --model faux/spike -nbt -ne -e "$HERE/harness" -e "$HERE/faux.ts" "second" 2>&1)
f=$(find "$WORK/agent/sessions" -name '*.jsonl' | head -1)
echo "セッションの利用者の発言: $(python3 -c "
import json,sys
print([c['text'] for l in open('$f') for e in [json.loads(l)] if (e.get('message') or {}).get('role')=='user' for c in e['message']['content'] if c.get('type')=='text'])")"

# 本物の agent 置き場は境界に入れない。Fence の denyWrite は無いパスに効かず、内側で extensions/ などを
# 作られると、境界の外の通常の pi が読んでしまう。境界用の agent 置き場を起動ごとに作り、認証・モデルの一覧・設定を写す
echo "=== F3 境界の内側から実際のモデル（$MODEL）を呼ぶ。境界用の agent 置き場に写す"
SBX="$WORK/sbx-agent"
mkdir -p "$SBX"
cp "$HOME/.pi/agent/auth.json" "$HOME/.pi/agent/models-store.json" "$HOME/.pi/agent/settings.json" "$SBX/"
boundary "$SBX"
auth="$HOME/.pi/agent/auth.json"
before=$(stat -c %Y "$auth")
set +e
PI_CODING_AGENT_DIR="$SBX" in_fence pi -p --no-session --model "$MODEL" -nbt -ne -e "$HERE/harness" \
  "1+1 の答えを数字だけで返して" 2>&1 | tail -3
echo "exit=$?"
set -e
echo "本物の auth.json の更新: $([ "$(stat -c %Y "$auth")" = "$before" ] && echo なし || echo あり)"
echo "写しの auth.json の更新: $(cmp -s "$auth" "$SBX/auth.json" && echo なし || echo あり)"
