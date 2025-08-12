# brew bundle --file ./brew_mas_cask.rb

# Fucntion to check whether current architechture is arm64 or not
# see https://zenn.dev/mactkg/articles/71d09e350315f9
def is_m1?
  !RUBY_PLATFORM.index("arm64e").nil?
end

#---------------#
# Mac App Store #
#---------------#

brew "mas"

# App Store login is required
mas "Magnet", id: 441258766
mas "The Unarchiver", id: 425424353
mas "GoodNotes 5", id: 1444383602

#-------#
# Casks #
#-------#

# Cask for Mac App
tap "homebrew/cask"

# Homebrew GUI manager
cask "cakebrew"

#--------------#
# Fundamentals #
#--------------#

# Basic softwares
#cask "avast-security"
cask "google-chrome"
#cask "google-japanese-ime"
cask "bitwarden"
brew "bitwarden-cli"

# Utilities
cask "iterm2"
cask "alfred"
cask "hyperswitch"
cask "karabiner-elements"

# QuickLook
cask "qlcolorcode"
cask "qlstephen"
cask "qlmarkdown"
cask "quicklook-json"
cask "qlimagesize"
cask "webpquicklook"
cask "suspicious-package"
cask "quicklookase"
# Needs Rosetta2
#cask "qlvideo"

#--------------#
# Developments #
#--------------#

# Editor and IDE
cask "visual-studio-code"
cask "jetbrains-toolbox"
cask "microsoft-remote-desktop"

# Fonts
tap "homebrew/cask-fonts"
cask "font-hack-nerd-font"

# Environments
#cask "xquartz"
cask "docker"

# Reference
cask "dash"

#----------#
# Mac Apps #
#----------#

# media
cask "spotify"
cask "kindle"
cask "discord"
# for Alfred Spotify Mini Player
brew "php"

# file manager
cask "cyberduck"
cask "omnidisksweeper"
#cask "sourcetree"

# Research Tools
#cask "mendeley"
#cask "mathpix-snipping-tool"
