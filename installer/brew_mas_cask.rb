# cf. https://zenn.dev/mactkg/articles/71d09e350315f9
def is_m1?
  !RUBY_PLATFORM.index("arm64e").nil?
end

#################
# Mac App Store #
#################

brew "mas"

# App Store login is required
mas "Magnet", id: 441258766
mas "The Unarchiver", id: 425424353
mas "GoodNotes 5", id: 1444383602

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
# cask "sourcetree"

# Editor and IDE
cask "visual-studio-code"
cask "jetbrains-toolbox"
cask "emacs"

# The shell emulator iTerm2
cask "iterm2"

# Fonts
tap "homebrew/cask-fonts"
cask "font-hack-nerd-font"

# Emulation
cask "docker"
# cask "virtualbox"
# cask "virtualbox-extension-pack"

# Reference
cask "dash"

#--------------#
# Fundamentals #
#--------------#

# Basic softwares
cask "avast-security"
cask "google-chrome"
cask "google-japanese-ime"

# Online storages
# cask "dropbox"
# cask "google-backup-and-sync"
# cask "google-drive"

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

# Drive format support
cask "osxfuse"

# Remote directory mounting
# brew "sshfs" unless is_m1?

#----------#
# Mac Apps #
#----------#

# utilities
cask "bitwarden"
brew "bitwarden-cli"
cask "discord"
# cask "skype"
# cask "evernote"

# media
cask "spotify"
cask "kindle"

# file manager
cask "cyberduck"
cask "omnidisksweeper"

# graph
# cask "xmind"
# cask "drawio"

# Research Tools
# cask "mendeley"
# cask "mathpix-snipping-tool"

#-----------#
# Platforms #
#-----------#

# cask "mactex"
# cask "mamp"
# cask "julia"
# cask "r"
# cask "sage"

#--------#
# Others #
#------=-#

# rogue-like game 'jnethack'
cask "xquartz"
brew "jnethack"
brew "cocot"
