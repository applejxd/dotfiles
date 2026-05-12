# zeno.zsh × zsh-autosuggestions 連携メモ

> 対象: [yuki-yano/zeno.zsh](https://github.com/yuki-yano/zeno.zsh) と
> [zsh-users/zsh-autosuggestions](https://github.com/zsh-users/zsh-autosuggestions)
> を同時に使う場合に必要な追加設定の調査記録。
> 当リポジトリでは
> [`home/dot_config/shell/zeno.zsh`](../../home/dot_config/shell/zeno.zsh) で対応済み。

## 1. 症状

`zsh-autosuggestions` をロードしているにも関わらず、対話シェルで以下が起こる:

- 入力したあとに**薄いグレーのサジェストが出ない**、あるいは
- Space / Enter を押したタイミングで**サジェスト表示が更新されない / 受理されない**

## 2. 原因

`zeno.zsh` は `zeno-bind-default-keys` 内で以下のキーバインドを登録する。

```zsh
bindkey ' '  zeno-auto-snippet
bindkey '^M' zeno-auto-snippet-and-accept-line
```

これにより Space / Enter を押したとき呼ばれる ZLE widget は、`self-insert` /
`accept-line` ではなく **zeno が定義した独自 widget** になる。

一方 `zsh-autosuggestions` は

- `ZSH_AUTOSUGGEST_MODIFY_WIDGETS` (内部): サジェスト取得のトリガ
- `ZSH_AUTOSUGGEST_CLEAR_WIDGETS`: 現在のサジェスト表示を消す widget
- `ZSH_AUTOSUGGEST_ACCEPT_WIDGETS`: サジェストを確定する widget
- `ZSH_AUTOSUGGEST_PARTIAL_ACCEPT_WIDGETS`: 単語単位の部分受理

の各配列に登録された widget だけをラップして処理を差し込む。
デフォルト値は `self-insert` などの組み込み widget が中心で、
**`zeno-auto-snippet` / `zeno-auto-snippet-and-accept-line` は含まれない**。

その結果:

| 操作 | デフォルト widget | zeno 適用後 | autosuggestions の動作 |
| --- | --- | --- | --- |
| 文字キー | `self-insert` | `self-insert` (zeno は介入しない) | 取得・表示 OK |
| Space | `self-insert` | `zeno-auto-snippet` | **介入できず取得が走らない** |
| Enter | `accept-line` | `zeno-auto-snippet-and-accept-line` | **クリア/確定が走らない** |

## 3. 対策

`zsh-autosuggestions` の公開拡張点である「Widget Mapping」配列に
zeno の widget を追加する。公式 README:
<https://github.com/zsh-users/zsh-autosuggestions/blob/master/README.md#widget-mapping>

upstream の `src/config.zsh` は `(( ! ${+VAR} )) &&` ガードで defaults を
セットするため、プラグインより先に `typeset -ga` で配列を定義すると
defaults が一切初期化されず、`forward-char` などが ACCEPT から消える。
これを避けるには **autosuggestions ロード後に `+=` する** のが最小。
zinit を使っているなら `atload` ice にぶら下げるのが定石。

```zsh
# home/dot_zshrc.tmpl
zinit ice lucid atload'
  ZSH_AUTOSUGGEST_CLEAR_WIDGETS+=(zeno-auto-snippet zeno-auto-snippet-and-accept-line)
'
zinit light zsh-users/zsh-autosuggestions
```

`zeno-auto-snippet` (Space) と `zeno-auto-snippet-and-accept-line` (Enter)
はどちらも CLEAR にだけ入れる。ACCEPT に入れると行末で Space を押した
ときに「サジェスト確定 + 末尾 Space 追加」になり、通常の Space 入力が
壊れる (zsh-autosuggestions README にも「同じ widget を複数の配列に
入れない」と明記)。サジェスト確定は `→` / `End` / `Ctrl-E` に任せる。

`atload` は plugin の source 完了直後に走るため、

1. autosuggestions が defaults をセット
2. `atload` で zeno widget を `+=`
3. 最初の precmd で `_zsh_autosuggest_bind_widgets` がラップ

の順序になり、defaults と zeno widget の両方が ACCEPT/CLEAR に揃う。

### 設定タイミングの制約

`zsh-autosuggestions` の widget ラッピングは初期化
(`_zsh_autosuggest_start` → `_zsh_autosuggest_bind_widgets`) 時、つまり
**最初の precmd** に走る。一方 `ZSH_AUTOSUGGEST_*_WIDGETS` の defaults は
plugin の **source 時**にセットされる。

したがって安全な追加タイミングは:

- ❌ source より前 (defaults が消える)
- ✅ source 完了後〜最初の precmd まで (ここで `+=`)

zinit なら `atload` がちょうど (1) と (2) の間で走るのでここに置く。

当リポジトリでは `home/dot_zshrc.tmpl` の autosuggestions ロード ice に
`atload` で `+=` を付けてあり、`home/dot_config/shell/zeno.zsh` 側では
配列を一切触らない。

## 4. 補足: ロード順序の一般則

`zsh-autosuggestions` 公式 README は

> If using together with zsh-syntax-highlighting, source this plugin **last**.

と明記している。`fast-syntax-highlighting` も同様の widget ラップ・
`zle-line-pre-redraw` フックを使うため、

```text
... → fast-syntax-highlighting → zsh-autosuggestions
```

の順で並べる必要がある。逆順だと `region_highlight` の上書きにより
グレーのサジェスト表示が消える事象が再現する。

## 5. アップストリーム状況 (記録時点)

- `yuki-yano/zeno.zsh` に本件の issue / PR は**未報告** (検索範囲内)
- 類似の widget ラップ系プラグイン
  ([Aloxaf/fzf-tab](https://github.com/Aloxaf/fzf-tab) など) は
  README にロード順注意が明記されているが、zeno は未記載
- 余力があれば zeno へ「README に
  `ZSH_AUTOSUGGEST_*_WIDGETS` のサンプル追加」を提案する PR を作る余地あり

## 6. 参考リンク

- [zsh-autosuggestions / Widget Mapping](https://github.com/zsh-users/zsh-autosuggestions/blob/master/README.md#widget-mapping)
- [zsh-autosuggestions #483 — Conflict with zsh-syntax-highlighting](https://github.com/zsh-users/zsh-autosuggestions/issues/483)
- [fast-syntax-highlighting #79 — unhandled ZLE widget: autosuggest-accept](https://github.com/zdharma-continuum/fast-syntax-highlighting/issues/79)
- [yuki-yano/zeno.zsh](https://github.com/yuki-yano/zeno.zsh)
