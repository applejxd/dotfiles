#!/bin/sh

# cf. https://zenn.dev/sprout2000/articles/95b125e3359694

if [ $# -eq 0 ]; then
    # Save Password
    read -sp "Password: " password
else
    password=$1
fi

echo "$password" | sudo -S apt-get update
echo "$password" | sudo -S apt-get -y upgrade
echo "$password" | sudo -S apt-get -y install curl apt-transport-https

# register GPG key of Docker official
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
# add stable repository
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "$password" | sudo -S apt-get update
echo "$password" | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose
echo "$password" | sudo -S service docker start
echo "$password" | sudo -S gpasswd -a $(whoami) docker