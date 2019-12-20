#################
# common config #
#################

COMMON_RC=$HOME/.config/shell/shellrc

if [ -e $COMMON_RC ]; then
    source $COMMON_RC
fi

###############
# Bash plugins #
###############

# powerline
powerline-daemon -q
. /usr/local/lib/python3.7/site-packages/powerline/bindings/bash/powerline.sh

# z: smart completion of the path
. $(brew --prefix)/etc/profile.d/z.sh
alias j='z'

# fzf
[ -f ~/.fzf.bash ] && source ~/.fzf.bash

# 探索コマンド
# cf. https://qiita.com/kamykn/items/aa9920f07487559c0c7e
export FZF_DEFAULT_COMMAND='rg --files --hidden --follow --glob "!.git/*"'
# デフォルト設定. 下に表示, 境界線表示, 高さ指定.
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# オプション設定. bat でプレビュー, 色付き, ファイル名付き, グリッドあり
export FZF_CTRL_T_OPTS='--preview "bat  --color=always --style=header,grid --line-range :100 {}"'

# オプション設定. tree でプレビュー, 色付き, 日本語対応
# 最後のオプション cf. https://wonderwall.hatenablog.com/entry/2017/10/06/063000#--select-1---exit-0
export FZF_ALT_C_OPTS='--preview "tree -C -N {} | head -200" --select-1 --exit-0'
