#!/bin/zsh

#----------------#
# Initialization #
#----------------#

# Added by Zinit's installer
if [[ ! -f $HOME/.zinit/bin/zinit.zsh ]]; then
    print -P "%F{33}▓▒░ %F{220}Installing DHARMA Initiative Plugin Manager (zdharma/zinit)…%f"
    command mkdir -p "$HOME/.zinit" && command chmod g-rwX "$HOME/.zinit"
    command git clone https://github.com/zdharma-continuum/zinit "$HOME/.zinit/bin" && \
        print -P "%F{33}▓▒░ %F{34}Installation successful.%f%b" || \
        print -P "%F{160}▓▒░ The clone has failed.%f%b"
fi

# shellcheck source=/dev/null
source "$HOME/.zinit/bin/zinit.zsh"
autoload -Uz _zinit
(( ${+_comps} )) && _comps[zinit]=_zinit
# End of Zinit's installer chunk

#------------#
# completion #
#------------#

# strict in loading order
# see https://github.com/Aloxaf/fzf-tab?tab=readme-ov-file#install

# completion for non-defalut commands
zinit light zsh-users/zsh-completions

# zsh completion
autoload -Uz compinit && compinit

# fish-like auto completion
zinit light zsh-users/zsh-autosuggestions
# syntax-highlighting to command-line (after compinit)
zinit light zdharma-continuum/fast-syntax-highlighting

# completion with fzf 
zinit light Aloxaf/fzf-tab

#---------------#
# other plugins #
#---------------#

# git
zinit ice pick"lib/git.zsh"
zinit light ohmyzsh/ohmyzsh

#------#
# pure #
#------#

zinit ice compile'(pure|async).zsh' pick'async.zsh' src'pure.zsh'
zinit light sindresorhus/pure

#--------#
# docker #
#--------#

zinit light felixr/docker-zsh-completion

zinit ice pick"docker-fzf.zsh"
zinit load mnowotnik/docker-fzf-completion

zinit ice pick'docker-fzf'
zinit load MartinRamm/fzf-docker

zinit ice as"program" pick"dfimage.bash"
zinit load RyodoTanaka/.bash_extend

#-----#
# fzf #
#-----#

# see https://wonderwall.hatenablog.com/entry/2017/10/06/063000
# see (for options) https://qiita.com/kompiro/items/a09c0b44e7c741724c80

# zinit ice from"gh-r" as"program"
# zinit load junegunn/fzf-bin

# zinit ice multisrc'shell/(key-bindings|completion).zsh'
# zinit load junegunn/fzf

# zinit ice from"gh-r" as"program" pick"bat-*/bat"
# zinit load sharkdp/bat

# zinit ice from"gh-r" as"program" pick"ripgrep-*/rg"
# zinit load BurntSushi/ripgrep

#----------#
# Commands #
#----------#

# zinit ice pick"z.sh"
# zinit light rupa/z

# # enhance 'cd' command
# zinit ice pick"init.sh"
# zinit light b4b4r07/enhancd
# export ENHANCD_COMMAND=ecd

# zinit ice from"gh-r" as"program" pick"ghq_*/ghq"
# zinit load x-motemen/ghq

# # cannot be installed?
# zinit ice as"program" make"install prefix=$ZPFX"
# zinit load jonas/tig

# zinit ice as"program" make"install prefix=$ZPFX"
# zinit load nvie/gitflow
