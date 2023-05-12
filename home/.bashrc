#!/bin/bash
#.bash_profile>.bashrc

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

#--------------#
# Bash plugins #
#--------------#

# iTerm2 shell integration
if [[ -e "${HOME}/.iterm2_shell_integration.bash" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.iterm2_shell_integration.bash"
fi

# powerline
if type "powerline-daemon" >/dev/null 2>&1; then
    powerline-daemon -q
    if [ -f "/usr/local/lib/python3.7/site-packages/powerline/bindings/bash/powerline.sh" ]; then
        # shellcheck source=/dev/null
        source "/usr/local/lib/python3.7/site-packages/powerline/bindings/bash/powerline.sh"
    fi
fi

# z: smart completion of the path
# shellcheck source=/dev/null
[[ -f /usr/local/etc/profile.d/z.sh ]] &&
    source /usr/local/etc/profile.d/z.sh

# bash completion
# shellcheck source=/dev/null
[[ -f "/usr/local/etc/profile.d/bash_completion.sh" ]] &&
    source "/usr/local/etc/profile.d/bash_completion.sh"

# fzf
if [ -f "$HOME"/.fzf.bash ]; then
    # shellcheck source=/dev/null
    source "$HOME"/.fzf.bash
    # common settings of fzf
    if [ -f "$HOME"/.config/shell/fzf.sh ]; then
        # shellcheck source=/dev/null
        source "$HOME"/.config/shell/fzf.sh
    fi
fi

if [[ -e "$HOME/.asdf" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.asdf/asdf.sh"
    # shellcheck source=/dev/null
    source "$HOME/.asdf/completions/asdf.bash"
fi
