# To prevent OpenGL error
export LIBGL_ALWAYS_INDIRECT=1

# for VcXsrv
if [[ "$(uname -r)" == *WSL2 ]]; then
    # for WSL2
    export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0.0
else
    # for WSL1
    export DISPLAY=:0.0
fi

# Windows System
export PATH=/mnt/c/Windows:$PATH            # for explorer.exe
export PATH=/mnt/c/Windows/System32:$PATH   # for clip.exe

# Powershell
export PATH=/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH

# VSCode
export PATH=/mnt/c/Progra~1/"Microsoft VS Code"/bin:$PATH

# Java
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH
export CLASSPATH=.:/usr/lib/jvm/java-11-openjdk-amd64/lib