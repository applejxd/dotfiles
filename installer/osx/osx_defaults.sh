#!/bin/bash

if [ $# -eq 0 ]; then
    # save password
    read -rsp "Password: " password
else
    password=$1
fi

# 起動時の音をミュート
echo "$password" | sudo -S nvram StartupMute=%01

#----------#
# defaults #
#----------#

# see https://github.com/ulwlu/dotfiles/blob/master/system/macos.sh

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

# 「メニューバーに Bluetooth を表示」
defaults write com.apple.controlcenter "NSStatusItem Visible Bluetooth" -bool true
defaults write ~/Library/Preferences/ByHost/com.apple.controlcenter.plist Bluetooth -int 18

# 「メニューバーにサウンドを表示」
defaults write com.apple.controlcenter "NSStatusItem Visible Sound" -bool true
defaults write ~/Library/Preferences/ByHost/com.apple.controlcenter.plist Sound -int 18

killall SystemUIServer

# 「新規 Finder ウィンドウでホームを表示」
# see https://gist.github.com/ChristopherA/98628f8cd00c94f11ee6035d53b0d3c6
defaults write com.apple.finder NewWindowTarget -string "PfHm"

killall Finder

# 「"Siri に頼む"を無効にする」
defaults write com.apple.assistant.support.plist "Assistant Enabled" -bool false
# 「メニューバーに Siri を非表示」
defaults write com.apple.Siri StatusMenuVisible -bool false

# 「Dock」->「画面上の位置」->「右」
defaults write com.apple.dock orientation -string left
killall Dock

# 「Mac を自動的に最新の状態に保つ」
# defaults write com.apple.SoftwareUpdate ScheduleFrequency -int 1

# 「ファイアウォールをオンにする」
echo "$password" | sudo -S defaults write /Library/Preferences/com.apple.alf globalstate -int 1
