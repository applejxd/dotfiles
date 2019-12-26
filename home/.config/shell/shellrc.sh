###################
# Command Wrapper #
###################

# The default options of "less" command
# cf. https://qiita.com/delphinus/items/b04752bb5b64e6cc4ea9
export LESS="-iMR -gSW -z-4 -x4"

# Reccomended SSH key generation
alias ssh-keygen="ssh-keygen -t ed25519"

# with number: -v
alias dirs="dirs -v"

# "ls" cloning
if type "lsd" >/dev/null 2>&1; then
    alias ls="lsd"
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

alias f="open -a Finder ./"
alias search="find . -type f -print0 | xargs -0 grep -n"

alias up="cd .."
alias upp="cd ../.."
alias uppp="cd ../../.."

alias ll="ls -l"
alias la="ls -a"
alias lla="ls -la"
alias lal="ls -al"
alias lt="ls --tree"

alias web="cd /Applications/MAMP/htdocs/"

# Download mp3 or mp4 from websites
alias audio-dl="youtube-dl --ignore-errors --output '~/Downloads/%(title)s.%(ext)s' --extract-audio --audio-format mp3 --embed-thumbnail"
alias video-dl="youtube-dl --ignore-errors --output '~/Downloads/%(title)s.%(ext)s' --recode-video mp4  --add-metadata"

######################
# original functions #
######################

# From Finder To Terminal
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# cf. https://vivafan.com/2013/03/csh-no-function/
function cdf() {
    target=$(osascript -e 'tell application "Finder" to if (count of Finder windows) > 0 then get POSIX path of (target of front Finder window as text)')
    if [ "$target" != "" ]; then
        cd "$target"
        pwd
    else
        echo 'No Finder window found' >&2
    fi
}

# Search and Move to The Directory
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# cf. http://rksz.hateblo.jp/entry/2012/10/27/201939
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

# Return sha1-type hash from a given argument
# cf. http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function sha1() {
    echo -n "$1" | openssl sha1 | sed "s/^.* //"
}

# for iTerm badge function
# http://bit.ly/2LTeYXt
function badge() {
    printf "\e]1337;SetBadgeFormat=%s\a" \
        $(echo -n "$1" | base64)
}

# for iTerm badge function
# http://bit.ly/2LTeYXt
function ssh_local() {
    local ssh_config=~/.ssh/config
    local server=$(cat $ssh_config | grep "Host " | sed "s/Host //g" | fzf)
    if [ -z "$server" ]; then
        return
    fi
    badge $server
    ssh $server
}