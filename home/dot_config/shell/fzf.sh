#!/bin/bash

#---------#
# options #
#---------#

# default is **
# export FZF_COMPLETION_TRIGGER=','

export FZF_CTRL_R_OPTS='--sort --exact'

# search command
# see https://qiita.com/kamykn/items/aa9920f07487559c0c7e
if type "rg" >/dev/null 2>&1; then
    export FZF_DEFAULT_COMMAND=(rg --files --hidden --follow --glob "!.git/*")
else
    unset FZF_DEFAULT_COMMAND
fi

# show below, show border, set hight
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# preview by bat, with color, with file name header, with grid
if type "bat" >/dev/null 2>&1; then
    export FZF_CTRL_T_OPTS='--preview "bat --color=always --style=header,grid --line-range :100 {}"'
else
    unset FZF_CTRL_T_OPTS
fi

# preview by tree, with color (enable Japanese)
# see https://wonderwall.hatenablog.com/entry/2017/10/06/063000#--select-1---exit-0
if type "tree" >/dev/null 2>&1; then
    export FZF_ALT_C_OPTS='--preview "tree -C -N {} | head -200" --select-1 --exit-0'
else
    unset FZF_ALT_C_OPTS
fi

#---------#
# wrapper #
#---------#

if type "_z" >/dev/null 2>&1; then
    function xf() {
        local selected_dir
        selected_dir=$(_z -l 2>&1 | fzf +s --tac | sed 's/^[0-9,.]* *//')
        if [[ -n "$selected_dir" ]]; then
            cd "${selected_dir}" || return
        fi
    }
fi

if type "ghq" >/dev/null 2>&1; then
    function xg() {
        local selected_dir
        selected_dir=$(ghq list | fzf)
        if [[ -n "$selected_dir" ]]; then
            cd "$(ghq root)/${selected_dir}" || return
        fi
    }
fi

if type "gwq" >/dev/null 2>&1; then
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

if type "ghq" >/dev/null 2>&1; then
    function mise-select() {
        if [[ -z "$1" ]]; then
            return 1
        fi
        local select_ver
        select_ver=$(mise ls-remote "$1" | sort -rV | fzf)
        mise use "$1@${select_ver}"
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

#-----#
# git #
#-----#

if type "git" >/dev/null 2>&1; then
    # fbr - checkout git branch
    # see http://bit.ly/34zmzkt
    function fbr() {
        local branches branch
        branches=$(git branch -vv) &&
            branch=$(echo "$branches" | fzf +m) &&
            git checkout "$(echo "$branch" | awk '{print $1}' | sed "s/.* //")"
    }

    # fbrm - checkout git branch (including remote branches)
    # see http://bit.ly/34zmzkt
    function fbrm() {
        local branches branch
        branches=$(git branch --all | grep -v HEAD) &&
            branch=$(echo "$branches" |
                fzf-tmux -d $((2 + $(wc -l <<<"$branches"))) +m) &&
            git checkout "$(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")"
    }

    # fshow - git commit browser
    # see http://bit.ly/34zmzkt
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
    # see http://bit.ly/34zmzkt
    function cdworktree() {
        # カレントディレクトリがGitリポジトリ上かどうか
        if ! (git rev-parse &>/dev/null); then
            echo fatal: Not a git repository.
            return
        fi

        local selectedWorkTreeDir
        selectedWorkTreeDir=$(git worktree list | fzf | awk '{print $1}')

        if [[ "$selectedWorkTreeDir" = "" ]]; then
            # Ctrl-C.
            return
        fi

        cd "$selectedWorkTreeDir" || exit
    }

    # interactive 'diff' and 'add'
    # see https://qiita.com/reviry/items/e798da034955c2af84c5
    function fadd() {
        local out input_key select_num selected_files
        # "out" is true except when cancel fzf selection
        # --exit-0: Exit if lenght of the list is 0
        while out=$(git status --short | awk '{if (substr($0,2,1) !~ / /) print $2}' | fzf --exit-0 --expect=ctrl-d); do
            # Use "fzf --expect=KEY" function (see https://www.mankier.com/1/fzf#Options-Scripting)
            input_key=$(echo "$out" | head -1)
            # Arithmetric Expansion
            select_num=$(($(echo "$out" | wc -l) - 1))
            selected_files=$(echo "$out" | tail "-$select_num")
            [[ -z "$selected_files" ]] && continue

            if [ "$input_key" == ctrl-d ]; then
                # Show diff
                git diff --color=always "$selected_files" | less -R
            else
                # When input ENTER
                git add "$selected_files"
            fi
        done
    }
fi

#----------#
# Anaconda #
#----------#

if type "conda" >/dev/null 2>&1; then
    alias condals="conda env list"

    function condarun() {
        local conda_env
        conda_env=$(conda env list | tail -n +3 | head -n -1 | fzf --no-sort | awk '{print $1}')
        [ -n "$conda_env" ] && conda activate "$conda_env"
    }

    function condarm() {
        local conda_env
        conda_env=$(conda env list | tail -n +3 | head -n -1 | fzf --no-sort | awk '{print $1}')
        [ -n "$conda_env" ] && conda env remove -n "$conda_env"
    }
