##################
# Initialization #
##################

### Added by Zinit's installer
if [[ ! -f $HOME/.zinit/bin/zinit.zsh ]]; then
    print -P "%F{33}▓▒░ %F{220}Installing DHARMA Initiative Plugin Manager (zdharma/zinit)…%f"
    command mkdir -p "$HOME/.zinit" && command chmod g-rwX "$HOME/.zinit"
    command git clone https://github.com/zdharma/zinit "$HOME/.zinit/bin" && \
        print -P "%F{33}▓▒░ %F{34}Installation successful.%f%b" || \
        print -P "%F{160}▓▒░ The clone has failed.%f%b"
fi

source "$HOME/.zinit/bin/zinit.zsh"
autoload -Uz _zinit
(( ${+_comps} )) && _comps[zinit]=_zinit
### End of Zinit's installer chunk

###########
# Plugins #
###########

# fish-like auto completion
zinit light zsh-users/zsh-autosuggestions

# completion for non-defalut commands
zinit light zsh-users/zsh-completions

# Fish like interactive tab completion for cd in zsh
zinit ice pick"zsh-interactive-cd.plugin.zsh" wait'!0'
zinit light changyuheng/zsh-interactive-cd

# syntax-highlighting to command-line (after compinit)
zinit ice wait'!0'
zinit light zsh-users/zsh-syntax-highlighting

# git
zinit snippet OMZ::lib/git.zsh

# enhance 'cd' command
zinit ice pick"init.sh"
zinit light b4b4r07/enhancd
export ENHANCD_COMMAND=ecd

# docker
zinit light felixr/docker-zsh-completion

zinit ice pick"docker-fzf.zsh"
zinit light mnowotnik/docker-fzf-completion

########
# pure #
########

zinit ice compile'(pure|async).zsh' pick'async.zsh' src'pure.zsh'
zinit light sindresorhus/pure

#######
# fzf #
#######

# cf. http://bit.ly/2QHO6uS
# cf. (for options) http://bit.ly/2Qi9NTu

# init by zplug
zinit ice from"gh-r" as"program"
zinit load junegunn/fzf-bin

zinit ice multisrc'shell/(key-bindings|completion).zsh'
zinit load junegunn/fzf

zinit ice pick"z.sh"
zinit light rupa/z