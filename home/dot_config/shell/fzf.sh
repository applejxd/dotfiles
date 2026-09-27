#!/bin/bash

# resolve fzf/ next to this file (bash: BASH_SOURCE, zsh: %x)
if [ -n "${ZSH_VERSION:-}" ]; then
    eval '_fzf_conf_dir=${${(%):-%x}:h}'
else
    _fzf_conf_dir=${BASH_SOURCE[0]%/*}
    [ "$_fzf_conf_dir" = "${BASH_SOURCE[0]}" ] && _fzf_conf_dir=.
fi

for _fzf_conf in core git tools; do
    # shellcheck source=/dev/null
    source "${_fzf_conf_dir}/fzf/${_fzf_conf}.sh"
done
unset _fzf_conf _fzf_conf_dir
