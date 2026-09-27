#!/bin/bash

#---------#
# options #
#---------#

# default is **
# export FZF_COMPLETION_TRIGGER=','

export FZF_CTRL_R_OPTS='--sort --exact'

# search command
# see https://qiita.com/kamykn/items/aa9920f07487559c0c7e
if command -v "rg" >/dev/null 2>&1; then
    export FZF_DEFAULT_COMMAND=(rg --files --hidden --follow --glob "!.git/*")
else
    unset FZF_DEFAULT_COMMAND
fi

# show below, show border, set hight
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# preview by bat, with color, with file name header, with grid
if command -v "bat" >/dev/null 2>&1; then
    export FZF_CTRL_T_OPTS='--preview "bat --color=always --style=header,grid --line-range :100 {}"'
else
    unset FZF_CTRL_T_OPTS
fi

# preview by tree, with color (enable Japanese)
# see https://wonderwall.hatenablog.com/entry/2017/10/06/063000#--select-1---exit-0
if command -v "tree" >/dev/null 2>&1; then
    export FZF_ALT_C_OPTS='--preview "tree -C -N {} | head -200" --select-1 --exit-0'
else
    unset FZF_ALT_C_OPTS
fi

#---------#
# wrapper #
#---------#

if [ -r "${HOME}/.z/z.sh" ]; then
    function xf() {
        local selected_dir
        selected_dir=$(_z -l 2>&1 | fzf +s --tac | sed 's/^[0-9,.]* *//')
        if [[ -n "$selected_dir" ]]; then
            cd "${selected_dir}" || return
        fi
    }
fi

if command -v "ghq" >/dev/null 2>&1; then
    function xg() {
        local selected_dir
        selected_dir=$(ghq list | fzf)
        if [[ -n "$selected_dir" ]]; then
            cd "$(ghq root)/${selected_dir}" || return
        fi
    }
fi

if command -v "gwq" >/dev/null 2>&1; then
    function xgw() {
        local selected_dir
        selected_dir=$(gwq list | fzf)
        if [[ -n "$selected_dir" ]]; then
            cd "$(gwq get "$selected_dir")" || return
        fi
    }

    function gwcode() {
        local selected_dir
        selected_dir=$(gwq list | fzf)
        if [[ -n "$selected_dir" ]]; then
            gwq exec "$selected_dir" -- code .
        fi
    }
fi

#-----------#
# functions #
#-----------#

# v - open files in ~/.viminfo
v() {
    local files
    files=$(grep '^>' ~/.viminfo | cut -c3- |
        while read -r line; do
            [ -f "${line/\~/$HOME}" ] && echo "$line"
        done | fzf -d -m -q "$*" -1) && vim "${files//\~/$HOME}"
}

function sshf() {
    # see https://www.jamesridgway.co.uk/list-ssh-hosts-from-your-ssh-config/
    name=$(grep -P "^Host ([^*]+)$" "$HOME"/.ssh/config | sed 's/Host //' | fzf)
    [ -n "$name" ] && ssh "$name"
}

# fg-fzf
# see http://bit.ly/39OMtEr
alias fgg='_fgg'
function _fgg() {
    wc=$(jobs | wc -l | tr -d ' ')
    if [ "$wc" -ne 0 ]; then
        job=$(jobs | awk -F "suspended" "{print $1 $2}" | sed -e "s/\-//g" -e "s/\+//g" -e "s/\[//g" -e "s/\]//g" | grep -v pwd | fzf | awk "{print $1}")
        wc_grep=$(echo "$job" | grep -v grep | grep 'suspended')
        if [ "$wc_grep" != "" ]; then
            fg %"$job"
        fi
    fi
}

function shellf() {
    local shell
    shell=$(sed -e "1d" </etc/shells | fzf -q "$1")
    [ -n "$shell" ] && "$shell"
}

# see http://bit.ly/37GNSLZ
if [[ "$OSTYPE" == "darwin"* ]]; then
    unmount() {
        DEVICE=$(diskutil list | grep '/dev' | cut -d ' ' -f 1 | fzf --preview 'diskutil info {}')

        # Sanity check the device
        diskutil info "$DEVICE" | grep "Device Location" | grep -q External || {
            echo "Chosen disk is an internal disk, so cannot unmount" >&2
            exit 1
        }

        diskutil info "$DEVICE" | grep "Virtual" | grep -q No || {
            echo "Chosen disk is virtual, so cannot unmount" >&2
            exit 1
        }

        echo "Unmounting $DEVICE"
        diskutil unmountDisk "$DEVICE"
    }
fi
