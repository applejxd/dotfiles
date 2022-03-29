#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

###################
# OS dependencies #
###################

# for Ubuntu (cf. http://bit.ly/37WjcWG)
if [[ -e /etc/lsb-release ]]; then
    echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/ubuntu.sh)
elif [[ "$OSTYPE" == "darwin"* ]]; then   
    # Mac OS X use bash 3.2, and process substitution is unable
    brew_bundle=$(mktemp)
    # cf. https://tm.root-n.com/programming:shell_script:command:trap
    trap 'rm -f "$brew_bundle"' EXIT HUP INT QUIT TERM
    
    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/osx.sh > brew_bundle
    echo "$password" | source brew_bundle
fi
