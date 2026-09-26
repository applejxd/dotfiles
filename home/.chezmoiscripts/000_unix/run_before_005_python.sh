#!/usr/bin/env bash

set -eu

# chezmoi の modify script は scripts/agents/generate.py を呼び、generate.py は
# tomllib (Python 3.11 以上) を使う。まっさらな Ubuntu 22.04 以前は python3 が
# 3.10 以下なので、ここで 3.11 以上を 1 つだけ確保しておく。
#
# run_before_ なのは、ファイル適用 (= modify script の実行) より先に走る必要が
# あるため。ツール一式を入れる 100_linux/run_onchange_after_125_mise.sh.tmpl は
# after のままにする。あちらは ~/.config/mise/config.toml を読むが、その config
# 自体がファイル適用で展開されるので前倒しできない。
#
# sudo は使わない。見つからないときだけ uv をユーザ領域へ入れて Python を取る。
# 失敗しても apply は止めず、generate.py 側の案内に委ねる。
# see docs/adr/0003-require-python-311-for-agent-configuration.md

has_tomllib() {
    "$1" -c 'import tomllib' >/dev/null 2>&1
}

# chezmoi の [interpreters.py] が指す固定パス。
# init 時に 3.11 以上が PATH に無いと、設定にはこの shim が焼かれる
# (see home/.chezmoi.toml.tmpl)。ここで実体へ張り直す。
# run_before_ なので modify script より先に走る。
SHIM="${HOME}/.local/bin/chezmoi-python3"

link_shim() {
    # 自分自身を指してループさせない
    if [ "$1" = "$SHIM" ]; then
        return 0
    fi
    # ★ここで apply を止めない。このスクリプトの契約は「失敗しても先へ進む」。
    #   dirname は使わずパラメータ展開で済ませる (外部コマンドを増やさない)。
    shim_dir="${SHIM%/*}"
    if ! mkdir -p "$shim_dir" 2>/dev/null; then
        echo "⚠️  ${shim_dir} を作成できませんでした (modify script の Python 解決は次回へ)" >&2
        return 0
    fi
    if ! ln -sfn "$1" "$SHIM" 2>/dev/null; then
        echo "⚠️  ${SHIM} を張れませんでした (modify script の Python 解決は次回へ)" >&2
        return 0
    fi
    echo "modify script 用の Python を ${SHIM} へ張りました -> $1"
}

# 見つけた実行ファイルのパスを出力する。無ければ非ゼロで返る。
find_python() {
    local candidate resolved
    for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
        resolved=$(command -v "$candidate" 2>/dev/null) || continue
        if has_tomllib "$resolved"; then
            printf '%s\n' "$resolved"
            return 0
        fi
    done
    # mise / uv は版番号付きの shim を PATH に出さないので導入先も直接見る
    for candidate in \
        "${HOME}"/.local/share/mise/installs/python/*/bin/python3.1[1-9] \
        "${HOME}"/.local/share/uv/python/*/bin/python3.1[1-9]; do
        if [ -x "$candidate" ] && has_tomllib "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

if found=$(find_python); then
    echo "Python 3.11 以上を確認しました: ${found}"
    link_shim "$found"
    exit 0
fi

echo "tomllib を持つ Python が見つかりません。uv で用意します..."

uv_bin="${HOME}/.local/bin/uv"
if [ ! -x "${uv_bin}" ]; then
    installer=$(mktemp)
    # curl | sh にしないのは、ダウンロード失敗を空入力の成功と区別するため
    if curl -LsSf https://astral.sh/uv/install.sh -o "${installer}"; then
        sh "${installer}" || true
    fi
    rm -f "${installer}"
fi

if [ ! -x "${uv_bin}" ]; then
    echo "⚠️  uv を導入できませんでした。3.11 以上の Python を手動で入れてください。" >&2
    echo "    例: sudo apt-get install -y python3.12" >&2
    exit 0
fi

"${uv_bin}" python install 3.13 || true

if found=$(find_python); then
    echo "✅ Python 3.11 以上を用意しました: ${found}"
    link_shim "$found"
else
    echo "⚠️  Python を用意できませんでした。agent 設定の生成は次回に持ち越されます。" >&2
    echo "    詳細: docs/spec/troubleshooting.md" >&2
fi

exit 0