fi

#--------#
# docker #
#--------#

if type "docker" >/dev/null 2>&1; then
    alias dim="docker images"
    alias dls="docker ps -a"
    alias dclean="docker container prune"

    function drun() {
        local cmd
        cmd="docker run -it --rm"

        # GUI 利用
        if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
            # WSL の場合
            cmd="${cmd} -v /mnt/wslg:/mnt/wslg"
        else
            # それ以外
            cmd="${cmd} -e DISPLAY=\"$DISPLAY\" -v /tmp/.X11-unix:/tmp/.X11-unix"
        fi

        # GPU があれば使用
        if type "nvidia-smi" >/dev/null 2>&1; then
            cmd="${cmd} --gpus all"
        fi

        # fzf でファイル名選択
        local name
        name=$(docker images | sed 1d | fzf --no-sort -m --tac | awk '{ print $1 ":" $2 }')

        # it (interactive & tty): stdio
        # rm: remove container that stops
        if [[ -n "$name" ]]; then
            # 追加で指定した引数を使用
            cmd="${cmd} $* $name"

            # for debugging
            # echo "${cmd}"

            # 実行
            eval "${cmd}"
        fi
    }

    function dsh() {
        local cid
        cid=$(docker ps -a | sed 1d | fzf -1 -q "$1" | awk '{print $1}')

        [ -n "$cid" ] && docker exec -it "$cid" /bin/bash
    }

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

    function drmi() {
        docker images | sed 1d | fzf -q "$1" --no-sort -m --tac | awk '{ print $3 }' | xargs -r docker rmi
    }

    # Produce Dockerfile from image
    # see https://qiita.com/RyodoTanaka/items/c7e4889a1b9383291799
    function dmkf() {
        local cid
        cid=$(docker ps -a | sed 1d | fzf -1 -q "$1" | awk '{print $1}')

        [ -n "$cid" ] && docker container commit "$cid" tmp && dfimage.bash tmp >Dockerfile && docker rmi tmp
    }

    function dbuild() {
        local cmd
        cmd="docker build"

        # Dockerfile を選択
        local file_name
        file_name=$(find . -type f | grep -E "./*.(D|d)ockerfile" | fzf)
        cmd="$cmd -f ${file_name}"

        # イメージ名を取得（"./"を削除・拡張子なしファイル名を取得・小文字化）
        local img_name
        img_name=$(echo "$file_name" | sed "s|./||" | awk -F'[.]' '{print $1}' | tr '[:upper:]' '[:lower:]')
        # タグに使う日付文字を取得
        local date_tag
        date_tag=$(date "+%y%m%d")
        cmd="$cmd -t local/${img_name}:${date_tag}"

        if [[ -n "$file_name" ]]; then
            cmd="$cmd $* ."
            eval "${cmd}"
        fi
    }

    function dcom() {
        local file_name
        file_name=$(find ./*.yml | fzf)

        [ -n "$file_name" ] && docker-compose -f "$file_name" up -d
    }
fi

#-------------#
# Singularity #
#-------------#

if type "singularity" >/dev/null 2>&1; then
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
        [ -n "$box_name" ] && sudo singularity shell --nv --writable "$name"
    }

    function brun() {
        local box_name
        box_name=$(find . -maxdepth 1 -type d | fzf)
        [ -n "$box_name" ] && sudo singularity run --nv --writable "$name"
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

if type "brew" >/dev/null 2>&1; then
    # Install or open the webpage for the selected application
    # using brew cask search as input source
    # and display a info quickview window for the currently marked application
    function install() {
        local token
        token=$(brew search --casks | fzf-tmux --query="$1" +m --preview 'brew cask info {}')

        if [ -n "$token" ]; then
            echo "(I)nstall or open the (h)omepage of $token"
            read -r input
            if [ "$input" = "i" ] || [ "$input" = "I" ]; then
                brew cask install "$token"
            fi
            if [ "$input" = "h" ] || [ "$input" = "H" ]; then
                brew cask home "$token"
            fi
        fi
    }

    # Uninstall or open the webpage for the selected application
    # using brew list as input source (all brew cask installed applications)
    # and display a info quickview window for the currently marked application
    function uninstall() {
        local token
        token=$(brew cask list | fzf-tmux --query="$1" +m --preview 'brew cask info {}')

        if [ -n "$token" ]; then
            echo "(U)ninstall or open the (h)omepage of $token"
            read -r input
            if [ "$input" = "u" ] || [ "$input" = "U" ]; then
                brew cask uninstall "$token"
            fi
            if [ "$input" = "h" ] || [ "$token" = "h" ]; then
                brew cask home "$token"
            fi
        fi
    }
fi
