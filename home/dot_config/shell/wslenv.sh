#!/bin/bash

#--------#
# system #
#--------#

# 入れ子のシェルで読み直しても重複させない
_wsl_path_prepend() {
    case ":${PATH}:" in
    *":$1:"*) ;;
    *) export PATH="$1${PATH:+:${PATH}}" ;;
    esac
}

# Windows System
_wsl_path_prepend "/mnt/c/Windows"          # for explorer.exe
_wsl_path_prepend "/mnt/c/Windows/System32" # for clip.exe

# Powershell (5.1 は常にある。7 は winget で入れたときだけ)
_wsl_path_prepend "/mnt/c/Windows/System32/WindowsPowerShell/v1.0"
[[ -d "/mnt/c/Program Files/PowerShell/7" ]] && _wsl_path_prepend "/mnt/c/Program Files/PowerShell/7"

# VSCode (for system installation, fallback to user installation)
if [[ -d "/mnt/c/Progra~1/Microsoft VS Code" ]]; then
    _wsl_path_prepend "/mnt/c/Progra~1/Microsoft VS Code/bin"
else
    _win_user_cache="$HOME/.cache/win_user"
    if [[ -f "$_win_user_cache" ]]; then
        _win_user=$(<"$_win_user_cache")
    else
        _win_user=""
        if command -v cmd.exe >/dev/null 2>&1; then
            _win_user=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null </dev/null | tr -d '\r') || _win_user=""
        fi
        # 空値はキャッシュしない (interop 無効時に以後ずっと探さなくなる)
        if [[ -n "$_win_user" ]] && mkdir -p "$HOME/.cache" 2>/dev/null; then
            echo "$_win_user" >"$_win_user_cache" 2>/dev/null || true
        fi
    fi
    _vscode_path="/mnt/c/Users/${_win_user}/AppData/Local/Programs/Microsoft VS Code"
    if [[ -n "$_win_user" ]] && [[ -d "$_vscode_path" ]]; then
        _wsl_path_prepend "$_vscode_path/bin"
    fi
    unset _win_user _vscode_path
fi

# for GPU drivers
case ":${LD_LIBRARY_PATH:-}:" in
*":/usr/lib/wsl/lib:"*) ;;
*) export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ;;
esac

# Browser
export BROWSER="wslview"

#-----#
# GUI #
#-----#

# To prevent OpenGL error
export LIBGL_ALWAYS_INDIRECT=0

# use default value if DISPLAY is set (e.g. SSH X11Forwarding)
if [[ -z "$DISPLAY" ]]; then
    # for VcXsrv
    read -r _osrelease </proc/sys/kernel/osrelease 2>/dev/null || _osrelease=""
    if [[ "$_osrelease" == *WSL2 ]]; then
        # for WSL2 (外部プロセスを起こさず resolv.conf の最初の nameserver を読む)
        _ns=""
        while read -r _key _val _; do
            if [[ "$_key" == nameserver ]]; then
                _ns="$_val"
                break
            fi
        done </etc/resolv.conf
        DISPLAY="${_ns}:0.0"
        unset _ns _key _val
    else
        # for WSL1
        DISPLAY=:0.0
    fi
    unset _osrelease
    export DISPLAY
fi

#-----------#
# Japansese #
#-----------#

# see https://astherier.com/blog/2020/08/install-fcitx-mozc-on-wsl2-ubuntu2004/#
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export DefaultIMModule=fcitx
# fcitx-autostart / xset は対話シェルだけ (shellrc.sh.tmpl)

#-----#
# dev #
#-----#

# Java
if [[ -e /usr/lib/jvm/java-11-openjdk-amd64 ]]; then
    export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
    _wsl_path_prepend /usr/lib/jvm/java-11-openjdk-amd64/bin
    export CLASSPATH=.:/usr/lib/jvm/java-11-openjdk-amd64/lib
fi

# 共通 env には関数を残さない (docs/spec/structure.md の起動契約)
unset -f _wsl_path_prepend
