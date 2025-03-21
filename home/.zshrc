#!/bin/zsh
# .zshenv>.zprofile>.zshrc>.zlogin

SHELL_CONF=$HOME/.config/shell

#--------#
# common #
#--------#

if [ -e $COMMON_RC ]; then
    source $SHELL_CONF/shellrc.sh
fi

# Emacs mode
bindkey -e

# zsh completion
autoload -Uz compinit && compinit

#-----------------#
# OS dependencies #
#-----------------#

zle -N switch-arch

#------------#
# zsh proper #
#------------#

# cd completion
# see http://bit.ly/2ZtPPrN
setopt auto_cd
cdpath=(.. ~)
function chpwd() {
    if type "lsd" >/dev/null 2>&1; then
        lsd
    else
        ls
    fi
}

# for glob expression
# see https://qiita.com/nisaji/items/f9eede2164a74bc08db7
setopt +o nomatch

# auto pushd & no history
setopt auto_pushd
setopt pushd_ignore_dups

# iTerm2 shell integration
[[ -f "${HOME}/.iterm2_shell_integration.zsh" ]] &&
    source "${HOME}/.iterm2_shell_integration.zsh"

# fg -> C-z
zle -N fancy-ctrl-z
bindkey '^Z' fancy-ctrl-z

#-------------#
# zsh history #
#-------------#

# see http://bit.ly/2EXlQ1S

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

#--------------#
# suffix alias #
#--------------#

# texts
alias -s {txt,dat,plt}='cat'

# images
if [[ "$OSTYPE" == "darwin"* ]]; then
    alias -s {pdf,jpg,jpeg,png,bmp,gif}='open -a Preview'
fi

# scripts
alias -s sh='bash'
alias -s py='python'
alias -s rb='ruby'
alias -s php='php -f'
alias -s hs='runhaskell'

# unarchive
# see http://bit.ly/2tCOvHP
if type "aunpack" >/dev/null 2>&1; then
    alias -s {gz,tgz,zip,lzh,bz2,tbz,Z,tar,arj,xz}=aunpack
else
    alias -s {gz,tgz,zip,lzh,bz2,tbz,Z,tar,arj,xz}=extract
fi

# compile
# see http://bit.ly/2tCOvHP

alias -s {c,cc,cpp}='runcpp'

# fg -> C-z
function fancy-ctrl-z() {
    if [[ $#BUFFER -eq 0 ]]; then
        BUFFER="fg"
        # Finish editing the buffer
        zle accept-line
    else
        # Push onto the buffer stack & Return to prompt
        zle push-input
        # Clear the screen
        zle clear-screen
    fi
}

#-----#
# fzf #
#-----#

[ -f "$HOME"/.fzf.zsh ] && source "$HOME"/.fzf.zsh

# common setting
COMMON_FZF=$HOME/.config/shell/fzf.sh
if [ -e $COMMON_FZF ]; then
    source $COMMON_FZF
fi

# z-fzf, emacs-like key-bindings
# see http://bit.ly/2sEPZAJ
if type "z" >/dev/null 2>&1; then
    function z-fzf() {
        local selected_dir=$(_z -l 2>&1 | fzf +s --tac | sed 's/^[0-9,.]* *//')
        if [[ -n "$selected_dir" ]]; then
            BUFFER="cd ${selected_dir}"
            zle accept-line
        fi
        zle reset-prompt
    }
    zle -N z-fzf
    bindkey "^X^F" z-fzf
fi

# ghq-fzf
# see http://bit.ly/2MMEb6e
if type "ghq" >/dev/null 2>&1; then
    function ghq-fzf() {
        local selected_dir=$(ghq list | fzf --query="$LBUFFER")
        if [[ -n "$selected_dir" ]]; then
            BUFFER="cd $(ghq root)/${selected_dir}"
            zle accept-line
        fi
        zle reset-prompt
    }
    zle -N ghq-fzf
    bindkey "^X^G" ghq-fzf
fi

#-------------#
# Activations #
#-------------#

if [[ -e "$HOME/.local/bin/mise" ]]; then
    eval "$(~/.local/bin/mise activate zsh)"
fi

if [[ -e /usr/local/Modules/init ]]; then
    source /usr/local/Modules/init/zsh
fi

if [[ -e /opt/ros ]]; then
    ros_dir=$(find /opt/ros -mindepth 1 -maxdepth 1 -type d | head -n 1)
    source "${ros_dir}/setup.zsh"
fi

# for Cline
# see https://github.com/cline/cline/wiki/Troubleshooting-%E2%80%90-Shell-Integration-Unavailable#still-having-trouble
[[ "$TERM_PROGRAM" == "vscode" ]] && . "$(code --locate-shell-integration-path zsh)"
