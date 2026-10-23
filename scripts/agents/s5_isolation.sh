#!/bin/sh
# CHG-0029 W1 S5: 実機の pis で、隔離の worker を通しで確かめるための使い捨てのリポジトリを作る・消す。
# 手順と読み方は docs/change/0029-worktree-isolation.md の「S5 の手順」。
# 使い捨てのリポジトリ ($S5_BASE、既定 ~/src/s5-isolation) だけを触り、本物のリポジトリには書かない。
set -eu

BASE="${S5_BASE:-$HOME/src/s5-isolation}"

usage() {
  cat <<EOF
使い方 (sh scripts/agents/s5_isolation.sh <setup|status|clean>):
  setup   Fence の外のシェルで 1 回。$BASE に使い捨てのリポジトリを作る
          (追跡の変更・未追跡のファイル・ignored のファイルを 1 つずつ持つ。.tmp/ は ignored)
  status  作業ツリー・worktree・ref・記録・patch の状態を表示する (どのシェルでもよい)
  clean   Fence の外のシェルで。$BASE を消す (worktree の登録も消える)
EOF
}

setup() {
  if [ -e "$BASE" ]; then
    echo "既にあります: $BASE (先に clean してください)" >&2
    exit 1
  fi
  mkdir -p "$BASE"
  git init -q -b main "$BASE"
  git -C "$BASE" config user.email s5@example.invalid
  git -C "$BASE" config user.name s5
  printf '.tmp/\nignored/\n' >"$BASE/.gitignore"
  printf 'one\ntwo\nthree\n' >"$BASE/notes.txt"
  git -C "$BASE" add -A
  git -C "$BASE" commit -q -m init
  printf 'one\ntwo-parent\nthree\n' >"$BASE/notes.txt"
  printf 'untracked in the parent\n' >"$BASE/parent-only.txt"
  mkdir -p "$BASE/ignored"
  printf 'ignored data\n' >"$BASE/ignored/data.txt"
  echo "作成しました: $BASE"
  echo "次: cd $BASE && pis を起動し、手順書のプロンプトを貼る"
}

status() {
  if [ ! -d "$BASE/.git" ]; then
    echo "リポジトリがありません: $BASE" >&2
    exit 1
  fi
  echo "--- 親の作業ツリー (変わっていないはず) ---"
  git -C "$BASE" status --short
  echo "notes.txt: $(tr '\n' '|' <"$BASE/notes.txt")"
  echo "--- worktree ---"
  git -C "$BASE" worktree list
  echo "--- refs/pi-agent ---"
  git -C "$BASE" for-each-ref refs/pi-agent
  echo "--- 記録 ---"
  ls -la "$BASE/.tmp/subagents/worktrees" 2>/dev/null || echo "(なし)"
  echo "--- patch ---"
  ls -la "$BASE"/.tmp/subagents/*.patch 2>/dev/null || echo "(なし)"
}

clean() {
  case "$BASE" in
    "$HOME"/src/*) rm -rf "$BASE" ;;
    *)
      echo "安全のため、$HOME/src/ の下以外は消しません: $BASE" >&2
      exit 1
      ;;
  esac
  echo "削除しました: $BASE"
}

case "${1:-}" in
  setup) setup ;;
  status) status ;;
  clean) clean ;;
  *) usage ;;
esac
