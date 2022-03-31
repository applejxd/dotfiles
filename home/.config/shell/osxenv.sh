export LANG=ja_JP.UTF-8

########
# PATH #
########

# The default
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:${PATH}}

# for openssl
if [[ -e "/opt/homebrew/opt/openssl@1.1" ]]; then
  export PATH="/opt/homebrew/opt/openssl@1.1/bin":$PATH
  export LDFLAGS="-L/opt/homebrew/opt/openssl@1.1/lib"
  export CPPFLAGS="-I/opt/homebrew/opt/openssl@1.1/include"
  export PKG_CONFIG_PATH="/usr/local/opt/openssl@1.1/lib/pkgconfig"
fi

#################
# Specific root #
#################

# for Maxima
if [[ -e /Applications/wxMaxima.app/ ]]; then
  export PATH=/Applications/wxMaxima.app/bin:$PATH
  export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima
fi
