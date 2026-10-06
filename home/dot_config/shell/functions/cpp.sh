#!/bin/bash
# 競技プログラミング用: C++ の単一ファイルを debug / release でコンパイルして実行する。
# shellrc.sh から読み込む (対話シェル専用)。zsh では suffix alias で *.cpp から呼ばれる。
# 使い方とフラグの意図: docs/spec/structure.md#c-の単一ファイル実行runcpp

# Usage: runcpp [options] <src.cpp> [options] [-- program args...]
function runcpp() {
    local mode="${RUNCPP_MODE:-debug}" std="${RUNCPP_STD:-gnu++20}"
    local compile_only=0 timing=0 src="" arg cxx="${RUNCPP_CXX-}" c
    local -a prog=() extra=() flags=()
    while [ "$#" -gt 0 ]; do
        arg="$1"
        shift
        case "$arg" in
            -h | --help)
                cat <<'EOF'
Usage: runcpp [options] <src.cpp> [options] [-- program args...]

  -d, --debug         warnings + ASan/UBSan + STL debug mode (default)
  -r, --release       -O2, no sanitizer (judge-like)
  -c, --compile-only  compile only
  -t, --time          show elapsed time
      --std=STD       language standard (default: gnu++20)
  -h, --help          show this help

Environment:
  RUNCPP_MODE   debug | release (default mode)
  RUNCPP_CXX    compiler (default: g++, newest g++-N on macOS)
  RUNCPP_STD    default for --std
  RUNCPP_FLAGS  extra compiler flags (e.g. "-I$HOME/ac-library")
EOF
                return 0
                ;;
            -d | --debug) mode=debug ;;
            -r | --release) mode=release ;;
            -c | --compile-only) compile_only=1 ;;
            -t | --time) timing=1 ;;
            --std=*) std="${arg#--std=}" ;;
            --)
                prog+=("$@")
                break
                ;;
            -*)
                echo "runcpp: unknown option: $arg (pass program args after --)" >&2
                return 1
                ;;
            *)
                if [ -z "$src" ]; then
                    src="$arg"
                else
                    prog+=("$arg")
                fi
                ;;
        esac
    done
    case "$mode" in
        debug | release) ;;
        *)
            echo "runcpp: invalid mode: $mode (debug | release)" >&2
            return 1
            ;;
    esac
    if [ -z "$src" ]; then
        echo "Usage: runcpp [options] <src.cpp> [-- args...] (see: runcpp --help)" >&2
        return 1
    fi
    if [ ! -f "$src" ]; then
        echo "runcpp: $src: No such file" >&2
        return 1
    fi

    if [ -z "$cxx" ]; then
        cxx=g++
        if [ "$(uname -s)" = Darwin ]; then
            # macOS の g++ は Apple clang (bits/stdc++.h が無い) なので Homebrew の g++-N を探す
            for c in g++-{20..11}; do
                if command -v "$c" >/dev/null 2>&1; then
                    cxx="$c"
                    break
                fi
            done
        fi
    fi

    flags=(-std="$std" -Wall -Wextra)
    if [ "$mode" = debug ]; then
        flags+=(
            -O0 -g -fno-omit-frame-pointer
            -Wshadow -Wformat=2 -Wfloat-equal -Wcast-qual
            "-fsanitize=address,undefined" -fno-sanitize-recover=all
            -D_GLIBCXX_DEBUG -D_GLIBCXX_DEBUG_PEDANTIC
            -D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG
            -DLOCAL
        )
        # gcc 専用の警告 (clang に渡すと unknown warning になる)
        if ! "$cxx" --version 2>/dev/null | grep -qi clang; then
            flags+=(-Wduplicated-cond -Wlogical-op)
        fi
    else
        flags+=(-O2 -DONLINE_JUDGE)
    fi
    # RUNCPP_FLAGS を空白で分割する (zsh は既定で分割しないため書き分ける)
    if [ -n "${RUNCPP_FLAGS-}" ]; then
        if [ -n "${ZSH_VERSION-}" ]; then
            eval 'extra=(${=RUNCPP_FLAGS})'
        else
            read -r -a extra <<<"$RUNCPP_FLAGS"
        fi
    fi

    local name="${src##*/}"
    name="${name%.*}"
    local outdir="${XDG_CACHE_HOME:-$HOME/.cache}/runcpp"
    local bin="$outdir/$name-$mode"
    mkdir -p "$outdir" || return 1
    "$cxx" "${flags[@]}" "$src" "${extra[@]}" -o "$bin" || return 1
    [ "$compile_only" = 1 ] && return 0

    # unlimited にしない (ASan が落ちる)。time の中で exec しない (bash で時間が出ない)
    if [ "$timing" = 1 ]; then
        time (
            ulimit -s 1048576 2>/dev/null || ulimit -s "$(ulimit -Hs)" 2>/dev/null
            "$bin" "${prog[@]}"
        )
    else
        (
            ulimit -s 1048576 2>/dev/null || ulimit -s "$(ulimit -Hs)" 2>/dev/null
            "$bin" "${prog[@]}"
        )
    fi
}
