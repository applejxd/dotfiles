#!/usr/bin/env bash

set -euo pipefail

sudo -v
sudo apt-get update && sudo apt-get install -y zsh

command -v zsh >/dev/null 2>&1 && chsh -s "$(command -v zsh)" || true
