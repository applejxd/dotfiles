export LANG=ja_JP.UTF-8

#------#
# PATH #
#------#

# The default
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}

# for openssl
if [[ -e "/opt/homebrew/opt/openssl@1.1" ]]; then
  export PATH="/opt/homebrew/opt/openssl@1.1/bin":$PATH
  export LDFLAGS="-L/opt/homebrew/opt/openssl@1.1/lib"
  export CPPFLAGS="-I/opt/homebrew/opt/openssl@1.1/include"
  export PKG_CONFIG_PATH="/usr/local/opt/openssl@1.1/lib/pkgconfig"
fi

#------------#
# BSD -> GNU # 
#------------#

# coreutils
PATH=/usr/local/opt/coreutils/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/coreutils/libexec/gnuman:$MANPATH
# ed
PATH=/usr/local/opt/ed/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/ed/libexec/gnuman:$MANPATH
# findutils
PATH=/usr/local/opt/findutils/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/findutils/libexec/gnuman:$MANPATH
# sed
PATH=/usr/local/opt/gnu-sed/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/gnu-sed/libexec/gnuman:$MANPATH
# tar
PATH=/usr/local/opt/gnu-tar/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/gnu-tar/libexec/gnuman:$MANPATH
# grep
PATH=/usr/local/opt/grep/libexec/gnubin:$PATH
MANPATH=/usr/local/opt/grep/libexec/gnuman:$MANPATH

#---------------#
# Specific root #
#---------------#

# for Maxima
if [[ -e /Applications/wxMaxima.app/ ]]; then
  export PATH=/Applications/wxMaxima.app/bin:$PATH
  export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima
fi
