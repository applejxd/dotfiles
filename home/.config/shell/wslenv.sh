#!/bin/bash

# for GPU drivers
export LD_LIBRARY_PATH=/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}

# To prevent OpenGL error
export LIBGL_ALWAYS_INDIRECT=1

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

# Windows System
export PATH=/mnt/c/Windows${PATH:+:${PATH}} # for explorer.exe
export PATH=/mnt/c/Windows/System32:$PATH   # for clip.exe

# Powershell
export PATH=/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH

# VSCode (for system installation)
if [[ -e /mnt/c/Progra~1/"Microsoft VS Code" ]]; then
    export PATH=/mnt/c/Progra~1/"Microsoft VS Code"/bin:$PATH
fi

# Java
if [[ -e /usr/lib/jvm/java-11-openjdk-amd64 ]]; then
    export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
    export PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH
    export CLASSPATH=.:/usr/lib/jvm/java-11-openjdk-amd64/lib
fi
