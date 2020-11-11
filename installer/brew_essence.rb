#-----#
# VCS #
#-----#

brew "git"
brew "git-flow-avh"
# brew "tig"

#-------------------#
# zsh Configuration #
#-------------------#

# install shell
if OS.mac?
    brew "bash"
    brew "fish"
    # the zsh cannot use pure theme on Linux
    brew "zsh"
end

# shell plugins
brew "tmux"

# for bash
# brew "z"
# brew "fzf"
# brew "ghq"

#----------------#
# Shell Commands #
#----------------#

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
