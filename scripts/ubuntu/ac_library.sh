#!/bin/bash

set -euo pipefail

# For AtCoder (ac-library)
if [[ ! -e /usr/local/include/atcoder ]]; then
    echo "/usr/local/include へ配置するため sudo 権限が必要です..."
    sudo -v || exit 1

    git clone https://github.com/atcoder/ac-library.git /tmp/ac-library
    sudo cp -r /tmp/ac-library/atcoder /usr/local/include
    rm -rf /tmp/ac-library
fi
