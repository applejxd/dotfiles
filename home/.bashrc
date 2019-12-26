#################
# common config #
#################

COMMON_RC=$HOME/.config/shell/shellrc.sh

if [ -e $COMMON_RC ]; then
    source $COMMON_RC
fi

###############
# Bash plugins #
###############

# powerline
powerline-daemon -q
. /usr/local/lib/python3.7/site-packages/powerline/bindings/bash/powerline.sh

# z: smart completion of the path
. $(brew --prefix)/etc/profile.d/z.sh
alias j='z'

# bash completion
[[ -r "/usr/local/etc/profile.d/bash_completion.sh" ]] &&
. "/usr/local/etc/profile.d/bash_completion.sh"

# fzf
[ -f ~/.fzf.bash ] && source ~/.fzf.bash

COMMON_FZF=$HOME/.config/shell/fzf.sh

if [ -e $COMMON_RC ]; then
    source $COMMON_FZF
fi