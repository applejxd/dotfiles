# 特殊ファイル・ディレクトリ

印: `[docs]` 公式 / `[src]` ソース / `[実測]` v2.67.0 / `[推測]`。

## 読み込み順 [docs]

1. `.chezmoiroot`（source のルートから。他より先）
2. `.chezmoi.$FORMAT.tmpl`（`init` と `--init` のときだけ設定を生成）
3. `.chezmoidata.$FORMAT` / `.chezmoidata/`（テンプレートより先に読む）
4. `.chezmoitemplates/`
5. `.chezmoiignore`
6. `.chezmoiremove`
7. `.chezmoiexternal.$FORMAT` / `.chezmoiexternals/`（辞書順）
8. `.chezmoiversion`（どの操作より先に検査）

`.chezmoiroot` を使うなら、`.chezmoi.$FORMAT.tmpl` など他の「ルートのファイル」も新しい根へ移す。`..` を含む値は v2.72.0 から拒否される。

## `.chezmoiignore` [docs・実測]

- **テンプレートとして描画される**（`.tmpl` が無くても）。サブディレクトリの `.chezmoiignore` はそのサブディレクトリにだけ効く。
- パターンは `doublestar.Match` で、**ターゲットのパス**に対して照合する。`dot_foo` ではなく `.foo` と書く（`dot_foo` と書くと無視されないことを v2.67.0 で確認 [実測]）。
- `!` で除外（無視の解除）。除外は包含より常に優先。`#` コメントは行頭か空白の後。
- 無視されたターゲットは管理対象から外れる（`managed` に出ず、`ignored` に出る）。`.chezmoiremove` でも消されない。
- `backups/` はディレクトリ自体、`backups/**` は中身。両方要るときは両方書く。
- 無視ディレクトリ内の `.chezmoiexternal` の項目も無視される。
- 例（OS で出し分ける）:

```text
{{- if ne .chezmoi.os "windows" }}
AppData
{{- end }}
```

## `.chezmoiremove` [docs・src・実測]

- テンプレートとして描画される。「削除するターゲット」の一覧（パターン）。
- `.chezmoiignore` のターゲット、`!` で除外したものは削除されない。
- **宛先に実在するものにだけ一致する**（宛先を glob して照合）。source に同じターゲットがあり、かつ宛先にも実在すると `inconsistent state` で止まる（宛先に無ければ止まらない）。詳細は [pitfalls.md](pitfalls.md#chezmoiremove-と-source-の-inconsistent-state)。
- 危険なので、先に `chezmoi apply --dry-run --verbose` で確かめる。
- 個別の削除は `remove_` 接頭辞のファイルでも書ける（[attributes.md](attributes.md)）。

## `.chezmoiexternal.$FORMAT` / `.chezmoiexternals/` [docs]

- テンプレート。キーは**ターゲットパス**（ファイルの置かれたディレクトリからの相対）。`type` は `file` / `archive` / `archive-file` / `git-repo`。
- `url`（`https`・`http`・`file`）または `urls`（順に試す）。`checksum.sha256` などで検証できる。
- `file` / `archive` は取得結果をキャッシュし、`refreshPeriod`（例 `168h`）ごとに取り直す。既定は 0 で**取り直さない**。強制は `-R` / `--refresh-externals`。
- `git-repo` は無ければ `git clone`、あれば `git pull`。組み込み git（`useBuiltinGit`）では使えない。
- `archive` の `exact`・`stripComponents`・`include` / `exclude`（アーカイブ内のパス。ターゲットのパスではない）。`archive-file` の `path` は `./` の有無を `tar tzf` で確かめる。
- `.chezmoiexternals/` はファイルごとに外部定義を持てるが、サブディレクトリの外部は未対応（issue #4274）。
- 外部が暗黙に作るディレクトリへ `chezmoi add` すると失敗する（`.keep` を置く回避策。issue #1574 / #2006）。`re-add` は外部を対象にしない。
- v2.70.0 以降、同じターゲットへ複数の外部を 1 ファイルで書ける（`targetPath`）。v2.73.2 から `external_` ディレクトリ内の `.chezmoidata` は読まない。
- 外部の取得は適用（update）フェーズ。`run_before_` は、その回に取得される外部に依存してはいけない。`run_after_` は依存してよい。[docs] application-order

## `.chezmoidata.$FORMAT` / `.chezmoidata/` [docs]

- 静的なデータ（json・jsonc・toml・yaml）。**テンプレートにはできない**（テンプレートエンジンより先に読むため）。動的な値は設定テンプレートの `[data]`、または `output` / `fromJson` などで実行時に取る。
- 辞書だけが再帰的にマージされる。リストは置き換わる。辞書順で後ろが勝つ。
- テンプレートのデータの優先: chezmoi 自身の変数 < `.chezmoidata` < 設定ファイルの `[data]`（後ろが勝つ）。

## `.chezmoitemplates/` [docs]

- 中のファイルは（`.tmpl` が無くても）テンプレート。`{{ template "name" . }}` か `includeTemplate` で呼ぶ。
- **文脈 `.` を明示して渡さないと `nil`**。`.chezmoi.os` などを使うなら `.` を渡す。複数の値は `dict` で渡す。
- 名前は `.chezmoitemplates/` からの相対パス。

## `.chezmoiscripts/` [docs]

ルート直下にあると、スクリプトが対応するターゲットのディレクトリを作らずに実行される。`run_` 接頭辞は要る。サブディレクトリに分けても、順序は属性を除いたパスの辞書順（[scripts-and-order.md](scripts-and-order.md)）。

## `.chezmoi.$FORMAT.tmpl`（設定テンプレート） [docs]

- `chezmoi init`（と `--init` を持つコマンド）が設定を生成する。**普段の `update` / `apply` は再生成しない**。
- 使えるもの: 設定の `data`・全テンプレート関数・`init` 関数（`promptStringOnce` など）。使えないもの: `.chezmoidata`・`.chezmoitemplates`。
- `prompt*` は設定テンプレートの中だけ（毎回の描画で対話させないため）。`chezmoi execute-template --init --promptString k=v < .chezmoi.toml.tmpl` で試せる。
- 設定テンプレートを変えると、`apply` / `update` が「config file template has changed, run chezmoi init」と警告する（`warnings.configFileTemplateHasChanged`）。[src]

## `.chezmoiversion` [docs]

最低限の chezmoi の版（semver）。古いと source state の解釈を拒否する。新しい機能（例 `chezmoi:modify-template`・`--init`）を使うときに更新する。[推測: どの機能がどの版から、は個別に確かめていない]
