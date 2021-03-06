# Unable path_helper from /etc/profile
# cf. http://karur4n.hatenablog.com/entry/2016/01/18/100000
setopt no_global_rcs

##################
# Plugin Manager #
##################

# for importing aliaces to commands by package manager

# if [ -e $SHELL_CONF/zplug.sh ]; then
#     source $SHELL_CONF/zplug.sh
# fi

SHELL_CONF=$HOME/.config/shell
if [ -e $SHELL_CONF/zinit.sh ]; then
    source $SHELL_CONF/zinit.sh
fi

#########################
# Environment variables #
#########################

COMMON_ENV=$HOME/.config/shell/shellenv.sh

if [ -e $COMMON_ENV ]; then
    source $COMMON_ENV
fi