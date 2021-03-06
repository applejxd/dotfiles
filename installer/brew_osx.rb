#################
# Mac App Store #
#################

brew "mas"

mas "Magnet", id: 441258766
mas "The Unarchiver", id: 425424353

#########
# Casks #
#########

# Cask for Mac App
tap "homebrew/cask"

#--------------#
# Developments #
#--------------#

# GUI Apps
cask "cakebrew"
cask "sourcetree"

# Editor and IDE
cask "visual-studio-code"
cask "pycharm"
cask "emacs"

# rogue-like game 'jnethack'
cask "xquartz"
brew "jnethack"
brew "cocot"

#--------------#
# Fundamentals #
#--------------#

# Basic softwares
cask "avast-security"
cask "google-chrome"
cask "google-japanese-ime"

# Online storages
cask "dropbox"
cask "google-backup-and-sync"

#------------------#
# System Asistants #
#------------------#

# quicklook
cask "qlcolorcode"
cask "qlstephen"
cask "qlmarkdown"
cask "quicklook-json"
cask "qlimagesize"
cask "webpquicklook"
cask "suspicious-package"
cask "quicklookase"
cask "qlvideo"

# system
cask "alfred"
cask "hyperswitch"
cask "karabiner-elements"

# Remote directory mounting
cask "osxfuse"
brew "sshfs"

# The shell emulator iTerm2
cask "iterm2"

# Fonts
tap "homebrew/cask-fonts"
cask "font-hack-nerd-font"

#----------#
# Mac Apps #
#----------#

# utilities
cask "evernote"
cask "bitwarden"
brew "bitwarden-cli"
cask "skype"

# media
cask "spotify"
cask "kindle"

# file manager
cask "cyberduck"
cask "omnidisksweeper"

# Research Tools
cask "mendeley-desktop"
cask "mathpix-snipping-tool"

# Reference
cask "dash"

# graph
cask "xmind"
cask "drawio"

# Emulation
# cask "virtualbox"
# cask "virtualbox-extension-pack"
brew "docker"
cask "docker"

#-----------#
# Platforms #
#-----------#

cask "mamp"
cask "julia"
cask "r"
cask "mactex"
# cask "sage"