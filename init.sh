#!/bin/sh

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# Python install
anyenv install pyenv
export PYENV_ROOT="$HOME/.anyenv/envs/pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
pyenv install miniforge3-4.10
pyenv global miniforge3-4.10

# for Ubuntu (cf. http://bit.ly/37WjcWG)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu.sh)
fi

# for Mac OS X
if [[ "$OSTYPE" == "darwin"* ]]; then
    if !(type "brew" > /dev/null 2>&1); then
        source /dev/stdin <<<"$( curl -sS https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh )"
        # enable brew command
        # eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    # update bash for process substitution
    brew install bash
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_shell.rb) 2>/dev/null
    brew bundle --file=<(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/brew_mas_cask.rb) 2>/dev/null
    source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx.sh)
fi

echo "$password" | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/shells.sh)
