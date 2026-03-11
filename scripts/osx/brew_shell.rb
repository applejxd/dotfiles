# brew bundle --file ./brew_shell.rb

#--------#
# shells #
#--------#

# update shell
if OS.mac?
    brew "bash"
    brew "fish"
    # the zsh cannot the use pure theme on Linux
    # brew "zsh"
end

#-----#
# VCS #
#-----#

brew "git"
brew "git-flow-avh"
brew "tig"

# shell plugins
brew "tmux"

brew "z"
brew "fzf"
brew "ghq"

#----------------#
# Shell Commands #
#----------------#

# BSD -> GNU
# see https://qiita.com/eumesy/items/3bb39fc783c8d4863c5f
brew "coreutils"
brew "diffutils"
brew "findutils"
brew "gawk"
brew "gnu-sed"
brew "gnu-tar"

# defaults
brew "curl"
brew "grep"
brew "gzip"

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
