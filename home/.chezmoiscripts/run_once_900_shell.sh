#!/usr/bin/env bash

set -euo pipefail

command -v zsh >/dev/null 2>&1 && chsh -s "$(command -v zsh)" || true
