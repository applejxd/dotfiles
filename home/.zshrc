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
# cf. http://bit.ly/2ZtPPrN
setopt auto_cd
cdpath=(.. ~)
function chpwd() {
    ls
}

# 自動 pushd & 履歴は残さない
setopt auto_pushd
setopt pushd_ignore_dups

# iTerm2 shell integration
test -e "${HOME}/.iterm2_shell_integration.zsh" &&
source "${HOME}/.iterm2_shell_integration.zsh"

###############
# zsh history #
###############

# cf. http://bit.ly/2EXlQ1S

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

# zplug settings
export ZPLUG_HOME=/usr/local/opt/zplug
source $ZPLUG_HOME/init.zsh

# fish-like auto completion
zplug "zsh-users/zsh-autosuggestions"
# completion for non-defalut commands
zplug "zsh-users/zsh-completions"
# syntax-highlighting to command-line (compinit 以降)
zplug "zsh-users/zsh-syntax-highlighting", defer:2

# 'z' command
zplug "rupa/z", use:z.sh
# enhance 'cd' command
zplug "b4b4r07/enhancd", use:init.sh
export ENHANCD_COMMAND=ecd

# docker
zplug 'felixr/docker-zsh-completion'
zplug 'mnowotnik/docker-fzf-completion', use:docker-fzf.zsh

# git
zplug "plugins/git", from:oh-my-zsh

################
# Powerlevel9k #
################

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

#######
# fzf #
#######

# cf. 解説: https://wonderwall.hatenablog.com/entry/2017/10/06/063000
# cf. オプション設定: https://qiita.com/kompiro/items/a09c0b44e7c741724c80
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ** -> ,
export FZF_COMPLETION_TRIGGER=","

COMMON_FZF=$HOME/.config/shell/fzf.sh

if [ -e $COMMON_RC ]; then
    source $COMMON_FZF
fi

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

zle -N ghq-fzf
bindkey "^g" ghq-fzf

###################
# zplug installer #
###################

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