#!/bin/bash

#-----------------#
# OS dependencies #
#-----------------#

if [[ -e /etc/lsb-release ]]; then
    alias open="xdg-open"
fi

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    alias ls="ls --color=auto"

    alias pbcopy='xsel --clipboard --input'
    alias pbpaste='xsel --clipboard --output'
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/osxrc.sh
fi

if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    alias pbcopy='clip.exe'
    alias pbpaste='powershell.exe Get-Clipboard'

    alias open="explorer.exe"
fi

#-----------------#
# Command Wrapper #
#-----------------#

# The default options of "less" command
export LESS="-iMR -gSW -z-4 -x4"

# X11 forwarding
alias ssh="ssh -X"

# with number: -v
alias dirs="dirs -v"

# adding git syntax sugar
if type "hub" >/dev/null 2>&1; then
    eval "$(hub alias -s)"
fi

# "ls" cloning
if type "lsd" >/dev/null 2>&1; then
    alias ls="lsd"
fi

# "cat" cloning
if type "bat" >/dev/null 2>&1; then
    alias cat="bat"
fi

# "diff" cloning & unified format: -u
if type "colordiff" >/dev/null 2>&1; then
    alias diff="colordiff -u"
else
    alias diff="diff -u"
fi

#----------------#
# original alias #
#----------------#

# Restart Terminal
alias relogin='exec $SHELL -l'

alias up="cd .."
alias upp="cd ../.."
alias uppp="cd ../../.."

alias ll="ls -l"
alias la="ls -a"
alias lla="ls -la"
alias lal="ls -al"
alias lt="ls --tree"

# for security
alias gen-key="ssh-keygen -t ed25519 -P \"\""

# count the number of characters
alias wcc="pbpaste | wc -m"
# clear format
alias fcr="pbpaste | pbcopy"

alias search="find . -type f -print0 | xargs -0 grep -n"

#--------------------#
# original functions #
#--------------------#

# Search and Move to The Directory
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# cf. http://rksz.hateblo.jp/entry/2014/10/27/201939
function jj() {
    if [[ "$1" ]]; then
        JUMPDIR=$(find . -type d -maxdepth 1 | grep "$1" | tail -1)
        if [[ -d $JUMPDIR && -n $JUMPDIR ]]; then
            cd "$JUMPDIR" || exit
        else
            echo "directory not found"
        fi
    fi
}

# Remove empty directries up to 2 levels
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function cleanup() {
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
}

# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function sha1() {
    echo -n "$1" | openssl sha1 | sed "s/^.* //"
}
alias sha2="openssl passwd -6 -salt 'SALTsalt'"

#----------------#
# zsh registered #
#----------------#

# unarchive
# cf. http://bit.ly/2tCOvHP
function extract() {
    case $1 in
    *.tar.gz | *.tgz) tar xzvf "$1" ;;
    *.tar.xz) tar Jxvf "$1" ;;
    *.zip) unzip "$1" ;;
    *.lzh) lha e "$1" ;;
    *.tar.bz2 | *.tbz) tar xjvf "$1" ;;
    *.tar.Z) tar zxvf "$1" ;;
    *.gz) gzip -d "$1" ;;
    *.bz2) bzip2 -dc "$1" ;;
    *.Z) uncompress "$1" ;;
    *.tar) tar xvf "$1" ;;
    *.arj) unarj "$1" ;;
    esac
}

# compile with atcoder compile options
# cf. https://qiita.com/matsu_chara/items/8372616f52934c657214
# cf. https://atcoder.jp/contests/APG4b/rules?lang=ja
function runcpp() {
    fname=$(echo "$1" | awk -F/ '{print $NF}' | awk -F. '{print $1}')
    g++ -std=gnu++17 -Wall -Wextra -O2 "$1" -o "$fname"
    shift
    ./"$fname" "$@"
}

#----------------#
# Initialization #
#----------------#

# iceberg theme for vim
if type "ghq" >/dev/null 2>&1; then
    if [[ ! -e $GHQ_ROOT/github.com/cocopon/iceberg.vim ]]; then
        ghq get https://github.com/cocopon/iceberg.vim.git
    fi
    if [[ ! -e $HOME/.vim/colors ]]; then
        mkdir -p "$HOME"/.vim/colors
    fi
    if [[ ! -L $HOME/.vim/colors/iceberg.vim ]]; then
        ln -s "$GHQ_ROOT"/github.com/cocopon/iceberg.vim/colors/iceberg.vim "$HOME"/.vim/colors/iceberg.vim
    fi
fi

#---------#
# Install #
#---------#

# fzf
if ! type "fzf" >/dev/null 2>&1 && [ ! -e "$HOME"/.fzf ]; then
    git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME"/.fzf
    "$HOME"/.fzf/install --key-bindings --completion --no-update-rc
fi

# z
if ! type "z" >/dev/null 2>&1 && [ ! -e "$HOME"/.z ]; then
    git clone https://github.com/rupa/z.git "$HOME"/.z
fi

export _Z_DATA="$HOME"/.z/.z
# shellcheck source=/dev/null
source "$HOME"/.z/z.sh

if ! type "asdf" >/dev/null 2>&1; then
    git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.13.1
fi
# shellcheck source=/dev/null
source "$HOME/.asdf/asdf.sh"

if ! type "ghq" >/dev/null 2>&1; then
    asdf plugin add ghq
    asdf install ghq latest
    asdf global ghq latest
fi
