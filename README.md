# dotfiles

Deploy settings and initialize the environment for

- Ubuntu (on WSL)
- Mac OS X

## How to Install

```shell
# Dependencies
sudo apt update && sudo apt install -y curl unzip
# for Docker images
apt update && apt install -y locales curl && locale-gen en_US.UTF-8

# Deployment
bash -c "$(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/deploy.sh)"
# Initialization
bash -c "$(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/init.sh)"
```

or

```shell
# Deployment + Initialization
bash -c "$(curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/install.sh)"
```

After execute above command, please restart your terminal.

## What does it install?

The scripts install configurations as following:

1. Install development tools depend on OS
2. (for Mac OS X: Install Homebrew)
3. Install mise
4. Install Ruby by mise
5. Install Homesick by Ruby
6. Link dotfiles by Homesick
7. Install packages from manager
    - for Ubuntu: via apt-get
    - for Mac OS X: via Homebrew
8. Install zsh and make it default shell

## How to uninstall

```bash
homesick unlink dotfiles
```
