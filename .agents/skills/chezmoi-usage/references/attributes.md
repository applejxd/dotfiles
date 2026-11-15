# source state の属性（接頭辞・接尾辞）

印: `[docs]` 公式文書 / `[src]` ソース / `[実測]` v2.67.0 を実行 / `[推測]`。出典は [sources.md](sources.md)。

## 一覧 [docs]

source state のファイル名に状態を埋め込む。`.chezmoi` で始まるもの以外の `.` 始まりは無視される。

| 接頭辞 | 意味 |
| --- | --- |
| `dot_` | 先頭の `.` に置換（`dot_foo` → `.foo`） |
| `private_` | group / world の権限を外す |
| `readonly_` | 書き込み権限を外す |
| `executable_` | 実行権限を付ける |
| `empty_` | 空でも作る（既定では空ファイルは削除される） |
| `encrypted_` | source で暗号化（age は `.age`、gpg は `.asc` が付く） |
| `exact_` | ディレクトリ内の未管理の項目を削除 |
| `external_` | 子の属性を無視 |
| `create_` | 無ければ内容つきで作る。あれば内容は変えない（権限は適用） |
| `modify_` | 内容を標準入力で受け、標準出力を新しい内容にするスクリプト |
| `remove_` | 存在すれば削除（ディレクトリは空のときだけ） |
| `symlink_` | シンボリックリンク（内容が参照先。末尾の改行は除く） |
| `run_` | スクリプト |
| `once_` / `onchange_` | `run_` の実行条件（[scripts-and-order.md](scripts-and-order.md)） |
| `before_` / `after_` | `run_` を適用の前後へ |
| `literal_` | 以降の接頭辞の解釈を止める |

接尾辞は `.tmpl`（テンプレート）と `.literal`（以降の接尾辞の解釈を止める）。

## 順序が決まっている [docs]

接頭辞は**型ごとに許される種類と順序**がある。順序違いは別の名前として扱われる。

| 型 | 許される接頭辞（この順） | 接尾辞 |
| --- | --- | --- |
| ディレクトリ | `remove_`, `external_`, `exact_`, `private_`, `readonly_`, `dot_` | なし |
| 通常ファイル | `encrypted_`, `private_`, `readonly_`, `empty_`, `executable_`, `dot_` | `.tmpl` |
| create | `create_`, `encrypted_`, `private_`, `readonly_`, `empty_`, `executable_`, `dot_` | `.tmpl` |
| modify | `modify_`, `encrypted_`, `private_`, `readonly_`, `executable_`, `dot_` | `.tmpl` |
| remove | `remove_`, `dot_` | なし |
| スクリプト | `run_`, `once_` または `onchange_`, `before_` または `after_` | `.tmpl` |
| symlink | `symlink_`, `dot_` | `.tmpl` |

例: `private_dot_ssh/`・`exact_dot_config/`・`executable_dot_local/bin/foo`・`run_onchange_after_126_x.sh.tmpl`。

## 変換と一意性

- ソースとターゲットは 1 対 1。同じターゲットを指す source の項目が 2 つあると `inconsistent state`（例: `dot_file` と `dot_file.tmpl`、`dir` と `exact_dir`、`run_once_x` と `run_x`）。[src] `sourcestate_test.go` の期待値
- 属性は改名か `chezmoi chattr` で変える。`.tmpl` は `chattr +template`。[docs]
- 許されるディレクトリの権限は 0o755・0o700・0o500 だけ。[docs] FAQ design

## modify_ スクリプト

- [docs] 標準入力に現在の内容（無ければ空）、標準出力が新しい内容。ファイルが無いときは完全な内容を出す責任がスクリプトにある。
- `modify_` スクリプトは **dry-run・`diff`・`status` でも実行される**（描画に必要なため。v2.67.0 で標準エラーへの出力を確認 [実測]）。副作用を持たせない。
- 内容に `chezmoi:modify-template` を含むと、その行を除いた残りがテンプレートとして実行され、現在の内容が `.chezmoi.stdin` に入る。このときファイル名に `.tmpl` を付けては**いけない**。
- 一方、`modify_foo.py.tmpl` のように `.tmpl` を付けると「スクリプト自体を描画してから実行する」普通のテンプレートになる。`chezmoi:modify-template` とは別物。[推測: 公式文書の記述の組み合わせ。この区別を明示した記述は未確認]
- 部分的な編集には JSON/TOML/YAML 向けの `setValueAtPath`・`deleteValueAtPath`（[templates.md](templates.md)）が使える。

## `create_` と権限だけの管理 [docs]

- `create_` のファイルは、あれば内容を変えず、無ければ作る。`private_` などの権限は適用する。
- 「無いときは作らず、あれば権限だけ整える」には `run_` スクリプトを使う。

## `exact_` [docs・src]

- ディレクトリに付けると、source に無い宛先の項目を削除する。外部（`.chezmoiexternal` の `exact = true`）でも使える。
- `chezmoi add --exact` で付ける。`exact_` ディレクトリでの `re-add` は、宛先で消した・足したファイルを source へも反映する（v2.73.1 / v2.73.2 で `re-add` と `exact_` の panic・不具合が複数直っている）。
- 空のディレクトリは git に載らない。作りたいが中身は無視したいときは source に `.keep` を置く（`.` 始まりなので chezmoi は無視）。
