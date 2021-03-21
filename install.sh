#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/deploy.sh)
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/main/init.sh)
