# 出典・取得日・確かめた版

取得日はすべて 2026-11-14。文書は GitHub の `twpayne/chezmoi` の `master`（`assets/chezmoi.io/docs/`）の写しを読み、公開サイトの URL と対応づけた。ソースは v2.67.0 と v2.74.1 のタグ。

## 確かめた版

- このリポジトリが使う版: **v2.67.0**（`chezmoi --version` で確認。2025-11-02 ビルド）。
- 公式の最新リリース: **v2.74.1**（2026-11-10）。
- 実測（`[実測]`）はすべて v2.67.0 のバイナリを、空の設定・使い捨ての `-S`・`-D`・`--persistent-state` で隔離して行った（[commands.md](commands.md#隔離して実測する)）。

## 公式文書（出典）

公開サイト <https://www.chezmoi.io/> 配下。

- user-guide: [daily-operations](https://www.chezmoi.io/user-guide/daily-operations/)・[templating](https://www.chezmoi.io/user-guide/templating/)・[manage-different-types-of-file](https://www.chezmoi.io/user-guide/manage-different-types-of-file/)・[manage-machine-to-machine-differences](https://www.chezmoi.io/user-guide/manage-machine-to-machine-differences/)・[use-scripts-to-perform-actions](https://www.chezmoi.io/user-guide/use-scripts-to-perform-actions/)・[include-files-from-elsewhere](https://www.chezmoi.io/user-guide/include-files-from-elsewhere/)・[machines/windows](https://www.chezmoi.io/user-guide/machines/windows/)
- FAQ: [usage](https://www.chezmoi.io/user-guide/frequently-asked-questions/usage/)・[design](https://www.chezmoi.io/user-guide/frequently-asked-questions/design/)・[troubleshooting](https://www.chezmoi.io/user-guide/frequently-asked-questions/troubleshooting/)
- reference: [application-order](https://www.chezmoi.io/reference/application-order/)・[source-state-attributes](https://www.chezmoi.io/reference/source-state-attributes/)・[target-types](https://www.chezmoi.io/reference/target-types/)
- special files: [index](https://www.chezmoi.io/reference/special-files/)・[.chezmoiignore](https://www.chezmoi.io/reference/special-files/chezmoiignore/)・[.chezmoiremove](https://www.chezmoi.io/reference/special-files/chezmoiremove/)・[.chezmoiroot](https://www.chezmoi.io/reference/special-files/chezmoiroot/)・[.chezmoiversion](https://www.chezmoi.io/reference/special-files/chezmoiversion/)・[.chezmoiexternal](https://www.chezmoi.io/reference/special-files/chezmoiexternal-format/)・[.chezmoi.$FORMAT.tmpl](https://www.chezmoi.io/reference/special-files/chezmoi-format-tmpl/)
- special directories: [.chezmoidata/](https://www.chezmoi.io/reference/special-directories/chezmoidata/)・[.chezmoiexternals/](https://www.chezmoi.io/reference/special-directories/chezmoiexternals/)・[.chezmoiscripts/](https://www.chezmoi.io/reference/special-directories/chezmoiscripts/)・[.chezmoitemplates/](https://www.chezmoi.io/reference/special-directories/chezmoitemplates/)
- templates: [variables](https://www.chezmoi.io/reference/templates/variables/)・[directives](https://www.chezmoi.io/reference/templates/directives/)・[functions](https://www.chezmoi.io/reference/templates/functions/)
- configuration file: [index](https://www.chezmoi.io/reference/configuration-file/)・[hooks](https://www.chezmoi.io/reference/configuration-file/hooks/)・[interpreters](https://www.chezmoi.io/reference/configuration-file/interpreters/)・[warnings](https://www.chezmoi.io/reference/configuration-file/warnings/)
- command-line flags: [global](https://www.chezmoi.io/reference/command-line-flags/global/)・[common](https://www.chezmoi.io/reference/command-line-flags/common/)
- commands: [add](https://www.chezmoi.io/reference/commands/add/)・[apply](https://www.chezmoi.io/reference/commands/apply/)・[diff](https://www.chezmoi.io/reference/commands/diff/)・[doctor](https://www.chezmoi.io/reference/commands/doctor/)・[execute-template](https://www.chezmoi.io/reference/commands/execute-template/)・[forget](https://www.chezmoi.io/reference/commands/forget/)・[destroy](https://www.chezmoi.io/reference/commands/destroy/)・[purge](https://www.chezmoi.io/reference/commands/purge/)・[init](https://www.chezmoi.io/reference/commands/init/)・[managed](https://www.chezmoi.io/reference/commands/managed/)・[unmanaged](https://www.chezmoi.io/reference/commands/unmanaged/)・[ignored](https://www.chezmoi.io/reference/commands/ignored/)・[push](https://www.chezmoi.io/reference/commands/push/)・[re-add](https://www.chezmoi.io/reference/commands/re-add/)・[state](https://www.chezmoi.io/reference/commands/state/)・[status](https://www.chezmoi.io/reference/commands/status/)・[update](https://www.chezmoi.io/reference/commands/update/)・[verify](https://www.chezmoi.io/reference/commands/verify/)
- 設計: [architecture](https://www.chezmoi.io/developer-guide/architecture/)

## 公式実装（出典）

- リリースノート: <https://github.com/twpayne/chezmoi/releases>（v2.67.0 より後の v2.68.0〜v2.74.1 を全件読んだ）。取得は GitHub API（`/repos/twpayne/chezmoi/releases`）。
- ソース（タグ v2.74.1・v2.67.0）: `internal/chezmoi/sourcestate.go`（`.chezmoiremove` の glob と `InconsistentStateError`）・`internal/chezmoi/errors.go`・`internal/chezmoi/targetstateentry.go`（スクリプトの `SkipApply` と状態の記録）・`internal/chezmoi/persistentstate.go`（バケット名）・`internal/cmd/config.go`（`newSourceState` の hook・`applyArgs` の `--init`）・`internal/cmd/updatecmd.go`（`update`）・`internal/cmd/util_windows.go` / `util_unix.go` / `interpreters.go`（`.ps1` の既定）。

## 版ごとの差分（v2.67.0 以降）

リリースノート（v2.68.0〜v2.74.1）から、このリポジトリの運用に関わるもの。

| 版 | 変更 |
| --- | --- |
| v2.68.0 | `add --new`・`re-add --re-encrypt`・`edit-encrypted` を追加。`.chezmoi.sourceFile` が常に相対パスに |
| v2.69.0 | TOML 1.1 に対応。テンプレート関数の実装を一時 sprout へ（v2.69.1 で sprig へ戻し、v2.72.1 でも sprig） |
| v2.69.2 | `unmanaged` に `--include` / `--exclude` |
| v2.69.4 | **`.ps1` の既定 interpreter が `pwsh` 優先に**（無ければ Windows は `powershell`） |
| v2.70.0 | 複数の外部を 1 つのターゲットへ（`targetPath`）。`edit --apply` が scripts を適用しないことを文書化 |
| v2.70.1 | `.chezmoi.rawHomeDir`・`doctor` の build-info・`globCaseInsensitive`。**設定ファイルの未知のフィールドを検出する** |
| v2.70.2 | `.chezmoi.flags`・`stdinIsATTY` を全テンプレートで |
| v2.70.4 | テンプレートデータのパスを文字列に統一 |
| v2.71.0 | `--error-on-conflict`・`init --revision` / `--tag` |
| v2.71.1 | `--skip-secrets` |
| v2.72.0 | `shellQuote`・`debugf`。複数のセキュリティ修正（`..` を含むパスの拒否・一時ファイルの権限・永続状態ディレクトリを private に） |
| v2.72.2 | `private_` を `external_` ディレクトリに適用可能に |
| v2.73.0 | `push` コマンドを追加 |
| v2.73.1 | `shellQuote` の二重バックスラッシュ修正。`re-add` と外部・`exact_` の panic 修正 |
| v2.73.2 | `external_` ディレクトリ内の `.chezmoidata` を読まない。`exact_` 内の `re-add` 修正 |
| v2.74.0 | **非推奨だった `remove` コマンドを撤去**。`apply` の選択肢に「conflicts をスキップ」。age の identity ファイルの権限を検査 |
| v2.74.1 | `init --apply` が確実に apply を実行し、設定テンプレートのデータを再読み込み |

## 調査で訂正した点

事前の理解と食い違った、または精度が上がった点。

1. **`.ps1` の既定 interpreter は固定ではない。** v2.67.0 は Windows で `powershell -NoLogo`、v2.69.4 以降は `pwsh` 優先。chezmoi の更新で、5.1 前提の BOM・文字コードの扱いが黙って変わりうる。
2. **`.chezmoiremove` の `inconsistent state` は「source に同名があれば常に」ではない。** 宛先に実在するときだけ起きる（宛先を glob して照合するため）。
3. **`run_once_` と `run_onchange_` の鍵が違う。** once は内容のハッシュ（別名でも走らない）、onchange はターゲットのパス（改名で走る）。公式の属性表は「same filename」としか書かず、once の鍵が内容だけであることは、文書の本文（`use-scripts-to-perform-actions`）とソースで分かる。
4. **`--dry-run` / `diff` で実行されるものがある。** hooks（公式に明記）に加え、`modify_` スクリプトも実行される（実測）。「dry-run は何も実行しない」は誤り。
5. **`.chezmoiignore` は `dot_` ではなくターゲットのパスで書く**（実測。文書にも明記）。
6. **`chezmoi update` は `init` を呼ばないが、警告は出す。** 設定テンプレートが変わると `apply` / `update` が「run chezmoi init」と警告する（`warnings.configFileTemplateHasChanged`）。完全に黙って古いままになるのではない。
7. **`chezmoi remove` は v2.74.0 で撤去済み。** 古い記事・記憶の `remove` は使えない。
8. **テンプレートの出力は既定で BOM 無し**。BOM が要るときはディレクティブ `chezmoi:template:encoding=utf-8-bom` が要る。

## 未確認

- `chezmoi:template:encoding=utf-8-bom` を付けた `.ps1.tmpl` の実際の描画結果（BOM の有無）。公式文書の記述だけ。
- 設定テンプレートに足した `hooks` が、`init` を通す前の機械で無効なことの実機確認（設定の読み込み経路からの推測）。
- Windows 実機での挙動全般（`pwsh` / `powershell` の選択・symlink・昇格）。WSL・Linux では再現できない。
- `update` の処理順（pull → apply）は v2.74.1 のソースで確認した。v2.67.0 でも `newSourceState` が同じ `read-source-state` の hook を呼ぶことは確かめたが、`update` の処理順そのものは v2.67.0 では読んでいない。
- `.chezmoiversion` の最低版を、どの機能がどの版から使えるかの一覧にした表（作っていない）。
- 公式文書は `master`（v2.74.1 より先の可能性）の写し。最新リリースとの差は個別に確認していない。

## description の発動の確認（机上）

skill-creator の手順（試験の依頼文で発動する / しないを見る）は、skill-creator の文書が作業ツリーの外にあり読めなかったため、この手順に倣って依頼文を作り、description と突き合わせる机上の確認に留めた。**実際のエージェントでの発動は未確認。**

| 依頼文 | 期待 | 根拠となる description の語 |
| --- | --- | --- |
| 「`.chezmoiremove` に書いたら `inconsistent state` で apply が止まった。原因は？」 | 発動 | `inconsistent state`・`.chezmoiremove` |
| 「`run_onchange_` のスクリプトが改名したら走り直した。仕様？」 | 発動 | `run_onchange_`・scripts の実行条件 |
| 「`.chezmoiignore` に `dot_foo` と書いたのに無視されない」 | 発動 | `.chezmoiignore が効かない` |
| 「`modify_` スクリプトで TOML の一部だけ書き換えたい」 | 発動 | `modify_ の書き方` |
| 「このリポジトリで新しい `run_once_after_` の番号はどう振る？コミットメッセージは？」 | 発動しない（dotfiles-conventions） | リポジトリ固有の規約は対象外と明記 |
| 「git rebase の競合を解消して」「mise でツールを入れて」 | 発動しない | dotfiles 以外の一般的な質問は対象外と明記 |
