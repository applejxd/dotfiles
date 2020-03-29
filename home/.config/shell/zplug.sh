###############
# zsh plugins #
###############

# Check if zplug is installed
if [[ ! -d ~/.zplug ]]; then
    git clone https://github.com/zplug/zplug ~/.zplug
    source ~/.zplug/init.zsh && zplug update --self
fi
# Essential
source ~/.zplug/init.zsh

# # init by Homebrew
# source $(brew --prefix)/opt/zplug/init.zsh

# fish-like auto completion
zplug "zsh-users/zsh-autosuggestions"
# completion for non-defalut commands
zplug "zsh-users/zsh-completions"
# Fish like interactive tab completion for cd in zsh
zplug "changyuheng/zsh-interactive-cd", use:zsh-interactive-cd.plugin.zsh, defer:2
# syntax-highlighting to command-line (after compinit)
zplug "zsh-users/zsh-syntax-highlighting", defer:2

# git
zplug "plugins/git", from:oh-my-zsh

# enhance 'cd' command
zplug "b4b4r07/enhancd", use:init.sh
export ENHANCD_COMMAND=ecd

# docker
zplug 'felixr/docker-zsh-completion'
zplug 'mnowotnik/docker-fzf-completion', use:docker-fzf.zsh

################
# Powerlevel9k #
################

# for Linux
export TERM="xterm-256color"

# Apply Nerd-Font
POWERLEVEL9K_MODE='nerdfont-complete'

# Double-Lined Prompt
POWERLEVEL9K_PROMPT_ON_NEWLINE=true
POWERLEVEL9K_RPROMPT_ON_NEWLINE=true
# Turned Arrow
POWERLEVEL9K_MULTILINE_FIRST_PROMPT_PREFIX="%F{blue}\u256D\u2500%F{white}"
POWERLEVEL9K_MULTILINE_LAST_PROMPT_PREFIX="%F{blue}\u2570\uf460%F{white} "
# # Adding Newline Before Each Prompt
# POWERLEVEL9K_PROMPT_ADD_NEWLINE=true

# Segment contents
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(os_icon dir vcs background_jobs)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(command_execution_time status time ram)

# enable zsh theme 'powerlevel9k'
zplug "bhilburn/powerlevel9k", use:powerlevel9k.zsh-theme

#######
# fzf #
#######

# cf. http://bit.ly/2QHO6uS
# cf. (for options) http://bit.ly/2Qi9NTu

# # init by Homebrew
# [ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# init by zplug
zplug "junegunn/fzf-bin", as:command, from:gh-r, rename-to:fzf
zplug "junegunn/fzf", as:command, use:bin/fzf-tmux
zplug "junegunn/fzf", use:shell/key-bindings.zsh
zplug "junegunn/fzf", use:shell/completion.zsh

zplug "rupa/z", use:z.sh

###################
# zplug installer #
###################

# Install packages that have not been installed yet
if ! zplug check --verbose; then
    printf "Install? [y/N]: "
    if read -q; then
        echo; zplug install
    fi
fi

# Then, source plugins and add commands to $PATH
zplug load --verbose
