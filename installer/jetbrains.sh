#!/bin/sh

if [[ $# -eq 0 ]]; then
    # save password
    printf "password: "
    read password
else
    password=$1
fi

if !(id jetbrains >/dev/null 2>&1); then
    echo "$password" | sudo -S useradd -s /bin/bash -m jetbrains
    echo "$password" | sudo -S passwd --stdin jetbrains
    echo "export DISPLAY=\$(cat /etc/resolv.conf | grep nameserver | awk '{print \$2}'):0.0" > /home/jetbrains/shellenv.sh
fi