# dotfiles

## How to Install 
- $ bash -c "$(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/install.sh)"
- After execute above command, please restart your terminal.

### for Deploy
- $ bash -c "$(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/deploy.sh)"

### for Initialization
- $ bash -c "$(curl -L https://raw.githubusercontent.com/applejxd/dotfiles/master/init.sh)"

## What does this install?

The scripts install as following:
1. Install development tools depend on OS
2. Install Ruby by anyenv
3. Install Homesick by Ruby
4. Link dotfiles by Homesick
5. Install packages from manager
  - for Ubuntu: via apt
  - for Mac: via Homebrew
6. Install zsh and make it default shell

## How to uninstall
- $ homesick unlink dotfiles
