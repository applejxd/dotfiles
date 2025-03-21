#!/bin/bash

# Install Homebrew

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

brew_path=""
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == arm64 ]]; then
        brew_path="/opt/homebrew/bin/brew"
    elif [[ $(uname -m) == x86_64 ]]; then
        brew_path="/usr/local/bin/brew"
    fi
fi

if [[ ! -e "$brew_path" ]]; then
    # Requirements
    # (For Mac OS X, command line tools for xcode are automatically installed by the following script.)
    if [[ -e /etc/lsb-release ]]; then
        echo "$password" | sudo -S apt-get update -y
        echo "$password" | sudo -S apt-get upgrade -y
        # for Homebrew
        # see https://docs.brew.sh/Homebrew-on-Linux
        echo "$password" | sudo -S apt-get install -y build-essential curl file git
    fi

    # Prepare installation script
    tmp_file=$(mktemp)
    # see https://tm.root-n.com/programming:shell_script:command:trap
    trap 'rm -f "$tmp_file"' EXIT HUP INT QUIT TERM
    curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh >"$tmp_file"

    # Install Homebrew for Mac OS X or Linux
    # see https://qiita.com/ine1127/items/cd6bc91174635016db9b
    expect -c "
    set timeout -1
    spawn env LANG=C /bin/bash $tmp_file
    expect \"Password:\"
    send \"${password}\n\"
    expect \"Press\"
    send \"\n\"
    expect \"$\"
    exit 0
    "
fi

eval "$($brew_path shellenv)"
