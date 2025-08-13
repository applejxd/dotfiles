#---------------------#
# Terminal Appearance #
#---------------------#

# Not display date after prompt
set -g theme_display_date no

# Use color scheme "solarized"
set -g theme_color_scheme solarized-dark

#----------------------#
# Directory Operations #
#----------------------#

alias f="open ."
alias up="cd .."
alias upp="cd ../.."
alias uppp="cd ../../.."

alias dirs="dirs -v"
alias j="z"

alias web="cd /Applications/MAMP/htdocs/"

function f
    open -a Finder ./
end

# From Finder To Terminal
# http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# https://vivafan.com/2013/03/csh-no-function/
function cdf
    set -l target (osascript -e "tell application "Finder" to if (count of Finder windows) > 0 then get POSIX path of (target of front Finder window as text)")
    if test -d "$target"
        cd "$target"
        pwd
    else
        echo "No Finder window found" >&2
    end
end

# Search and Move to The Directory
# http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
# http://rksz.hateblo.jp/entry/2012/10/27/201939
function jj
    if $argv[1]
        set -l JUMPDIR (find . -type d -maxdepth 1 | grep $argv[1] | tail -1)
        if test -d "$JUMPDIR" &&  test -n "$JUMPDIR"
            cd "$JUMPDIR"
        else
            echo "directory not found"
        end
    end
end

# Remove empty directries up to 2 levels
# http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function cleanup
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
    find . -type d -maxdepth 2 -empty -exec rmdir -v {} \; 2>/dev/null
end

#-----------------#
# Command Rhapper #
#-----------------#

# The default options of "less" command
# https://qiita.com/delphinus/items/b04752bb5b64e6cc4ea9
set -x LESS "-iMR -gSW -z-4 -x4"

# "diff" cloning
if test (which colordiff)
    alias diff="colordiff -u"
else
    alias diff="diff -u"
end

# "cat" cloning
if test (which bat)
    alias cat="bat -p"
end

# "grep" cloning
if test (which ripgrep)
    alias grep="rg"
end

#------------#
# The Others #
#------------#

# Reccomended SSH key generation
alias ssh-keygen="ssh-keygen -t ed25519"

# Restart Terminal
alias relogin="exec $SHELL -l"
alias jnethack="cocot -t UTF-8 -p EUC-JP jnethack"

# Open Emacs on Terminal
alias emacs="emacs -nw"

function ggl
	  open -a /Applications/Google\ Chrome.app  "http://www.google.com/search?q= $argv[1]"
end

# Return sha1-type hash from a given argument
# http://www.rickynews.com/blog/2014/07/19/useful-bash-aliases/
function sha1
	echo -n "$argv[1]" | openssl sha1 | sed "s/^.* //"
end

# English Dictionary on Terminal
function dic
    w3m "http://ejje.weblio.jp/content/$argv[1]" | grep "^[0-9]."
end

# English Dictionary by Chrome
function wdic
    open -a "/Applications/Google Chrome.app" http://ejje.weblio.jp/content/"$argv[1]"
end

# Command Manual
function wman
    open -a "/Applications/Google Chrome.app" https://webkaru.net/linux/"$argv[1]"-command/
end

function audio-dl
    youtube-dl --ignore-errors --output "~/Downloads/%(title)s.%(ext)s" --extract-audio --audio-format mp3 --embed-thumbnail "$argv[1]"
end

function video-dl
    youtube-dl --ignore-errors --output "~/Downloads/%(title)s.%(ext)s" --recode-video mp4  --add-metadata "$argv[1]"
end

# $argv[1] = kind, $argv[2] = string
function search
    find . -type f -name "*.$argv[1]" -print0 | xargs -0 grep -n "$argv[2]"
end

#-----------------------#
# Environment Variables #
#-----------------------#

# PATH configurations
## The default PATH
set -x PATH /usr/local/bin /usr/local/sbin /sw/bin $PATH
## for original binaries
set -x PATH ~/bin $PATH
## for wxMaxima
set -x PATH /Applications/wxMaxima.app/bin $PATH
## for YaTeX
set -x PATH ~/.emacs.d/private/yatex $PATH
## for Haskell package Cabal
set -x PATH ~/.cabal/bin $PATH

# for Japanese man command
set -x LANG ja_JP.UTF-8

# for fzf
## https://wonderwall.hatenablog.com/entry/2017/10/06/063000
## https://qiita.com/kompiro/items/a09c0b44e7c741724c80
set -x FZF_DEFAULT_OPTS "--reverse --border --height 60%"
set -x FZF_CTRL_T_COMMAND "rg --files --hidden --follow --glob '!.git/*'"
set -x FZF_CTRL_T_OPTS "--preview 'bat  --color=always --style=header,grid --line-range :100 {}'"
set -x FZF_ALT_C_OPTS "--preview 'tree -C {} | head -200' --select-1 --exit-0"

# for Maxima
set -x MAXIMA_USERDIR /Applications/wxMaxima.app/.maxima

# for YaTeX
set -x TEXINPUTS ~/.emacs.d/private/yatex $TEXINPUTS
set -x BSTINPUTS ~/.emacs.d/private/yatex $BSTINPUTS
set -x BIBINPUTS ~/Dropbox/bib $BIBINPUTS

# Initialization for FDK command line tools.Fri Jul 29 10:12:14 2016
## for Adobe Font Development Kit for OpenType
set -x PATH "~/bin/FDK/Tools/osx" $PATH
set -x FDK_EXE "~/bin/FDK/Tools/osx"set GHQ_SELECTOR peco
