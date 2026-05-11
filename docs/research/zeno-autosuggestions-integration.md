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

```zsh
# zsh-autosuggestions より前に設定する必要がある
typeset -ga ZSH_AUTOSUGGEST_CLEAR_WIDGETS ZSH_AUTOSUGGEST_ACCEPT_WIDGETS
ZSH_AUTOSUGGEST_CLEAR_WIDGETS+=(zeno-auto-snippet zeno-auto-snippet-and-accept-line)
ZSH_AUTOSUGGEST_ACCEPT_WIDGETS+=(zeno-auto-snippet)
```

### 設定タイミングの制約

`zsh-autosuggestions` は初期化 (`_zsh_autosuggest_start`) 時にこれらの配列を
読み取って widget をラップするため、**autosuggestions がロードされる前**に
配列に追加しておく必要がある。

当リポジトリでは:

- `home/dot_config/shell/zeno.zsh` (eager, 同期ロード) で配列を設定
- `home/dot_zshrc.tmpl` の `zinit ice wait'0d' lucid` (turbo, プロンプト後)
  で `zsh-users/zsh-autosuggestions` をロード

の順序になっており、安全に解決される。

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
