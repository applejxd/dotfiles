#!/bin/bash
# 圧縮・展開の関数 (extract / zpack / zunpack)。
# shellrc.sh から読み込む (対話シェル専用)。zsh では suffix alias で extract が呼ばれる。
# 失敗時の扱い: docs/spec/structure.md#シェルの起動契約 (方針 5)

# 拡張子に応じて展開する
# see http://bit.ly/2tCOvHP
function extract() {
    case $1 in
    *.tar.gz | *.tgz) tar xzvf "$1" ;;
    *.tar.xz) tar Jxvf "$1" ;;
    *.zip) unzip "$1" ;;
    *.lzh) lha e "$1" ;;
    *.tar.bz2 | *.tbz) tar xjvf "$1" ;;
    *.tar.Z) tar zxvf "$1" ;;
    *.gz) gzip -d "$1" ;;
    *.bz2) bzip2 -dc "$1" ;;
    *.Z) uncompress "$1" ;;
    *.tar.zst | *.tzst) zstd -d --threads=0 -c "$1" | tar -xvf - ;;
    *.zst) zstd -d "$1" ;;
    *.tar) tar xvf "$1" ;;
    *.arj) unarj "$1" ;;
    esac
}

# tar + zstd で圧縮する (全コア並列・高圧縮。既存の出力先は上書きしない)
# Usage: zpack <dir_or_file> [output.tar.zst]
function zpack() {
    if [ "$#" -ge 1 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
        cat <<'EOF'
Usage: zpack <dir_or_file> [output.tar.zst]

Existing output files are never overwritten.

Compression level:
  Set ZPACK_LEVEL to an integer between 1 and 22 (default: 19).
  Levels 20-22 automatically enable --ultra.

Examples:
  zpack mydir
  zpack mydir archive.tar.zst
  ZPACK_LEVEL=22 zpack mydir
EOF
        return 0
    fi
    if [ "$#" -lt 1 ]; then
        echo "Usage: zpack <dir_or_file> [output.tar.zst] (see: zpack --help)" >&2
        return 1
    fi
    local src="$1"
    if [ ! -e "$src" ]; then
        echo "zpack: $src: No such file or directory" >&2
        return 1
    fi
    local dst="${2:-$(basename "$src").tar.zst}"
    # --threads=0 uses all available CPU cores
    # Override compression level via ZPACK_LEVEL (default: 19, max: 22 with --ultra)
    local level="${ZPACK_LEVEL:-19}"
    case "$level" in
        ''|*[!0-9]*)
            echo "zpack: ZPACK_LEVEL must be an integer (1-22): $level" >&2
            return 1
            ;;
    esac
    if [ "$level" -lt 1 ] || [ "$level" -gt 22 ]; then
        echo "zpack: ZPACK_LEVEL out of range (1-22): $level" >&2
        return 1
    fi
    local ultra_flag=""
    if [ "$level" -gt 19 ]; then
        ultra_flag="--ultra"
    fi
    if [ -e "$dst" ]; then
        echo "zpack: $dst: already exists (not overwritten)" >&2
        return 1
    fi
    local tmp="${dst}.zpack.$$"
    set -- -T0 "-$level" -o "$tmp"
    if [ -n "$ultra_flag" ]; then
        set -- -T0 "$ultra_flag" "-$level" -o "$tmp"
    fi
    if (
        set -o pipefail
        tar -cf - "$src" | zstd "$@"
    ) && mv -n -- "$tmp" "$dst" && [ ! -e "$tmp" ]; then
        echo "Created: $dst"
    else
        rm -f -- "$tmp"
        echo "zpack: failed to create archive: $dst" >&2
        return 1
    fi
}

# tar.zst を展開する
# Usage: zunpack <archive.tar.zst> [output_dir]
function zunpack() {
    if [ "$#" -ge 1 ] && { [ "$1" = "-h" ] || [ "$1" = "--help" ]; }; then
        cat <<'EOF'
Usage: zunpack <archive.tar.zst> [output_dir]
EOF
        return 0
    fi
    if [ "$#" -lt 1 ]; then
        echo "Usage: zunpack <archive.tar.zst> [output_dir] (see: zunpack --help)" >&2
        return 1
    fi
    local src="$1"
    if [ ! -f "$src" ]; then
        echo "zunpack: $src: No such file" >&2
        return 1
    fi
    local dst="${2:-.}"
    if [ -e "$dst" ] && [ ! -d "$dst" ]; then
        echo "zunpack: $dst: Not a directory" >&2
        return 1
    fi
    if ! mkdir -p "$dst"; then
        echo "zunpack: failed to create directory: $dst" >&2
        return 1
    fi
    if ! (
        set -o pipefail
        zstd -d --threads=0 -c "$src" | tar -xf - -C "$dst"
    ); then
        echo "zunpack: failed to extract archive: $src" >&2
        return 1
    fi
}
