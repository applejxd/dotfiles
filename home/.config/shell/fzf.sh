###########
# options #
###########

# default is **
# export FZF_COMPLETION_TRIGGER=','

export FZF_CTRL_R_OPTS='--sort --exact'

# search command
# cf. https://qiita.com/kamykn/items/aa9920f07487559c0c7e
if type "rg" >/dev/null 2>&1; then
    export FZF_DEFAULT_COMMAND='rg --files --hidden --follow --glob "!.git/*"'
fi

# show below, show border, set hight
export FZF_DEFAULT_OPTS='--layout=reverse --border --height 60%'
# preview by bat, with color, with file name header, with grid
if type "bat" >/dev/null 2>&1; then
    export FZF_CTRL_T_OPTS='--preview "bat --color=always --style=header,grid --line-range :100 {}"'
fi

# preview by tree, with color (enable Japanese)
# cf. https://wonderwall.hatenablog.com/entry/2017/10/06/063000#--select-1---exit-0
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
    if [ "$wc" -ne 0 ]; then
        job=$(jobs | awk -F "suspended" "{print $1 $2}" | sed -e "s/\-//g" -e "s/\+//g" -e "s/\[//g" -e "s/\]//g" | grep -v pwd | fzf | awk "{print $1}")
        wc_grep=$(echo "$job" | grep -v grep | grep 'suspended')
        if [ "$wc_grep" != "" ]; then
            fg %"$job"
        fi
    fi
}

# v - open files in ~/.viminfo
v() {
    local files
    files=$(grep '^>' ~/.viminfo | cut -c3- | 
        while read -r line; do
            [ -f "${line/\~/$HOME}" ] && echo "$line"
        done | fzf -d -m -q "$*" -1) && vim "${files//\~/$HOME}"
}

# cf. http://bit.ly/37GNSLZ
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

function fsh() {
    local shell
    shell=$(sed -e "1d" < /etc/shells | fzf -q "$1")
    $shell
}

#######
# git #
#######

if type "git" >/dev/null 2>&1; then
    # fbr - checkout git branch
    # cf. http://bit.ly/34zmzkt
    function fbr() {
        local branches branch
        branches=$(git branch -vv) &&
            branch=$(echo "$branches" | fzf +m) &&
            git checkout "$(echo "$branch" | awk '{print $1}' | sed "s/.* //")"
    }

    # fbrm - checkout git branch (including remote branches)
    # cf. http://bit.ly/34zmzkt
    function fbrm() {
        local branches branch
        branches=$(git branch --all | grep -v HEAD) &&
            branch=$(echo "$branches" |
                fzf-tmux -d $((2 + $(wc -l <<<"$branches"))) +m) &&
            git checkout "$(echo "$branch" | sed "s/.* //" | sed "s#remotes/[^/]*/##")"
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
    # cf. https://qiita.com/reviry/items/e798da034955c2af84c5
    function fadd() {
        local out input_key select_num selected_files
        # "out" is true except when cancel fzf selection
        # --exit-0: Exit if lenght of the list is 0
        while out=$(git status --short | awk '{if (substr($0,2,1) !~ / /) print $2}' | fzf --exit-0 --expect=ctrl-d)
        do
            # Use "fzf --expect=KEY" function (cf. https://www.mankier.com/1/fzf#Options-Scripting)
            input_key=$(echo "$out" | head -1)
            # Arithmetric Expansion
            select_num=$(( $(echo "$out" | wc -l) - 1))
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

############
# Anaconda #
############

if type "conda" >/dev/null 2>&1; then
    alias cls="conda env list"

    function cact() {
        local conda_env
        conda_env=$(conda env list | tail -n +3 | fzf --no-sort | awk '{print $1}')
        conda activate "$conda_env" 
    }

    function crm() {
        local conda_env
        conda_env=$(conda env list | tail -n +3 | fzf --no-sort | awk '{print $1}')
        conda env remove -n "$conda_env"
    }
fi

##########
# docker #
##########

if type "docker" >/dev/null 2>&1; then
    alias dim="docker images"

    function drun() {
        local name
        name=$(docker images | sed 1d | fzf --no-sort -m --tac | awk '{ print $1 ":" $2 }')

        # it (interactive & tty): stdio
	# rm: remove container that stops
        [ -n "$name" ] && docker run -it --rm --gpus all -e DISPLAY="$DISPLAY" "$@" "$name"
    }

    alias dls="docker ps -a"

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
    # cf. https://qiita.com/RyodoTanaka/items/c7e4889a1b9383291799
    function dmkf() {
        local cid
        cid=$(docker ps -a | sed 1d | fzf -1 -q "$1" | awk '{print $1}')

        [ -n "$cid" ] && docker container commit "$cid" tmp && dfimage.bash tmp > Dockerfile && docker rmi tmp
    }
    
    function dbuild() {
    	local file_name
        file_name=$(find ./*.dockerfile | sed "s|\.\/|| | fzf)
         
	    local date_tag
	    date_tag=$(date "+%y.%m.%d")
        [ -n "$file_name" ] && docker build -t local/"$file_name":"$date_tag" -f "$file_name" .
    }
    
    function dcom() {
        local file_name
        file_name=$(find ./*.yml | fzf)

    	    [ -n "$file_name" ] && docker-compose -f "$file_name" up -d
    }
fi

###############
# Singularity #
###############

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

############
# Homebrew #
############

if type "brew" >/dev/null 2>&1; then
    # Install or open the webpage for the selected application
    # using brew cask search as input source
    # and display a info quickview window for the currently marked application
    function install() {
        local token
        token=$(brew search --casks | fzf-tmux --query="$1" +m --preview 'brew cask info {}')

        if [ "x$token" != "x" ]; then
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

        if [ "x$token" != "x" ]; then
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
