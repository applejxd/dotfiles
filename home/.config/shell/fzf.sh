###########
# options #
###########

# search command
# cf. https://qiita.com/kamykn/items/aa9920f07487559c0c7e
if type "rg" >/dev/null 2>&1; then
    export FZF_DEFAULT_COMMAND='rg --files --hidden --follow --glob "!.git/*"'
fi
# show below, show border, set hight
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# preview by bat, with color, with file name header, with grid
if type "bat" >/dev/null 2>&1; then
    export FZF_CTRL_T_OPTS='--preview "bat  --color=always --style=header,grid --line-range :100 {}"'
fi

# preview by tree, with color (enable Japanese)
# cf. http://bit.ly/35TBnvE
if type "tree" >/dev/null 2>&1; then
    export FZF_ALT_C_OPTS='--preview "tree -C -N {} | head -200" --select-1 --exit-0'
fi

#############
# functions #
#############

# fg-fzf
# cf. http://bit.ly/39OMtEr
alias fgg='_fgg'
function _fgg() {
    wc=$(jobs | wc -l | tr -d ' ')
    if [ $wc -ne 0 ]; then
        job=$(jobs | awk -F "suspended" "{print $1 $2}" | sed -e "s/\-//g" -e "s/\+//g" -e "s/\[//g" -e "s/\]//g" | grep -v pwd | fzf | awk "{print $1}")
        wc_grep=$(echo $job | grep -v grep | grep 'suspended')
        if [ "$wc_grep" != "" ]; then
            fg %$job
        fi
    fi
}

# v - open files in ~/.viminfo
v() {
    local files
    files=$(grep '^>' ~/.viminfo | cut -c3- |
        while read line; do
            [ -f "${line/\~/$HOME}" ] && echo "$line"
        done | fzf-tmux -d -m -q "$*" -1) && vim ${files//\~/$HOME}
}

# cf. http://bit.ly/37GNSLZ
if [[ "$OSTYPE" == "darwin"* ]]; then
    unmount() {
        DEVICE=$(diskutil list | grep '/dev' | cut -d ' ' -f 1 | fzf --preview 'diskutil info {}')

        # Sanity check the device
        diskutil info $DEVICE | grep "Device Location" | grep -q External || {
            echo "Chosen disk is an internal disk, so cannot unmount" >&2
            exit 1
        }

        diskutil info $DEVICE | grep "Virtual" | grep -q No || {
            echo "Chosen disk is virtual, so cannot unmount" >&2
            exit 1
        }

        echo "Unmounting $DEVICE"
        diskutil unmountDisk $DEVICE
    }
fi

#######
# git #
#######

# fbr - checkout git branch
# cf. http://bit.ly/34zmzkt
function fbr() {
    local branches branch
    branches=$(git branch -vv) &&
        branch=$(echo "$branches" | fzf +m) &&
        git checkout $(echo "$branch" | awk '{print $1}' | sed "s/.* //")
}

# fbrm - checkout git branch (including remote branches)
# cf. http://bit.ly/34zmzkt
function fbrm() {
    local branches branch
    branches=$(git branch --all | grep -v HEAD) &&
        branch=$(echo "$branches" |
            fzf-tmux -d $((2 + $(wc -l <<<"$branches"))) +m) &&
        git checkout $(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")
}

# fshow - git commit browser
# cf. http://bit.ly/34zmzkt
function fshow() {
    git log --graph --color=always \
        --format="%C(auto)%h%d %s %C(black)%C(bold)%cr" "$@" |
        fzf --ansi --no-sort --reverse --tiebreak=index --bind=ctrl-s:toggle-sort \
            --bind "ctrl-m:execute:
                (grep -o '[a-f0-9]\{7\}' | head -1 |
                xargs -I % sh -c 'git show --color=always % | less -R') << 'FZF-EOF'
                {}
                FZF-EOF"
}

# worktree移動
# cf. http://bit.ly/34zmzkt
function cdworktree() {
    # カレントディレクトリがGitリポジトリ上かどうか
    git rev-parse &>/dev/null
    if [ $? -ne 0 ]; then
        echo fatal: Not a git repository.
        return
    fi

    local selectedWorkTreeDir=$(git worktree list | fzf | awk '{print $1}')

    if [ "$selectedWorkTreeDir" = "" ]; then
        # Ctrl-C.
        return
    fi

    cd ${selectedWorkTreeDir}
}

# interactive 'diff' and 'add'
# cf. http://bit.ly/34GCFZK
fadd() {
    local out q n addfiles
    while out=$(
        git status --short |
            awk '{if (substr($0,2,1) !~ / /) print $2}' |
            fzf-tmux --multi --exit-0 --expect=ctrl-d
    ); do
        q=$(head -1 <<<"$out")
        n=$(($(wc -l <<<"$out") - 1))
        addfiles=($(echo $(tail "-$n" <<<"$out")))
        [[ -z "$addfiles" ]] && continue
        if [ "$q" = ctrl-d ]; then
            git diff --color=always $addfiles | less -R
        else
            git add $addfiles
        fi
    done
}

##########
# docker #
##########

# Select a docker container to start and attach to
function da() {
    local cid
    cid=$(docker ps -a | sed 1d | fzf -1 -q "$1" | awk '{print $1}')

    [ -n "$cid" ] && docker start "$cid" && docker attach "$cid"
}

# Select a running docker container to stop
function ds() {
    local cid
    cid=$(docker ps | sed 1d | fzf -q "$1" | awk '{print $1}')

    [ -n "$cid" ] && docker stop "$cid"
}

# Select a docker container to remove
function drm() {
    local cid
    cid=$(docker ps -a | sed 1d | fzf -q "$1" | awk '{print $1}')

    [ -n "$cid" ] && docker rm "$cid"
}

############
# Homebrew #
############

# Install or open the webpage for the selected application
# using brew cask search as input source
# and display a info quickview window for the currently marked application
install() {
    local token
    token=$(brew search --casks | fzf-tmux --query="$1" +m --preview 'brew cask info {}')

    if [ "x$token" != "x" ]; then
        echo "(I)nstall or open the (h)omepage of $token"
        read input
        if [ $input = "i" ] || [ $input = "I" ]; then
            brew cask install $token
        fi
        if [ $input = "h" ] || [ $input = "H" ]; then
            brew cask home $token
        fi
    fi
}

# Uninstall or open the webpage for the selected application
# using brew list as input source (all brew cask installed applications)
# and display a info quickview window for the currently marked application
uninstall() {
    local token
    token=$(brew cask list | fzf-tmux --query="$1" +m --preview 'brew cask info {}')

    if [ "x$token" != "x" ]; then
        echo "(U)ninstall or open the (h)omepage of $token"
        read input
        if [ $input = "u" ] || [ $input = "U" ]; then
            brew cask uninstall $token
        fi
        if [ $input = "h" ] || [ $token = "h" ]; then
            brew cask home $token
        fi
    fi
}
