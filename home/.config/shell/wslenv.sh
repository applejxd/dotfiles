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
