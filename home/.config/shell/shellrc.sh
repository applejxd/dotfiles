###################
# OS dependencies #
###################

# # Homebrew for linux
# if [[ "$OSTYPE" == "linux-gnu" ]]; then
#     eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
# fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    arch=$(uname -m)

    brew_path=""
    if [[ $arch == arm64 ]]; then
        echo "Current Architecture: $arch"
        brew_path="/opt/homebrew/bin/brew"
    elif [[ $arch == x86_64 ]]; then
        echo "Current Architecture: $arch"
        brew_path="/usr/local/bin/brew"
    fi

    if [[ -e $brew_path ]]; then
        eval "$($brew_path shellenv)"
    fi

    alias x64='exec arch -x86_64 /bin/zsh'
	alias a64='exec arch -arm64e /bin/zsh'
fi

##################
# Initialization #
##################

if type "anyenv" >/dev/null 2>&1; then
    # anyenv for rbenv, nodenv, phpenv
    eval "$(anyenv init - zsh)"

    if type "pyenv" >/dev/null 2>&1; then
        eval "$(pyenv init -)"
    fi
fi

# iceberg theme for vim
if type "ghq" >/dev/null 2>&1; then
    if [[ ! -e  $GHQ_ROOT/github.com/cocopon/iceberg.vim ]]; then
        ghq get https://github.com/cocopon/iceberg.vim.git
    fi
    if [[ ! -e $HOME/.vim/colors ]]; then
            mkdir -p "$HOME"/.vim/colors
    fi
    if [[ ! -L $HOME/.vim/colors/iceberg.vim ]]; then
    	ln -s "$GHQ_ROOT"/github.com/cocopon/iceberg.vim/colors/iceberg.vim "$HOME"/.vim/colors/iceberg.vim
    fi
fi

###################
# Command Wrapper #
###################

# The default options of "less" command
# cf. https://tinyurl.com/y8q7xwl9
export LESS="-iMR -gSW -z-4 -x4"

# X11 forwarding
alias ssh="ssh -X"

# with number: -v
alias dirs="dirs -v"

# adding git syntax sugar
if type "hub" >/dev/null 2>&1; then
    eval "$(hub alias -s)"
fi

# "ls" cloning
if type "lsd" >/dev/null 2>&1; then
    alias ls="lsd"
else
    if [[ "$OSTYPE" == "darwin"* ]]; then
        alias ls="ls -G"
    elif [[ "$OSTYPE" == "linux-gnu" ]]; then
        alias ls="ls --color=auto"
    fi
fi

# "cat" cloning
if type "bat" >/dev/null 2>&1; then
    alias cat="bat"
fi

# "diff" cloning & unified format: -u
if type "colordiff" >/dev/null 2>&1; then
    alias diff="colordiff -u"
else
    alias diff="diff -u"
fi

# # brew -> brew-wrap  by Homebrew-file
# if [ -f $(brew --prefix)/etc/brew-wrap ]; then
#     source $(brew --prefix)/etc/brew-wrap
# fi

alias jnethack="cocot -t UTF-8 -p EUC-JP jnethack"

##################
# original alias #
##################

# Restart Terminal
alias relogin="exec $SHELL -l"

alias up="cd .."
alias upp="cd ../.."
alias uppp="cd ../../.."

alias ll="ls -l"
alias la="ls -a"
alias lla="ls -la"
alias lal="ls -al"
alias lt="ls --tree"

# for security
alias gen-key="ssh-keygen -t ed25519 -P \"\""

# pbcopy & pbpaste
if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    alias pbcopy='clip.exe'
    alias pbpaste='powershell.exe Get-Clipboard' 
elif [[ "$OSTYPE" == "linux-gnu" ]]; then
    alias pbcopy='xsel --clipboard --input'
    alias pbpaste='xsel --clipboard --output'
fi
# count the number of characters
alias wcc="pbpaste | wc -m"
# clear format
alias fcr="pbpaste | pbcopy"

if [[ "$(uname -r)" =~ (M|m)icrosoft ]]; then
    alias open="explorer.exe"
elif [[ -e /etc/lsb-release ]]; then
    alias open="xdg-open"
fi

