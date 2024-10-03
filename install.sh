#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

# shellcheck source=/dev/null
echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/deploy.sh)
# shellcheck source=/dev/null
echo "$password" | source <(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/init.sh)
