#!/bin/bash

#--------#
# system #
#--------#

# Windows System
export PATH="/mnt/c/Windows${PATH:+:${PATH}}" # for explorer.exe
export PATH="/mnt/c/Windows/System32:$PATH"   # for clip.exe

# Powershell
export PATH="/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH"

# VSCode (for system installation, fallback to user installation)
if [[ -d "/mnt/c/Progra~1/Microsoft VS Code" ]]; then
    export PATH="/mnt/c/Progra~1/Microsoft VS Code/bin:$PATH"
else
    _win_user=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
    _vscode_path="/mnt/c/Users/${_win_user}/AppData/Local/Programs/Microsoft VS Code"
    if [[ -n "$_win_user" ]] && [[ -d "$_vscode_path" ]]; then
        export PATH="$_vscode_path/bin:$PATH"
    fi
    unset _win_user _vscode_path
fi

# for GPU drivers
export LD_LIBRARY_PATH="/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

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
    if [[ "$(uname -r)" == *WSL2 ]]; then
        # for WSL2
        DISPLAY=$(grep nameserver </etc/resolv.conf | awk '{print $2}'):0.0
    else
        # for WSL1
        DISPLAY=:0.0
    fi
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

if [[ "$SHLVL" = 1 ]]; then
    (fcitx-autostart >/dev/null 2>&1 &)
    xset -r 49 >/dev/null 2>&1
fi

#-----#
# dev #
#-----#

# Java
if [[ -e /usr/lib/jvm/java-11-openjdk-amd64 ]]; then
    export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
    export PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH
    export CLASSPATH=.:/usr/lib/jvm/java-11-openjdk-amd64/lib
fi
