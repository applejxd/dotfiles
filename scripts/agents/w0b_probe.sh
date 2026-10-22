#!/bin/sh
# CHG-0029 W0b: Fence の下で、linked worktree を cwd にした子の書込境界を確かめる使い捨ての検査。
# 手順と読み方は docs/change/0029-worktree-isolation.md の「W0b の手順」。
# 使い捨てのリポジトリ ($W0B_BASE、既定 ~/worktrees/w0b) だけを触り、本物のリポジトリには書かない。
set -eu

BASE="${W0B_BASE:-$HOME/worktrees/w0b}"

usage() {
  cat <<EOF
使い方 (sh scripts/agents/w0b_probe.sh <setup|probe|clean>):
  setup  Fence の外のシェルで 1 回。$BASE に使い捨ての main リポジトリと worktree wt1・wt2 を作る
  probe  Fence の下 (cd $BASE/wt1 して pis を起動し、その中) で実行。各操作が通るか・拒否されるかを表示する
  clean  Fence の外のシェルで。$BASE を消す
EOF
}

setup() {
  if [ -e "$BASE" ]; then
    echo "既にあります: $BASE (先に clean してください)" >&2
    exit 1
  fi
  mkdir -p "$BASE"
  main="$BASE/main"
  git init -q -b main "$main"
  git -C "$main" config user.email w0b@example.invalid
  git -C "$main" config user.name w0b
  printf 'a\n' >"$main/a.txt"
  git -C "$main" add a.txt
  git -C "$main" commit -q -m init
  git -C "$main" worktree add -q --detach "$BASE/wt1" HEAD
  git -C "$main" worktree add -q --detach "$BASE/wt2" HEAD
  echo "作成しました。次: cd $BASE/wt1 && pis を起動し、その中で sh <このスクリプト> probe を実行する"
}

# 名前・期待 (通る / 拒否) ・コマンドを受け取り、結果を 1 行で出す
check() {
  name="$1"
  expect="$2"
  shift 2
  if out=$("$@" 2>&1); then
    res="通った"
  else
    res="拒否された"
  fi
  msg=$(printf '%s' "$out" | head -c 120 | tr '\n' ' ')
  printf '%-44s 期待=%-6s 結果=%s  %s\n' "$name" "$expect" "$res" "$msg"
}

probe() {
  here=$(pwd)
  gitdir=$(git rev-parse --git-common-dir)
  main=$(cd "$gitdir/.." && pwd)
  sib="$(dirname "$here")/wt2"
  echo "cwd=$here"
  echo "main=$main"
  echo "sibling=$sib"
  echo "--- E1: worktree の中の通常の作業 (通ってほしい) ---"
  check "git status" 通る git status --short
  check "ファイルの編集" 通る sh -c 'echo x >>a.txt'
  check "git add (.git/worktrees/<id>/index への書き込み)" 通る git add a.txt
  check "一時 index で read-tree と add -A" 通る sh -c 'GIT_INDEX_FILE=.w0b-idx git read-tree HEAD && GIT_INDEX_FILE=.w0b-idx git add -A'
  tree=$(GIT_INDEX_FILE=.w0b-idx git write-tree 2>/dev/null || true)
  check "write-tree (共有 objects への書き込み)" 通る test -n "$tree"
  commit=$(git commit-tree "$tree" -p HEAD -m w0b 2>/dev/null || true)
  check "commit-tree" 通る test -n "$commit"
  check "update-ref refs/pi-agent/w0b" 通る git update-ref refs/pi-agent/w0b "$commit"
  echo "--- E2: 境界の外 (拒否されてほしい。通れば隔離の効果が限られる) ---"
  check "兄弟 worktree への書き込み" 拒否 sh -c "echo x >'$sib/e2.txt'"
  check "本体の作業ツリーへの書き込み" 拒否 sh -c "echo x >'$main/e2.txt'"
  check "本体 .git/hooks への書き込み" 拒否 sh -c "echo x >'$main/.git/hooks/w0b-test'"
  check "本体 .git/config の変更" 拒否 git config --file "$main/.git/config" w0b.test 1
  check "update-ref refs/heads/w0b-hijack" 拒否 git update-ref refs/heads/w0b-hijack HEAD
  check "ホーム直下への書き込み (対照)" 拒否 sh -c "echo x >'$HOME/w0b-outside'"
  echo "--- 後始末 (このシェルから消せる範囲) ---"
  rm -f .w0b-idx a.txt.w0b "$sib/e2.txt" "$main/e2.txt" "$main/.git/hooks/w0b-test" "$HOME/w0b-outside" 2>/dev/null || true
  git update-ref -d refs/pi-agent/w0b 2>/dev/null || true
  git update-ref -d refs/heads/w0b-hijack 2>/dev/null || true
  git config --file "$main/.git/config" --unset w0b.test 2>/dev/null || true
  git checkout -q -- a.txt 2>/dev/null || true
  echo "完了。結果の表を貼ってください。(a.txt の編集と index は clean で消えます)"
}

clean() {
  case "$BASE" in
    "$HOME"/worktrees/*) rm -rf "$BASE" ;;
    *)
      echo "安全のため、$HOME/worktrees/ の下以外は消しません: $BASE" >&2
      exit 1
      ;;
  esac
  echo "削除しました: $BASE"
}

case "${1:-}" in
  setup) setup ;;
  probe) probe ;;
  clean) clean ;;
  *) usage ;;
esac
