#!/bin/bash

if [[ $(id -u) -ne 0 ]]; then
    if [ $# -eq 0 ]; then
        # save password
        read -rsp "Password: " password
    else
        password="$1"
    fi
fi

#-----------------------#
# Requirements (Global) #
#-----------------------#

# for ruby-build in Ubuntu (cf. https://github.com/rbenv/ruby-build/wiki)
if [[ -e /etc/lsb-release ]] && (! type "ruby-build" >/dev/null 2>&1); then
    cmd="apt-get update && \
         apt-get upgrade -y && \
         apt-get install -y git curl unzip build-essential libssl-dev zlib1g-dev"
    if [[ $(id -u) -ne 0 ]]; then
        echo "$password" | sudo -S bash -c "$cmd"
    else
        eval "$cmd"
    fi
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    if (! git --version >/dev/null 2>&1); then
        xcode-select --install
        echo "Rerun this script after completion to install the command line tools."
        exit 1
    fi

    if (! type "brew" >/dev/null 2>&1); then
        # Mac OS X use bash 3.2, and process substitution is unable
        brew_script=$(mktemp)
        # cf. https://tm.root-n.com/programming:shell_script:command:trap
        trap 'rm -f "$brew_script"' EXIT HUP INT QUIT TERM
        curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/homebrew.sh >"$brew_script"
        # shellcheck source=/dev/null
        echo "$password" | source "$brew_script"
    fi
fi

#----------------------#
# Requirements (Local) #
#----------------------#

# mise
if [[ ! -e "$HOME/.local/bin/mise" ]]; then
    curl https://mise.run | sh
fi
eval "$(~/.local/bin/mise activate)"
export PATH="$HOME/.local/share/mise/shims:$PATH"
MAKE_OPS=-j2 mise use --global -y ruby@2.7.8

#--------------#
# Link configs #
#--------------#

if (! type "homesick" >/dev/null 2>&1); then
    gem install homesick
fi

# spacemacs install
if [[ ! -e ~/.emacs.d ]]; then
    git clone https://github.com/syl20bnr/spacemacs ~/.emacs.d
fi

if [[ ! -e ~/.homesick/repos/dotfiles ]]; then
    homesick clone applejxd/dotfiles
    # for ghq
    if [[ ! -e ~/src ]]; then
        mkdir ~/src
    fi
    ln -s ~/.homesick/repos/dotfiles ~/src/
fi

if [[ ! -L ~/.bashrc ]]; then
    if [[ -f ~/.bashrc ]]; then
        mv ~/.bashrc ~/.bashrc_old
    fi
    homesick link dotfiles
fi

#---------------#
# Write configs #
#---------------#

if (type "git" >/dev/null 2>&1); then
    git config --global init.defaultBranch "main"

    git config --global core.editor "vim"
    # distinguish between uppercase and lowercase
    git config --global core.ignorecase "false"
    # to display Japanese files
    git config --global core.quotepath "false"

    git config --global ghq.root "$HOME/src"
    git config --global gitflow.branch.master "main"

    # for ssh push
    git config --global url."github:".pushInsteadOf https://github.com/

    # save credentials (for AzureDevOps)
    git config --global credential.helper store
fi

read -r -n1 -p "configure default shells? (y/N): " yn
if [[ $yn = [yY] ]]; then
    # Mac OS X use bash 3.2, and process substitution is unable
    shell_config=$(mktemp)
    # cf. https://tm.root-n.com/programming:shell_script:command:trap
    trap 'rm -f "$shell_config"' EXIT HUP INT QUIT TERM
    curl -fsSL https://raw.githubusercontent.com/applejxd/dotfiles/main/installer/shells.sh >"$shell_config"
    # shellcheck source=/dev/null
    echo "$password" | source "$shell_config"
fi
