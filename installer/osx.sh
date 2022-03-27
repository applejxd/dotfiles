#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -sp "Password: " password
else
    password=$1
fi

# for x86_64 architecture
yes A | softwareupdate --install-rosetta

# fzf install
if [ ! -e ~/.fzf.zsh ]; then
    $(brew --prefix)/opt/fzf/install
fi

# iTerm2 Shell integration
if [ ! -e ~/.iterm2_shell_integration.zsh ]; then
    curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash
fi

# LaTeX
if !(type "platex" > /dev/null 2>&1) && (type tlmgr > /dev/null 2>&1); then
    echo "$password" | sudo -S tlmgr update --self --all
    echo "$password" | sudo -S tlmgr paper a4
fi

# # Programming Font Ricty
# if [ ! -e ~/Library/fonts/Ricty\ Discord\ Regular\ for\ Powerline.ttf ]; then
#     cp -f /usr/local/opt/ricty/share/fonts/Ricty*.ttf ~/Library/Fonts/
#     fc-cache -vf
# fi

# # powerline, which needs powerline-font
# if !(type "powerline-daemon" > /dev/null 2>&1); then
#     pip3 install powerline-status
# fi

############
# defaults #
############

# 設定項目一覧
# defaults domain

# 設定値変更の確認
# defaults read > backup.conf
# diff -u backup.conf <(defaults read)

# 設定値の型の確認
# defaults read-type com.apple.AppleMultitouchTrackpad Clicking

# 「タップでクリック」
defaults write com.apple.AppleMultitouchTrackpad Clicking -bool true
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad Clicking -bool true

# 「3本指のトラック」
defaults write com.apple.driver.AppleBluetoothMultitouch.trackpad TrackpadThreeFingerDrag -bool true
defaults write com.apple.AppleMultitouchTrackpad TrackpadThreeFingerDrag -bool true

# 「Dock」->「画面上の位置」->「右」
defaults write com.apple.dock orientation -string left
