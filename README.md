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
2. (for Mac OS X: Install Homebrew)
3. Install Ruby by anyenv
4. Install Homesick by Ruby
5. Link dotfiles by Homesick
6. Install packages from manager
    - for Ubuntu: via apt
    - for Mac OS X: via Homebrew
7. Install zsh and make it default shell

## How to uninstall
- $ homesick unlink dotfiles
