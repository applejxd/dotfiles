#!/usr/bin/env bash
# CHG-0019 段 4: 別名のツールを実際のモデルで使い、圧縮まで 1 周させる。
# 引数: モデル（既定 github-copilot/claude-sonnet-5.5）。モデルの利用枠を使う。
# see docs/research/agents/pi-harness-spike.md
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MODEL=${1:-github-copilot/claude-sonnet-5.5}
export SPIKE_POLICY="$HERE/policy.py"

setup_project() {
  dir=$1
  mkdir -p "$dir"
  cat > "$dir/calc.py" <<'PY'
def average(values):
    """Return the arithmetic mean of a non-empty list."""
    return sum(values) / (len(values) + 1)


def clamp(value, low, high):
    return max(low, min(value, high))
PY
  cat > "$dir/test_calc.py" <<'PY'
from calc import average, clamp

assert average([2, 4, 6]) == 4, average([2, 4, 6])
assert clamp(5, 0, 3) == 3
print("ok")
PY
  # 小さなセッションでも圧縮できるよう、直近を残さない（--approve で読ませる）
  mkdir -p "$dir/.pi"
  echo '{"compaction": {"keepRecentTokens": 1}}' > "$dir/.pi/settings.json"
  git -C "$dir" init -q
  git -C "$dir" add -A
  git -C "$dir" -c user.name=spike -c user.email=spike@example.invalid commit -qm init
}

summarize() {
  label=$1
  dir=$2
  echo "=== $label"
  (cd "$dir" && python3 test_calc.py 2>&1 | tail -1) || true
  python3 - "$dir/sessions" <<'PY'
import collections, glob, json, sys
calls = collections.Counter()
errors = []
for path in glob.glob(sys.argv[1] + "/**/*.jsonl", recursive=True):
    for line in open(path):
        e = json.loads(line)
        if e.get("type") == "compaction":
            d = e.get("details") or {}
            print("compaction details:", json.dumps(d, ensure_ascii=False))
            print("summary has file tags:", "<read-files>" in e.get("summary", "") or "<modified-files>" in e.get("summary", ""))
        m = e.get("message") or {}
        if m.get("role") == "assistant":
            for b in m.get("content", []):
                if b.get("type") == "toolCall":
                    calls[b["name"]] += 1
        if m.get("role") == "toolResult" and m.get("isError"):
            text = "".join(c.get("text", "") for c in m.get("content", []))
            errors.append(f'{m.get("toolName")}: {text[:160]}')
print("tool calls:", dict(calls))
print("tool errors:", errors)
PY
  echo "--- final answer"
  tail -5 "$dir/out.txt"
}

TASK='test_calc.py が失敗する。原因を調べて calc.py を直し、python3 test_calc.py を実行して通ることを確かめて。'
ASK='圧縮の前に、どのファイルを読み、どのファイルを変更したか、パスだけを挙げて。'

for variant in ${VARIANTS:-harness builtin}; do
  dir=$(mktemp -d)
  setup_project "$dir"
  if [ "$variant" = harness ]; then
    flags=(-nbt -ne -e "$HERE/harness" -e "$HERE/compact.ts")
  else
    flags=(-ne -e "$HERE/compact.ts")
  fi
  (cd "$dir" && SPIKE_RENAME=1 timeout 600 pi -p --approve --session-dir "$dir/sessions" --model "$MODEL" \
    "${flags[@]}" "$TASK" /spike-compact "$ASK" > "$dir/out.txt" 2>&1) || echo "pi exit=$?"
  summarize "$variant ($MODEL)" "$dir"
done
