# テンプレート

印: `[docs]` 公式 / `[src]` ソース / `[実測]` / `[推測]`。

## 基本 [docs]

- Go の `text/template` + sprig + chezmoi 独自の関数。`.tmpl` 接尾辞、または `.chezmoitemplates/` の中のファイルが対象。
- 空白の除去は `{{-` / `-}}`（改行も詰める）。スクリプトの shebang の前に改行を残さない。
- リテラルの `{{` は `{{ "{{" }}`。長いときは `{{ "{{ .Target }}" }}`。
- `and` / `or` は全引数を評価する（短絡しない）。変数の存在確認は `{{- if and (hasKey . "var") .var }}` のように `hasKey` を使う（このリポジトリの作法。dotfiles-conventions）。
- 既定ではマップの存在しないキーを引くとエラー。`template.options` か `chezmoi:template:missing-key=zero|invalid|error` で変える。

## データ [docs]

`chezmoi data` で一覧（JSON）。優先順位は、chezmoi の変数 `.chezmoi.*` < `.chezmoidata` < 設定の `[data]`。主な `.chezmoi.*`:

| 変数 | 内容 |
| --- | --- |
| `os` / `arch` | `linux`・`darwin`・`windows` / `amd64` など |
| `hostname` / `fqdnHostname` / `username` / `homeDir` | ホームは `/` 区切り。`\` 区切りは `rawHomeDir`（v2.70.1〜） |
| `sourceDir` / `sourceFile` / `targetFile` / `workingTree` | `sourceFile` は source からの相対 |
| `osRelease` / `kernel` | Linux のみ。WSL は `.chezmoi.kernel.osrelease` に `microsoft` を含む |
| `windowsVersion` | Windows のみ |
| `stdin` | `modify_` テンプレートの現在の内容 |
| `args` / `flags` / `config` / `configFile` / `executable` / `version.*` | 実行の文脈（`flags` は v2.70.2〜） |

v2.70.4 から、テンプレートデータのパスはすべて文字列。

## 主な関数 [docs]

- 取得: `include`（source 内のファイル）・`includeTemplate`・`output`（コマンドの標準出力）・`lookPath`・`findExecutable`・`stat` / `lstat`・`glob`・`env`・`fromJson` / `fromToml` / `fromYaml`
- 変換: `toJson` / `toPrettyJson` / `toToml` / `toYaml`・`quote`・`shellQuote` / `shellQuoteList`（v2.72.0〜。シェルへ値を埋めるときは `quote` ではなくこちら）・`replaceAllRegex`・`setValueAtPath` / `deleteValueAtPath`
- 制御: `abortEmpty`・`warnf`・`debugf`（v2.72.0〜）・`stdinIsATTY`
- 秘密: 各 password manager 関数（Bitwarden・1Password・Proton Pass…）。`--skip-secrets`（v2.71.1〜）で秘密を含むテンプレートを飛ばせる
- `prompt*` / `*Once` は設定テンプレート専用（[special-files.md](special-files.md)）

## ディレクティブ [docs]

テンプレート内の `chezmoi:template:key=value` の行（その行は出力から除かれる）:

- `left-delimiter` / `right-delimiter`: `{{ }}` と衝突する形式（Go のテンプレートを含む設定など）で変える
- `encoding=utf-8-bom` など: 出力の文字コード。**テンプレートの出力は既定で BOM 無しの UTF-8**。BOM が要る `.ps1.tmpl` は `{{/* chezmoi:template:encoding=utf-8-bom */}}` を使う。[docs・推測: 描画物の BOM を `execute-template` で確かめた実測は無い]
- `line-endings=crlf|lf|native`: `modify_` テンプレートの `diff` で改行が食い違うとき
- `format-indent` / `format-indent-width`: `toJson`・`toToml`・`toYaml` のインデント
- `missing-key`

## 検査 [docs・実測]

- 断片: `chezmoi execute-template '{{ .chezmoi.os }}'`。ファイル全体: `chezmoi execute-template < f.tmpl`（`-f` でファイル名を引数に）。
- 設定テンプレート: `chezmoi execute-template --init --promptString email=me@example < .chezmoi.toml.tmpl`。`--init` が無いと init 専用関数が使えない。
- 実際に出る内容は `chezmoi cat ~/target`（宛先の実ファイルではなく、あるべき内容）。
- `execute-template` は宛先に何も書かないが、テンプレート内の `output` / `exec` は**実行される**。[推測: 関数の定義から]
- `.tmpl` は pre-commit の linter が素通りする。描画後の検査はこのリポジトリでは `lint_templates.py`（dotfiles-conventions）。
