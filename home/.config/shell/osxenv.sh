export LANG=ja_JP.UTF-8

########
# PATH #
########

# The default
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}

# for openssl
export PATH="/opt/homebrew/opt/openssl@1.1/bin:$PATH"

#################
# Specific root #
#################

# for openssl
export LDFLAGS="-L/opt/homebrew/opt/openssl@1.1/lib"
export CPPFLAGS="-I/opt/homebrew/opt/openssl@1.1/include"
export PKG_CONFIG_PATH="/usr/local/opt/openssl@1.1/lib/pkgconfig"

# for Maxima
if [[ -e /Applications/wxMaxima.app/ ]]; then
  export PATH=/Applications/wxMaxima.app/bin:$PATH
  export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima
fi

# Initialization for FDK command line tools.Fri Jul 29 10:12:14 2016
## for Adobe Font Development Kit for OpenType
export PATH=~/bin/FDK/Tools/osx:$PATH
export FDK_EXE=~/bin/FDK/Tools/osx

# for YaTeX
# export BIBINPUTS=~/Dropbox/bib:$BIBINPUTS
