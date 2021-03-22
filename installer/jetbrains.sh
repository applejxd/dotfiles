#!/bin/sh

if [[ $# -eq 0 ]]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# wsl.conf の設定（シンボリックリンクでなければ実行）
if [ ! -L /etc/wsl.conf ]; then
    echo "$password" | sudo -S rm /etc/wsl.conf
    echo "$password" | sudo -S ln -s ~/.homesick/repos/dotfiles/config/wsl.conf /etc/wsl.conf
fi

if !(id jetbrains >/dev/null 2>&1); then
    echo "$password" | sudo -S useradd -s /bin/bash -m jetbrains
    echo $password | sudo -S sh -c "echo \"jetbrains:$password\" | chpasswd"
    echo $password | sudo -S gpasswd -a jetbrains sudo
    echo "export DISPLAY=\$(cat /etc/resolv.conf | grep nameserver | awk '{print \$2}'):0.0" > /home/jetbrains/shellenv.sh
    echo "$password" | sudo -S -u jetbrains wget -P /home/jetbrains https://raw.githubusercontent.com/JetBrains/clion-wsl/master/ubuntu_setup_env.sh && bash /home/jetbrains/ubuntu_setup_env.sh
fi
