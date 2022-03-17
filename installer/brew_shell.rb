################
# Renew shells #
################

# install shell
if OS.mac?
    brew "bash"
    brew "fish"
    # the zsh cannot the use pure theme on Linux
    # brew "zsh"
end

#######
# VCS #
#######

brew "git"
brew "git-flow-avh"
brew "tig"

# shell plugins
brew "tmux"

brew "z"
brew "fzf"
brew "ghq"

##################
# Shell Commands #
##################

# defaults
brew "curl"
brew "gawk"

# command cloning
# brew "bat"
brew "colordiff"
# brew "ripgrep"
brew "atool"
# brew "lsd"

# basic command line tools
brew "vim"
brew "wget"
brew "tree"
brew "ispell"
brew "nkf"

if OS.mac?
    brew "m-cli"
end
