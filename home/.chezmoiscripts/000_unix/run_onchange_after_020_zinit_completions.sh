#!/bin/bash
# zinit が ohmyzsh から自動インストールした補完を取り除く。
#
# .zshrc では ohmyzsh を lib/git.zsh のためだけに読み込んでいるが、
# zinit はプラグイン配下の _* を全て ~/.zinit/completions/ へリンクする。
# その結果、ロードしていないプラグイン用の補完が fpath に混ざる。
# 代表例が zsh-z 用の _z で、未定義の zshz を呼ぶため
# "_z:39: command not found: zshz" になる (このリポジトリは rupa/z を使う)。
#
# 今後の再発は .zshrc の nocompletions ice で防ぐ。ここでは既存の
# インストール済みリンクを掃除する。

set -eu

completions_dir="${HOME}/.zinit/completions"

removed=0
if [ -d "$completions_dir" ]; then
    for link in "$completions_dir"/*; do
        [ -L "$link" ] || continue
        case "$(readlink "$link")" in
        *ohmyzsh---ohmyzsh*)
            rm -f "$link"
            removed=$((removed + 1))
            ;;
        esac
    done
    echo "removed ${removed} ohmyzsh completion(s) from ${completions_dir}"
fi

# fpath の内容が変わるので compinit のダンプを作り直させる。
# 名前は環境によって .zcompdump / .zcompdump.<host>.<pid> / .zcompdump-<host>-<ver>
# / .zcompdump.zwc と揺れるため、まとめて消す (次回シェル起動で再生成される)。
zdotdir="${ZDOTDIR:-$HOME}"
rm -f "${zdotdir}"/.zcompdump "${zdotdir}"/.zcompdump.* "${zdotdir}"/.zcompdump-*
