SHELL_CONF=$HOME/.config/shell

#################
# common config #
#################

if [ -e $COMMON_RC ]; then
    source $SHELL_CONF/shellrc.sh
fi

# Emacs mode
bindkey -e

# zsh completion
autoload -Uz compinit && compinit

###################
# OS dependencies #
###################

function switch-arch() {
    if  [[ "$(uname -m)" == arm64 ]]; then
        arch=x86_64
    elif [[ "$(uname -m)" == x86_64 ]]; then
        arch=arm64e
    fi
    exec arch -arch $arch /bin/zsh
}
zle -N switch-arch

##############
# zsh proper #
##############

# cd completion
# cf. http://bit.ly/2ZtPPrN
setopt auto_cd
cdpath=(.. ~)
function chpwd() {
    if type "lsd" >/dev/null 2>&1; then
        lsd
    else
        ls
    fi
}

# auto pushd & no history
setopt auto_pushd
setopt pushd_ignore_dups

# iTerm2 shell integration
[[ -f "${HOME}/.iterm2_shell_integration.zsh" ]] &&
    source "${HOME}/.iterm2_shell_integration.zsh"

# fg -> C-z
function fancy-ctrl-z() {
    if [[ $#BUFFER -eq 0 ]]; then
        BUFFER="fg"
        zle accept-line
    else
        zle push-input
        zle clear-screen
    fi
}
zle -N fancy-ctrl-z
bindkey '^Z' fancy-ctrl-z

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

################
# suffix alias #
################

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
# cf. http://bit.ly/2tCOvHP
if type "aunpack" >/dev/null 2>&1; then
    alias -s {gz,tgz,zip,lzh,bz2,tbz,Z,tar,arj,xz}=aunpack
else
    function extract() {
        case $1 in
        *.tar.gz | *.tgz) tar xzvf $1 ;;
        *.tar.xz) tar Jxvf $1 ;;
        *.zip) unzip $1 ;;
        *.lzh) lha e $1 ;;
        *.tar.bz2 | *.tbz) tar xjvf $1 ;;
        *.tar.Z) tar zxvf $1 ;;
        *.gz) gzip -d $1 ;;
        *.bz2) bzip2 -dc $1 ;;
        *.Z) uncompress $1 ;;
        *.tar) tar xvf $1 ;;
        *.arj) unarj $1 ;;
        esac
    }
    alias -s {gz,tgz,zip,lzh,bz2,tbz,Z,tar,arj,xz}=extract
fi

# compile
# cf. http://bit.ly/2tCOvHP
function runcpp() {
    fname=$(echo $1 | awk -F/ '{print $NF}' | awk -F. '{print $1}')
    g++ -O2 -Wall -Wextra $1 -o $fname
    shift
    ./$fname $@
}
alias -s {c,cc,cpp}='runcpp'

#######
# fzf #
#######

if type "fzf" >/dev/null 2>&1;then
    # ** -> ,
    export FZF_COMPLETION_TRIGGER=","

    # common setting
    COMMON_FZF=$HOME/.config/shell/fzf.sh
    if [ -e $COMMON_FZF ]; then
        source $COMMON_FZF
    fi

    # z-fzf, emacs-like key-bindings
    # cf. http://bit.ly/2sEPZAJ
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
    # cf. http://bit.ly/2MMEb6e
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
fi
