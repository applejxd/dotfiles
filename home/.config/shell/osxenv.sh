########
# PATH #
########

# The default
export PATH=/usr/local/bin:/usr/local/sbin:/sw/bin:$PATH
# for TeX Live 2019
export PATH=/usr/local/texlive/2019/bin/x86_64-darwin:$PATH
# for wxMaxima
export PATH=/Applications/wxMaxima.app/bin:$PATH

# for openssl
export PATH="/usr/local/opt/openssl@1.1/bin:$PATH"

#################
# Specific root #
#################

# for Maxima
export MAXIMA_USERDIR=/Applications/wxMaxima.app/.maxima

# for YaTeX
export BIBINPUTS=~/Dropbox/bib:$BIBINPUTS

# for openssl
export LDFLAGS="-L/usr/local/opt/openssl@1.1/lib"
export CPPFLAGS="-I/usr/local/opt/openssl@1.1/include"
export PKG_CONFIG_PATH="/usr/local/opt/openssl@1.1/lib/pkgconfig"

# Initialization for FDK command line tools.Fri Jul 29 10:12:14 2016
## for Adobe Font Development Kit for OpenType
export PATH="~/bin/FDK/Tools/osx":$PATH
export FDK_EXE="~/bin/FDK/Tools/osx"

# export HOMEBREW_GITHUB_API_TOKEN=6ab4724f6d2c6706e5997b0794d487948c68f8bf
