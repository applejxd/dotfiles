# コマンドの使い分けと限界

印: `[docs]` 公式 / `[src]` ソース / `[実測]` v2.67.0 / `[推測]`。

## 日常 [docs]

| やりたいこと | コマンド |
| --- | --- |
| 差分を見る | `chezmoi diff [target]`（既定は scripts の内容も出す）。`status` は `git status` 風（1 列目: 最後に chezmoi が書いた状態との差、2 列目: apply が行う変更。`R` は script の実行） |
| 適用 | `chezmoi apply [target]`。`-n -v`（dry-run）で予告。`--source-path` で source のパスを指定 |
| 取り込んで適用 | `chezmoi update`（`git pull --autostash --rebase` + apply。`init` は呼ばない） |
| 設定を再生成して適用 | `chezmoi update --init` / `apply --init` |
| 一致の確認 | `chezmoi verify`（一致なら終了コード 0、不一致は 1） |
| 管理対象・対象外 | `chezmoi managed`（`-i files,dirs`・`--path-style source-relative`）・`unmanaged`（`--include` / `--exclude` は v2.69.2〜）・`ignored` |
| 診断 | `chezmoi doctor`（`ok` / `warning` / `error`）。詳細は `-v`、さらに `--debug` |
| 実ファイルを source へ戻す | `chezmoi add`（テンプレートは `-T`）・`re-add`（テンプレート・外部・非ファイルは対象外） |
| 管理をやめる | `chezmoi forget`（宛先は残す）。`destroy`（宛先・source・状態をすべて消す。危険）・`purge`（chezmoi 自体の設定・状態・source を消す） |
| 編集 | `chezmoi edit [--apply / --watch]`（`--apply` は scripts を適用しない。v2.70.0 の文書化）。`source-path`・`target-path`・`cd`・`git` |
| 状態 | `chezmoi state dump` / `get` / `delete-bucket` / `reset`。`chezmoi data` |
| 常用の型 | `-S` source・`-D` dest・`-c` 設定・`--persistent-state`・`--no-tty`・`-k`（続行）・`--force`・`--error-on-conflict`（v2.71.0〜。プロンプトの代わりに失敗） |

- `chezmoi remove` は v2.74.0 で撤去された（廃止済みコマンド）。管理をやめるなら `forget`、宛先も消すなら `destroy`。[docs] リリースノート
- `chezmoi push`（v2.73.0〜）は source で `git add`・`commit`・`push`（運用方針で push を禁止している環境では使わない）。
- `chezmoi init` は source の初期化・設定の生成・（`--apply` で）適用。`--one-shot` は `--apply --depth=1 --force --purge --purge-binary` で、一時環境向け。`--branch`・`--revision`・`--tag`（v2.71.0〜）。v2.74.1 で `init --apply` が確実に apply を実行するよう修正された。
- 位置引数 `target` は宛先のパス。source のパスで渡すときは `--source-path`。

## dry-run と diff の限界

- `--dry-run` は宛先を変更しない。ただし次は動く [docs・実測]:
  - **hooks は実行される**（[scripts-and-order.md](scripts-and-order.md#hooks)）。
  - **`modify_` スクリプトは実行される**（内容を計算するため）。標準エラーへの出力で確認 [実測]。`output` などテンプレート内のコマンドも実行される。
  - scripts は実行されない。`diff` / `status` に出るのは「走る」ことまでで、効果は出ない。
- よって `diff` が空でも、scripts が環境に与える変化（パッケージ導入・設定の書き換え）は検証していない。
- `diff` / `apply` は永続状態を読むので、`run_once_` / `run_onchange_` を走らせたくない検査は `-n` で。dry-run は実際の状態の一時コピーを使う（[src] architecture 文書）。
- **sandbox 内の `chezmoi diff` は `~/` が見えず全部が new file になり、証拠にならない**（dotfiles-conventions）。

## 隔離して実測する

実機を触らずに挙動を確かめるときは、空の設定・使い捨ての source / dest / 状態を渡す:

```sh
: > cfg.toml
chezmoi -c cfg.toml -S ./src -D ./dst --persistent-state ./st.db apply -v
```

`.chezmoiignore` の照合・`.chezmoiremove` の衝突・scripts の実行条件・`modify_` の実行はこれで確認できる。OS 依存（`.chezmoi.os`）と Windows は再現できない。

## Windows [docs]

- `.chezmoi.homeDir` は `/` 区切り。`\` が要るときは `rawHomeDir`（v2.70.1〜）。
- scripts の interpreter は拡張子で決まる（[scripts-and-order.md](scripts-and-order.md#interpreters)）。`.ps1` の既定は v2.69.4 で変わった。
- symlink は開発者モードか `SeCreateSymbolicLinkPrivilege` が要る。
- 管理者権限の scripts は、非昇格のスクリプトが先に終わらないよう `Start-Process -Wait` で待つ（待たないと次の処理が先に進む）。
- WSL の判定は `.chezmoi.kernel.osrelease` の `microsoft`。
- Windows の挙動は WSL / Linux の隔離実行では確かめられない。未確認と書く。
