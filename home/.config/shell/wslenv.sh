# To prevent OpenGL error
export LIBGL_ALWAYS_INDIRECT=1

# for VcXsrv
if [[ -e /etc/resolv.conf ]]; then
    # for WSL2
    export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0.0
else
    # for WSL1
    export DISPLAY=:0.0
fi

# Windows System
export PATH=/mnt/c/Windows:$PATH
export PATH=/mnt/c/Windows/System32:$PATH
export PATH=/mnt/c/Windows/System32/WindowsPowerShell/v1.0:$PATH

# Java
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH
export CLASSPATH=.:/usr/lib/jvm/java-11-openjdk-amd64/lib