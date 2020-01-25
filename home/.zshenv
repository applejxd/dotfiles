# Unable path_helper from /etc/profile
# cf. http://karur4n.hatenablog.com/entry/2016/01/18/100000
setopt no_global_rcs

COMMON_ENV=$HOME/.config/shell/shellenv.sh

if [ -e $COMMON_ENV ]; then
    source $COMMON_ENV
fi