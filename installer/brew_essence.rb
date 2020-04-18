#-----#
# VCS #
#-----#

brew "git"
brew "hub"
brew "git-flow-avh"
brew "tig"

#-------------------#
# zsh Configuration #
#-------------------#

# install shell
brew "bash"
brew "zsh"
brew "fish"

# Package manager 'zplug'
# brew "zplug"

# shell plugins
brew "tmux"

# for bash
brew "z"
brew "fzf"
brew "ghq"

#----------------#
# Shell Commands #
#----------------#

# defaults
brew "curl"
brew "gawk"

# command cloning
brew "bat"
brew "colordiff"
brew "ripgrep"
brew "atool"
# brew "lsd"

# basic command line tools
brew "vim"
brew "wget"
brew "tree"
brew "ispell"
brew "nkf"

#--------------#
# Developments #
#--------------#

# Python
brew "python3"
brew "python@2"
brew "pipenv"

# C++
brew "boost"
brew "opencv"

#---------#
# Science #
#---------#

# Cadabra2
tap "kpeeters/repo"
brew "cadabra2"

# WxMaxima
brew "gnuplot"
brew "maxima"
brew "wxmaxima"

# Octave
brew "octave"

#----------------#
# Entertainments #
#----------------#

brew "youtube-dl"
brew "ffmpeg"
brew "mediainfo"

# show this environment
brew "screenfetch"

# 元祖 rogue 日本語版
# https://leopard-gecko.github.io/jrogue/
tap "leopard-gecko/game"
brew "jrogue"