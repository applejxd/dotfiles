#!/usr/bin/env bash
set -eu
command -v git >/dev/null 2>&1 || exit 0
git config --global init.defaultBranch "main"
git config --global core.editor "vim"
git config --global core.ignorecase "false"
git config --global core.quotepath "false"
git config --global ghq.root "$HOME/src"
git config --global gitflow.branch.master "main"
git config --global url."github:".pushInsteadOf https://github.com/
git config --global credential.helper store
mkdir -p "$HOME/src"
