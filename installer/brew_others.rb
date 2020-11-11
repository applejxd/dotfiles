
#--------------#
# Developments #
#--------------#

brew "make"

# Python: Use 'python3' and 'pip3' command
brew "python"
brew "pipenv"

# C++
brew "clang-format"
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
