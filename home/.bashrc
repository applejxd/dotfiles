#################
# common config #
#################

if [ -f $HOME/.config/shell/shellrc.sh ]; then
    source $HOME/.config/shell/shellrc.sh
fi

###########
# options #
###########

# for latest bash
# cf. http://bit.ly/2Sts1CU
# cf. http://bit.ly/2MvLSgX

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

################
# Bash plugins #
################

# iTerm2 shell integration
test -e "${HOME}/.iterm2_shell_integration.bash" &&
source "${HOME}/.iterm2_shell_integration.bash" || true

# powerline
if type "powerline-daemon" >/dev/null 2>&1; then
    powerline-daemon -q
    POWERLINE_PATH=/usr/local/lib/python3.7/site-packages/powerline/bindings/bash/powerline.sh
    if [ -f $POWERLINE_PATH ]; then
        source $POWERLINE_PATH
    fi
fi

# z: smart completion of the path
[[ -f /usr/local/etc/profile.d/z.sh ]] &&
source /usr/local/etc/profile.d/z.sh

# bash completion
[[ -f "/usr/local/etc/profile.d/bash_completion.sh" ]] &&
source "/usr/local/etc/profile.d/bash_completion.sh"

# fzf
if [ -f ~/.fzf.bash ]; then
    source ~/.fzf.bash
    # common settings of fzf
    if [ -f $HOME/.config/shell/fzf.sh ]; then
        source $HOME/.config/shell/fzf.sh
    fi
fi