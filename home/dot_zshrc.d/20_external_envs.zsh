#!/bin/zsh
# 外部環境統合 (Modules / ROS / iTerm2)

if [[ -e /usr/local/Modules/init ]]; then
    source /usr/local/Modules/init/zsh
fi

if [[ -e /opt/ros ]]; then
    ros_dir=$(find /opt/ros -mindepth 1 -maxdepth 1 -type d | head -n 1)
    source "${ros_dir}/setup.zsh"
fi

# iTerm2 shell integration
[[ -f "${HOME}/.iterm2_shell_integration.zsh" ]] &&
    source "${HOME}/.iterm2_shell_integration.zsh"

# # for Cline
# # see https://github.com/cline/cline/wiki/Troubleshooting-%E2%80%90-Shell-Integration-Unavailable#still-having-trouble
# [[ "$TERM_PROGRAM" == "vscode" ]] && . "$(code --locate-shell-integration-path zsh)"
