############
# Homebrew #
############

# Homebrew for linux
if [[ "$OSTYPE" == "linux-gnu" ]]; then
    eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
fi

###################
# Command Wrapper #
###################

# The default options of "less" command
# cf. https://qiita.com/delphinus/items/b04752bb5b64e6cc4ea9
export LESS="-iMR -gSW -z-4 -x4"

# for security
alias ssh-keygen="ssh-keygen -t ed25519"

# with number: -v
alias dirs="dirs -v"

# adding git syntax sugar
eval "$(hub alias -s)"

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

# pbcopy & pbpaste
if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ]; then
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
    if [ $1 ]; then
        JUMPDIR=$(find . -type d -maxdepth 1 | grep $1 | tail -1)
        if [[ -d $JUMPDIR && -n $JUMPDIR ]]; then
            cd $JUMPDIR
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
            cd "$target"
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
            $(echo -n "$1" | base64)
    }

    function ssh_local() {
        local ssh_config=~/.ssh/config
        local server=$(cat $ssh_config | grep "Host " | sed "s/Host //g" | fzf)
        if [ -z "$server" ]; then
            return
        fi
        badge $server
        ssh $server
    }
fi
