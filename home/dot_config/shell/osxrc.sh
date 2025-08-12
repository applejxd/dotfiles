#!/bin/bash

#------#
# arch #
#------#

arch=$(uname -m)

brew_path=""
if [[ $arch == arm64 ]]; then
  echo "Current Architecture: $arch"
  brew_path="/opt/homebrew/bin/brew"
elif [[ $arch == x86_64 ]]; then
  echo "Current Architecture: $arch"
  brew_path="/usr/local/bin/brew"
fi

if [[ -e $brew_path ]]; then
  eval "$($brew_path shellenv)"
fi
alias x64='exec arch -x86_64 /bin/zsh'
alias a64='exec arch -arm64e /bin/zsh'

function switch-arch() {
  if [[ "$(uname -m)" == arm64 ]]; then
    arch=x86_64
  elif [[ "$(uname -m)" == x86_64 ]]; then
    arch=arm64e
  fi
  exec arch -arch "$arch" /bin/zsh
}

#-------#
# alias #
#-------#

alias ls="ls -G"

# Finder functions for OS X
# see http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# see https://vivafan.com/2013/03/csh-no-function/

# Open current directory in Finder
alias f="open -a Finder ./"
# Move to directory opend by Finder
function cdf() {
  target=$(osascript -e 'tell application "Finder" to if (count of Finder windows) > 0 then get POSIX path of (target of front Finder window as text)')
  if [ "$target" != "" ]; then
    cd "$target" || exit
    pwd
  else
    echo 'No Finder window found' >&2
  fi
}

#-------#
# iTerm #
#-------#

# for iTerm badge function
# http://bit.ly/2LTeYXt
if [[ -e ~/.iterm2_shell_integration.zsh ]]; then
  function badge() {
    printf "\e]1337;SetBadgeFormat=%s\a" \
      "$(echo -n "$1" | base64)"
  }

  function ssh_local() {
    local ssh_config=~/.ssh/config
    local server
    server=$(cat $ssh_config | grep "Host " | sed "s/Host //g" | fzf)
    if [ -z "$server" ]; then
      return
    fi
    badge "$server"
    ssh "$server"
  }
fi
