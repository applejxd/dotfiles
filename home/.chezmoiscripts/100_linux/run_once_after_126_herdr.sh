#!/bin/bash

set -euo pipefail

installer_path="$(mktemp)"
trap 'rm -f "$installer_path"' EXIT

curl -fsSL https://herdr.dev/install.sh -o "$installer_path"
sh "$installer_path"

herdr_path="${HOME}/.local/bin/herdr"
if [[ ! -x "$herdr_path" ]]; then
    echo "Herdr was not installed at ${herdr_path}" >&2
    exit 1
fi

"$herdr_path" --version
