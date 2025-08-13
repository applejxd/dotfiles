#!/usr/bin/env bash
set -e -o pipefail
export PATH="$HOME/.local/bin:$PATH"
[[ -x "$HOME/.local/bin/mise" ]] || curl -fsSL https://mise.run | sh
mkdir -p "$HOME/.config/mise"
eval "$("$HOME/.local/bin/mise" activate bash)"
export PATH="$HOME/.local/share/mise/shims:$PATH"
