#!/bin/zsh
# 外部環境統合 (Modules / ROS / iTerm2)

if [[ -e /usr/local/Modules/init ]]; then
    source /usr/local/Modules/init/zsh
fi

__ros_pick() { # $1=ROS ルート。結果は _ros_setup へ (fork しない)
    local c
    _ros_setup=
    if [[ -n ${ROS_DISTRO-} && -f $1/$ROS_DISTRO/setup.zsh ]]; then
        _ros_setup=$1/$ROS_DISTRO/setup.zsh
        return 0
    fi
    c=("$1"/*/setup.zsh(N-.))
    (($#c == 1)) && _ros_setup=$c[1] # 複数あって ROS_DISTRO も無ければ読まない
    return 0
}
__ros_pick /opt/ros
[[ -n $_ros_setup ]] && source "$_ros_setup"
unfunction __ros_pick
unset _ros_setup

# iTerm2 shell integration
[[ -f "${HOME}/.iterm2_shell_integration.zsh" ]] &&
    source "${HOME}/.iterm2_shell_integration.zsh"

# # for Cline
# # see https://github.com/cline/cline/wiki/Troubleshooting-%E2%80%90-Shell-Integration-Unavailable#still-having-trouble
# [[ "$TERM_PROGRAM" == "vscode" ]] && . "$(code --locate-shell-integration-path zsh)"
