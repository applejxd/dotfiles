#################
# common config #
#################

COMMON_RC=$HOME/.config/shell/shellrc.sh

if [ -e $COMMON_RC ]; then
    source $COMMON_RC
fi

##############
# zsh proper #
##############

# Emacs mode
bindkey -e

# zsh completion
autoload -U compinit
compinit

# cd 補完
# cf. https://qiita.com/yaotti/items/157ff0a46736ec793a91
setopt auto_cd
cdpath=(.. ~)
function chpwd() {
    ls
}

# 自動 pushd & 履歴は残さない
setopt auto_pushd
setopt pushd_ignore_dups

# for iTerm2
test -e "${HOME}/.iterm2_shell_integration.zsh" && source "${HOME}/.iterm2_shell_integration.zsh"

###############
# zsh history #
###############

# cf. https://yk5656.hatenadiary.org/entry/20160203/1461325853

export HISTFILE=$HOME/.zsh_history

export HISTSIZE=100000
export SAVEHIST=100000

setopt share_history

setopt hist_ignore_dups
setopt hist_ignore_all_dups
setopt hist_find_no_dups

setopt hist_save_no_dups
setopt hist_reduce_blanks
setopt hist_ignore_space

###############
# zsh plugins #
###############

'z' command
. /usr/local/etc/profile.d/z.sh
alias j="z"

# # powerline
# powerline-daemon -q
# . /usr/local/lib/python3.7/site-packages/powerline/bindings/zsh/powerline.zsh

#########
# zplug #
#########

# zplug settings
export ZPLUG_HOME=/usr/local/opt/zplug
source $ZPLUG_HOME/init.zsh

# fish-like auto completion
zplug "zsh-users/zsh-autosuggestions"
# completion for non-defalut commands
zplug "zsh-users/zsh-completions"
# syntax-highlighting to command-line (compinit 以降)
zplug "zsh-users/zsh-syntax-highlighting", defer:2

# git, oh-my-zsh plugin
zplug "plugins/git", from:oh-my-zsh

# enhance 'cd' command
zplug "b4b4r07/enhancd", use:init.sh
export ENHANCD_COMMAND=ecd

# docker
zplug 'felixr/docker-zsh-completion'

# zsh theme 'powerlevel9k'
zplug "bhilburn/powerlevel9k", use:powerlevel9k.zsh-theme

# Apply Nerd-Font
POWERLEVEL9K_MODE='nerdfont-complete'

# Double-Lined Prompt
POWERLEVEL9K_PROMPT_ON_NEWLINE=true
POWERLEVEL9K_RPROMPT_ON_NEWLINE=true
# Turned Arrow
POWERLEVEL9K_MULTILINE_FIRST_PROMPT_PREFIX="%F{blue}\u256D\u2500%F{white}"
POWERLEVEL9K_MULTILINE_LAST_PROMPT_PREFIX="%F{blue}\u2570\uf460%F{white} "
# # Adding Newline Before Each Prompt
# POWERLEVEL9K_PROMPT_ADD_NEWLINE=true

# Segment contents
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(os_icon dir vcs)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(command_execution_time status time ram)

# Install plugins if there are plugins that have not been installed
if ! zplug check --verbose; then
    printf "Install? [y/N]: "
    if read -q; then
        echo
        zplug install
    fi
fi

# Then, source plugins and add commands to $PATH
zplug load --verbose

#######
# fzf #
#######

# cf. 解説: https://wonderwall.hatenablog.com/entry/2017/10/06/063000
# cf. オプション設定: https://qiita.com/kompiro/items/a09c0b44e7c741724c80
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

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

# z-fzf
# cf. https://github.com/junegunn/fzf/wiki/examples#z
function z-fzf() {
    local selected_dir=$(_z -l 2>&1 | fzf +s --tac | sed 's/^[0-9,.]* *//')
    if [[ -n "$selected_dir" ]]; then
        BUFFER="cd ${selected_dir}"
        zle accept-line
    fi
    zle reset-prompt
}
# Emacs-like binding C-x C-f
zle -N z-fzf
bindkey "^x^f" z-fzf

# ghq-fzf
# cf. https://blog.tsub.me/post/move-from-peco-to-fzf/
function ghq-fzf() {
    local selected_dir=$(ghq list | fzf --query="$LBUFFER")
    if [[ -n "$selected_dir" ]]; then
        BUFFER="cd $(ghq root)/${selected_dir}"
        zle accept-line
    fi
    zle reset-prompt
}
# wiget 登録 & キー割り当て
zle -N ghq-fzf
bindkey "^g" ghq-fzf

# fbr - checkout git branch
# cf. http://bit.ly/34zmzkt
fbr() {
    local branches branch
    branches=$(git branch -vv) &&
        branch=$(echo "$branches" | fzf +m) &&
        git checkout $(echo "$branch" | awk '{print $1}' | sed "s/.* //")
}

# fbr - checkout git branch (including remote branches)
# cf. http://bit.ly/34zmzkt
fbrm() {
    local branches branch
    branches=$(git branch --all | grep -v HEAD) &&
        branch=$(echo "$branches" |
                     fzf-tmux -d $(( 2 + $(wc -l <<< "$branches") )) +m) &&
        git checkout $(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")
}

# fshow - git commit browser
# cf. http://bit.ly/34zmzkt
fshow() {
    git log --graph --color=always \
        --format="%C(auto)%h%d %s %C(black)%C(bold)%cr" "$@" |
        fzf --ansi --no-sort --reverse --tiebreak=index --bind=ctrl-s:toggle-sort \
            --bind "ctrl-m:execute:
                (grep -o '[a-f0-9]\{7\}' | head -1 |
                xargs -I % sh -c 'git show --color=always % | less -R') << 'FZF-EOF'
                {}
FZF-EOF"
}

# worktree移動
# cf. http://bit.ly/34zmzkt
function cdworktree() {
    # カレントディレクトリがGitリポジトリ上かどうか
    git rev-parse &>/dev/null
    if [ $? -ne 0 ]; then
        echo fatal: Not a git repository.
        return
    fi

    local selectedWorkTreeDir=`git worktree list | fzf | awk '{print $1}'`

    if [ "$selectedWorkTreeDir" = "" ]; then
        # Ctrl-C.
        return
    fi

    cd ${selectedWorkTreeDir}
}

# interactive 'diff' and 'add'
# cf. http://bit.ly/34GCFZK
fadd() {
    local out q n addfiles
    while out=$(
            git status --short |
                awk '{if (substr($0,2,1) !~ / /) print $2}' |
                fzf-tmux --multi --exit-0 --expect=ctrl-d); do
        q=$(head -1 <<< "$out")
        n=$[$(wc -l <<< "$out") - 1]
        addfiles=(`echo $(tail "-$n" <<< "$out")`)
        [[ -z "$addfiles" ]] && continue
        if [ "$q" = ctrl-d ]; then
            git diff --color=always $addfiles | less -R
        else
            git add $addfiles
        fi
    done
}

