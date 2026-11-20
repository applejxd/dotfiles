#!/bin/bash
# pi の特殊な起動 2 つ: drypi (モデルの上に載るものを全部切る) と superpi (drypi を root で起動する)。
# shellrc.sh から読み込む (対話シェル専用)。外部の pi (alias・関数ではない実行ファイル) が PATH に無い機では、何も定義しない。
# 意図・切るもの・注意: docs/spec/shell.md#pi-の特殊な起動-drypi-と-superpi

# 外部の pi の実行ファイルを探す (alias・関数は除く。bash は type -P、zsh は whence -p)
if [ -n "${ZSH_VERSION-}" ]; then
    _pi_found="$(whence -p pi 2>/dev/null)"
else
    _pi_found="$(type -P pi 2>/dev/null)"
fi

if [ -n "$_pi_found" ]; then
    # drypi が切るもの。superpi も同じ一覧を使うので、切る範囲を変えるときはここだけ直す。
    # --no-extensions は、組み込みの MCP・tool_search・codemode と、設定した package 由来の拡張も切る (--no-mcp は足さない)。
    # --no-approve は、信頼の対象になるプロジェクトの .pi/ の設定・拡張・MCP を、この実行では読まない。
    _PI_DRY_ARGS=(--no-extensions --no-skills --no-prompt-templates --no-context-files --no-approve)

    # 起動したその場所のまま (作業ディレクトリは変えない)。引数は pi へそのまま渡す。
    # 例: drypi / drypi -p "依頼" / echo "依頼" | drypi -p
    function drypi() {
        command pi "${_PI_DRY_ARGS[@]}" "$@"
    }

    # root で drypi を起動する。cd / は、サブシェルの中だけ (呼んだシェルの作業ディレクトリは変わらない)。
    # HOME と PI_CODING_AGENT_DIR は、利用者のものを使う (認証・設定を共有するため)。root が ~/.pi/agent に
    # root 所有のファイルを作ると、あとで通常の pi が書けなくなるので、セッションを保存せず (--no-session)、
    # 起動時の自動の通信もしない (--offline)。sudo が環境変数を落とすので、渡すのは env の 3 つだけ。
    function superpi() {
        local pi_bin
        if ! command -v sudo >/dev/null 2>&1; then
            echo "superpi: sudo が無い" >&2
            return 1
        fi
        # 外部の pi の絶対パス。相対の PATH 要素で見つかったときは、cd / する前の作業ディレクトリで絶対にする
        if [ -n "${ZSH_VERSION-}" ]; then
            pi_bin="$(whence -p pi 2>/dev/null)"
        else
            pi_bin="$(type -P pi 2>/dev/null)"
        fi
        if [ -z "$pi_bin" ]; then
            echo "superpi: pi の実行ファイルが PATH に無い" >&2
            return 1
        fi
        case "$pi_bin" in
            /*) ;;
            *) pi_bin="$PWD/$pi_bin" ;;
        esac
        (
            cd / || exit
            sudo env HOME="$HOME" PATH="$PATH" PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}" \
                "$pi_bin" "${_PI_DRY_ARGS[@]}" --no-session --offline "$@"
        )
    }
fi
unset _pi_found
