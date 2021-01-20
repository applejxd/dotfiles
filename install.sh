#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    printf "password: "
    read password
else
    password=$1
fi

echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/deploy.sh)
echo $password | source <(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/init.sh)
