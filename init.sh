#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

#-----------------#
# OS dependencies #
#-----------------#

# for Ubuntu (see https://eng-entrance.com/linux-os-version)
if [[ -e /etc/lsb-release ]]; then
    # shellcheck source=/dev/null
    echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu/ubuntu.sh)
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # Mac OS X use bash 3.2, and process substitution is unable
    brew_bundle=$(mktemp)
    # see https://tm.root-n.com/programming:shell_script:command:trap
    trap 'rm -f "$brew_bundle"' EXIT HUP INT QUIT TERM

    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx/osx.sh >"$brew_bundle"
    # shellcheck source=/dev/null
    echo "$password" | source "$brew_bundle"
fi

#--------#
# Common #
#--------#

#code --list-extensions
code --install-extension harg.iceberg
code --install-extension eamodio.gitlens
code --install-extension mhutchie.git-graph
code --install-extension foxundermoon.shell-format
