# brew bundle --file ./brew_others.rb

#--------------#
# Developments #
#--------------#

brew "make"

# C++
brew "gcc"
brew "cmake"
brew "clang-format"
brew "boost"
brew "opencv"

# Docker
brew "hadolint"

#---------#
# Science #
#---------#

# Cadabra2
tap "kpeeters/repo"
brew "cadabra2"

# brew "gnuplot"
brew "maxima"
brew "wxmaxima"

# Octave
# brew "octave"

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
