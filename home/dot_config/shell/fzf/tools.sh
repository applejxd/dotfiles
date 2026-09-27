#!/bin/bash

#------#
# mise #
#------#

if command -v "ghq" >/dev/null 2>&1; then
    function mise-select() {
        if [[ -z "$1" ]]; then
            return 1
        fi
        local select_ver
        select_ver=$(mise ls-remote "$1" | sort -rV | fzf)
        mise use "$1@${select_ver}"
    }
fi

#-------------#
# Singularity #
#-------------#

if command -v "singularity" >/dev/null 2>&1; then
    function sbuild() {
        local file_name
        file_name=$(find ./*.def | fzf)
        # https://qiita.com/mriho/items/b30b3a33e8d2e25e94a8
        file_name=${file_name%.*}

        [ -n "$file_name" ] && sudo -E singularity build "$file_name".sif "$file_name".def
    }

    function bbuild() {
        local file_name
        file_name=$(find ./*.def | fzf)
        # https://qiita.com/mriho/items/b30b3a33e8d2e25e94a8
        file_name=${file_name%.*}

        [ -n "$file_name" ] && sudo -E singularity build --sandbox "$file_name"-box "$file_name".def
    }

    function box2sif() {
        local box_name
        box_name=$(find . -maxdepth 1 -type d | fzf)
        [ -n "$box_name" ] && singularity build "$box_name".sif "$box_name"
    }

    function sshell() {
        local file_name
        file_name=$(find ./*.sif | fzf)

        [ -n "$file_name" ] && singularity shell --nv "$file_name"
    }

    function sexe() {
        local file_name
        file_name=$(find ./*.sif | fzf)

        [ -n "$file_name" ] && singularity exec --nv "$file_name" "$@"
    }

    function bshell() {
        local box_name
        box_name=$(find . -maxdepth 1 -type d | fzf)
        [ -n "$box_name" ] && sudo singularity shell --nv --writable "$box_name"
    }

    function brun() {
        local box_name
        box_name=$(find . -maxdepth 1 -type d | fzf)
        [ -n "$box_name" ] && sudo singularity run --nv --writable "$box_name"
    }

    alias sls="singularity instance list"

    function sstart() {
        local file_name
        file_name=$(find ./*.sif | fzf)
        # https://qiita.com/mriho/items/b30b3a33e8d2e25e94a8
        file_name=${file_name%.*}

        [ -n "$file_name" ] && singularity instance start --nv "$file_name".sif "$file_name"
    }

    function sishell() {
        local instance_name
        instance_name=$(singularity instance list | sed -e '1d' | awk '{print $1}' | fzf)

        [ -n "$instance_name" ] && singularity shell instance://"$instance_name"
    }

    function sstop() {
        local instance_name
        instance_name=$(singularity instance list | sed -e '1d' | awk '{print $1}' | fzf)

        [ -n "$instance_name" ] && singularity instance stop "$instance_name"
    }
fi

#----------#
# Homebrew #
#----------#

if command -v "brew" >/dev/null 2>&1; then
    # Install or open the webpage for the selected application
    # using brew search --casks as input source
    # and display a info quickview window for the currently marked application
    function install() {
        local token
        token=$(brew search --casks | fzf-tmux --query="$1" +m --preview 'brew info --cask {}')

        if [ -n "$token" ]; then
            echo "(I)nstall or open the (h)omepage of $token"
            read -r input
            if [ "$input" = "i" ] || [ "$input" = "I" ]; then
                brew install --cask "$token"
            fi
            if [ "$input" = "h" ] || [ "$input" = "H" ]; then
                brew home "$token"
            fi
        fi
    }

    # Uninstall or open the webpage for the selected application
    # using brew list as input source (all installed casks)
    # and display a info quickview window for the currently marked application
    function uninstall() {
        local token
        token=$(brew list --cask | fzf-tmux --query="$1" +m --preview 'brew info --cask {}')

        if [ -n "$token" ]; then
            echo "(U)ninstall or open the (h)omepage of $token"
            read -r input
            if [ "$input" = "u" ] || [ "$input" = "U" ]; then
                brew uninstall --cask "$token"
            fi
            if [ "$input" = "h" ] || [ "$input" = "H" ]; then
                brew home "$token"
            fi
        fi
    }
fi
