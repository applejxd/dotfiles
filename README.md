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
3. Install anyenv
4. Install Ruby by anyenv
5. Install Homesick by Ruby
6. Link dotfiles by Homesick
7. Install packages from manager
    - for Ubuntu: via apt
    - for Mac OS X: via Homebrew
8. Install zsh and make it default shell

## How to uninstall
- $ homesick unlink dotfiles