alias search="find . -type f -print0 | xargs -0 grep -n"

# Download mp3 or mp4 from websites
if type "youtube-dl" >/dev/null 2>&1; then
    alias audio-dl="youtube-dl --ignore-errors \
                    --output '~/Downloads/%(title)s.%(ext)s' \
                    --extract-audio --audio-format mp3 \
                    --embed-thumbnail"
    alias video-dl="youtube-dl --ignore-errors \
                    --output '~/Downloads/%(title)s.%(ext)s' \
                    --recode-video mp4  --add-metadata"
fi

# for Mac OS X
if [[ "$OSTYPE" == "darwin"* ]]; then
    alias web="cd /Applications/MAMP/htdocs/"
fi

######################
# original functions #
######################

# Search and Move to The Directory
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# cf. http://rksz.hateblo.jp/entry/2014/10/27/201939
function jj() {
    if [[ "$1" ]]; then
        JUMPDIR=$(find . -type d -maxdepth 1 | grep "$1" | tail -1)
        if [[ -d $JUMPDIR && -n $JUMPDIR ]]; then
            cd "$JUMPDIR" || exit
        else
            echo "directory not found"
        fi
    fi
}

# Remove empty directries up to 2 levels
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function cleanup() {
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
}

# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function sha1() {
    echo -n "$1" | openssl sha1 | sed "s/^.* //"
}
alias sha2="openssl passwd -6 -salt 'SALTsalt'"

# Finder functions for OS X
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# cf. https://vivafan.com/2013/03/csh-no-function/
if [[ "$OSTYPE" == "darwin"* ]]; then
    alias f="open -a Finder ./"
    function cdf() {
        target=$(osascript -e 'tell application "Finder" to if (count of Finder windows) > 0 then get POSIX path of (target of front Finder window as text)')
        if [ "$target" != "" ]; then
            cd "$target" || exit
            pwd
        else
            echo 'No Finder window found' >&2
        fi
    }
fi

# for iTerm badge function
# http://bit.ly/2LTeYXt
if [ -e ~/.iterm2_shell_integration.zsh ]; then
    function badge() {
        printf "\e]1337;SetBadgeFormat=%s\a" \
            "$(echo -n "$1" | base64)"
    }

    function ssh_local() {
        local ssh_config=~/.ssh/config
        local server
        server=$(cat $ssh_config | grep "Host " | sed "s/Host //g" | fzf)
        if [ -z "$server" ]; then
            return
        fi
        badge "$server"
        ssh "$server"
    }
fi


##################
# zsh registered #
##################

# fg -> C-z
function fancy-ctrl-z() {
    if [[ $#BUFFER -eq 0 ]]; then
        BUFFER="fg"
        # Finish editing the buffer
        zle accept-line
    else
        # Push onto the buffer stack & Return to prompt
        zle push-input
        # Clear the screen
        zle clear-screen
    fi
}

function switch-arch() {
    if  [[ "$(uname -m)" == arm64 ]]; then
        arch=x86_64
    elif [[ "$(uname -m)" == x86_64 ]]; then
        arch=arm64e
    fi
    exec arch -arch $arch /bin/zsh
}

# unarchive
# cf. http://bit.ly/2tCOvHP
function extract() {
    case $1 in
    *.tar.gz | *.tgz) tar xzvf "$1" ;;
    *.tar.xz) tar Jxvf "$1" ;;
    *.zip) unzip "$1" ;;
    *.lzh) lha e "$1" ;;
    *.tar.bz2 | *.tbz) tar xjvf "$1" ;;
    *.tar.Z) tar zxvf "$1" ;;
    *.gz) gzip -d "$1" ;;
    *.bz2) bzip2 -dc "$1" ;;
    *.Z) uncompress "$1" ;;
    *.tar) tar xvf "$1" ;;
    *.arj) unarj "$1" ;;
    esac
}

# compile
# cf. http://bit.ly/2tCOvHP
function runcpp() {
    fname=$(echo "$1" | awk -F/ '{print $NF}' | awk -F. '{print $1}')
    g++ -O2 -Wall -Wextra "$1" -o "$fname"
    shift
    ./"$fname" "$@"
}
