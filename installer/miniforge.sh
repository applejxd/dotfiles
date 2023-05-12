#!/bin/bash

if [[ ! -e ~/.asdf ]]; then
    git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.11.3
fi
# shellcheck source=/dev/null
source "$HOME/.asdf/asdf.sh"

if [[ ! -e "$HOME"/.asdf/python ]]; then
    asdf plugin add python
fi

if ! (type "conda" >/dev/null 2>&1); then
    # asdf list all python
    asdf install python miniforge3-latest
    asdf global python miniforge3-latest
fi
