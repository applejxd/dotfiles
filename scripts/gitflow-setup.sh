#!/bin/sh
# gitflow-lite (main / develop / feature。squash) の設定を、このリポジトリで作る・取り込む。
# サンドボックスの外 (普通のシェル) で、利用者が実行する (.git/config を書くため)。
# 新しい clone・別のマシンでは、同じスクリプトで共有の .gitflow を取り込む。何度実行しても同じ結果になる。
# see docs/spec/development.md#ブランチモデルgitflow-lite
set -eu

if ! command -v git-flow >/dev/null 2>&1; then
	echo "git-flow が無い。mise install で入れる (github:gittower/git-flow-next)" >&2
	exit 1
fi
cd "$(git rev-parse --show-toplevel)"

# 旧実装 (nvie / avh) の名残のキー。git-flow-next の設定と混ざり、安全な構成の検査で拒否されるので消す。
# ここで消せるのはこのリポジトリのもの。グローバルの ~/.gitconfig に同じキー (gitflow.branch.master) が
# 残っていても検査で拒否される。そのキーは dot_config/git/config.tmpl から消してあるので、chezmoi apply で反映する
for key in master develop feature release hotfix support versiontag; do
	git config --unset-all "gitflow.branch.$key" 2>/dev/null || true
	git config --unset-all "gitflow.prefix.$key" 2>/dev/null || true
done
if git config --global --get gitflow.branch.master >/dev/null 2>&1; then
	echo "注意: ~/.gitconfig に gitflow.branch.master が残っている。chezmoi apply で ~/.gitconfig を更新する" >&2
fi

if [ -f .gitflow ]; then
	# 共有の設定がある: 取り込むだけ
	git flow config sync
	echo "取り込んだ: .gitflow"
	exit 0
fi

# 初回: develop・設定・共有ファイルを作る
git flow init --preset=classic --defaults --shared
for topic in release hotfix support bugfix; do
	git flow config delete topic "$topic" --shared
done
git flow config edit topic feature --upstream-strategy=squash --shared
# feature の worktree は、本体の .tmp/worktrees/ の下 (本体で動く pi が書ける範囲)
git config -f .gitflow gitflow.worktreePath '.tmp/worktrees/{{ branchName }}'
git flow config sync

echo "作った: .gitflow (コミットする)。develop を push する場合は、利用者が行う"
echo "確認: git flow config list"
