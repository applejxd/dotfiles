# #!/bin/bash
# #.bash_profile>.bashrc

#---------------#
# common config #
#---------------#

if [ -f "$HOME"/.config/shell/shellrc.sh ]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/shellrc.sh
fi

#---------#
# options #
#---------#

# for latest bash
# see https://ozuma.hatenablog.jp/entry/20141219/1418915137
# see https://geek-techiela.blogspot.com/2014/07/shoptbash.html

# no cd
shopt -s autocd
# fuzzy cd
shopt -s cdspell
# dotfiles match
shopt -s dotglob
# regexp enable
shopt -s extglob
# '**'' recursive match
shopt -s globstar
# not to distinguish between uppercase and lowercase
shopt -s nocaseglob

#-------------#
# activations #
#-------------#

# mise
if [[ -e "$HOME/.local/bin/mise" ]]; then
    eval "$(~/.local/bin/mise activate bash)"
fi

# for Cline
# see https://github.com/cline/cline/wiki/Troubleshooting-%E2%80%90-Shell-Integration-Unavailable#still-having-trouble
[[ "$TERM_PROGRAM" == "vscode" ]] && . "$(code --locate-shell-integration-path bash)"

# z: smart completion of the path
# shellcheck source=/dev/null
[[ -f /usr/local/etc/profile.d/z.sh ]] &&
    source /usr/local/etc/profile.d/z.sh

# bash completion
# shellcheck source=/dev/null
[[ -f "/usr/local/etc/profile.d/bash_completion.sh" ]] &&
    source "/usr/local/etc/profile.d/bash_completion.sh"

# fzf
# shellcheck source=/dev/null
[ -f "$HOME"/.fzf.bash ] && source "$HOME"/.fzf.bash
if [ -f "$HOME"/.fzf.bash ]; then
    # shellcheck source=/dev/null
    source "$HOME"/.fzf.bash
    # common settings of fzf
fi

if type "fzf" >/dev/null 2>&1 && [ -f "$HOME"/.config/shell/fzf.sh ]; then
    # shellcheck source=/dev/null
    source "$HOME"/.config/shell/fzf.sh
fi

# ROS2
if [[ -e /opt/ros ]]; then
    ros_dir=$(find /opt/ros -mindepth 1 -maxdepth 1 -type d | head -n 1)
    # shellcheck source=/dev/null
    source "${ros_dir}/setup.bash"
fi

# iTerm2 shell integration
if [[ -e "${HOME}/.iterm2_shell_integration.bash" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.iterm2_shell_integration.bash"
fi

#---------#
# bash-it #
#---------#

if [ ! -e "$HOME"/.bash_it ]; then
    git clone --depth=1 https://github.com/Bash-it/bash-it.git "$HOME"/.bash_it
fi

# If not running interactively, don't do anything
case $- in
*i*) ;;
*) return ;;
esac

# Path to the bash it configuration
export BASH_IT="$HOME/.bash_it"

# Lock and Load a custom theme file.
# Leave empty to disable theming.
# location /.bash_it/themes/
export BASH_IT_THEME='pure'

# Some themes can show whether `sudo` has a current token or not.
# Set `$THEME_CHECK_SUDO` to `true` to check every prompt:
#THEME_CHECK_SUDO='true'

# (Advanced): Change this to the name of your remote repo if you
# cloned bash-it with a remote other than origin such as `bash-it`.
# export BASH_IT_REMOTE='bash-it'

# (Advanced): Change this to the name of the main development branch if
# you renamed it or if it was changed for some reason
# export BASH_IT_DEVELOPMENT_BRANCH='master'

# Your place for hosting Git repos. I use this for private repos.
export GIT_HOSTING='git@git.domain.com'

# Don't check mail when opening terminal.
unset MAILCHECK

# Change this to your console based IRC client of choice.
export IRC_CLIENT='irssi'

# Set this to the command you use for todo.txt-cli
export TODO="t"

# Set this to the location of your work or project folders
#BASH_IT_PROJECT_PATHS="${HOME}/Projects:/Volumes/work/src"

# Set this to false to turn off version control status checking within the prompt for all themes
export SCM_CHECK=true
# Set to actual location of gitstatus directory if installed
#export SCM_GIT_GITSTATUS_DIR="$HOME/gitstatus"
# per default gitstatus uses 2 times as many threads as CPU cores, you can change this here if you must
#export GITSTATUS_NUM_THREADS=8

# Set Xterm/screen/Tmux title with only a short hostname.
# Uncomment this (or set SHORT_HOSTNAME to something else),
# Will otherwise fall back on $HOSTNAME.
#export SHORT_HOSTNAME=$(hostname -s)

# Set Xterm/screen/Tmux title with only a short username.
# Uncomment this (or set SHORT_USER to something else),
# Will otherwise fall back on $USER.
#export SHORT_USER=${USER:0:8}

# If your theme use command duration, uncomment this to
# enable display of last command duration.
#export BASH_IT_COMMAND_DURATION=true
# You can choose the minimum time in seconds before
# command duration is displayed.
#export COMMAND_DURATION_MIN_SECONDS=1

# Set Xterm/screen/Tmux title with shortened command and directory.
# Uncomment this to set.
#export SHORT_TERM_LINE=true

# Set vcprompt executable path for scm advance info in prompt (demula theme)
# https://github.com/djl/vcprompt
#export VCPROMPT_EXECUTABLE=~/.vcprompt/bin/vcprompt

# (Advanced): Uncomment this to make Bash-it reload itself automatically
# after enabling or disabling aliases, plugins, and completions.
# export BASH_IT_AUTOMATIC_RELOAD_AFTER_CONFIG_CHANGE=1

# Uncomment this to make Bash-it create alias reload.
# export BASH_IT_RELOAD_LEGACY=1

# Load Bash It
# shellcheck source=/dev/null
source "$BASH_IT"/bash_it.sh
