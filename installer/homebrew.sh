#!/bin/sh

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# Requirements
# (For Mac OS X, command line tools for xcode are automatically installed by the following script.)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | sudo -S apt-get update -y
    echo "$password" | sudo -S apt-get upgrade -y
    # for Homebrew
    # cf. https://docs.brew.sh/Homebrew-on-Linux
    echo "$password" | sudo -S apt-get install -y build-essential curl file git
fi

# Prepare installation script
tmp_file=$(mktemp)
# cf. https://tm.root-n.com/programming:shell_script:command:trap
trap 'rm -f "$temp_file"' EXIT HUP INT QUIT TERM
curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh > tmp_file

# Install Homebrew for Mac OS X or Linux
# cf. https://qiita.com/ine1127/items/cd6bc91174635016db9b
expect -c "
set timeout -1
spawn env LANG=C /bin/bash tmp_file
expect \"Password:\"
send \"${password}\n\"
expect \"Press\"
send \"\n\"
expect \"$\"
exit 0
"

[[ -n "${tmp_file} "]] && rm -f "$tmp_file"

# Enable Homebrew
if [[ "$OSTYPE" == "darwin"* ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ "$OSTYPE" == "linux-gnu" ]]; then
    # cf. https://docs.brew.sh/Homebrew-on-Linux
    test -d ~/.linuxbrew && eval $(~/.linuxbrew/bin/brew shellenv)
    test -d /home/linuxbrew/.linuxbrew && eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
    test -r ~/.bashrc && echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.bashrc
fi
