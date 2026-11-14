# 落とし穴（症状 → 原因 → 対処）

印: `[docs]` 公式 / `[src]` ソース / `[実測]` v2.67.0 を隔離実行 / `[推測]`。

## `.chezmoiremove` と source の inconsistent state

- **症状**: `apply` 全体が `chezmoi: .foo: inconsistent state (<source のパス>, remove)` で失敗する。他のファイルも適用されない。
- **原因**: `.chezmoiremove` のパターンは**宛先を glob して**一致した実在の項目ごとに「削除」の項目を作る。同じターゲットの source の項目（`dot_foo` など）があると、1 つのターゲットに 2 つの項目が競合する。[src] `sourcestate.go`（`SourceStateAbsent` を足し、複数なら `InconsistentStateError`）
- **条件**: 宛先に**実在するときだけ**起きる。宛先に無ければ失敗せず、source の内容が普通に作られる [実測]。そのため「復活させた後、一部の機械だけ止まる」形になる。
- **対処**: source に同名を復活させる前に、`.chezmoiremove` から外す。`.chezmoiignore` に載せたターゲットは削除の対象にならない（競合もしない）。
- **このリポジトリでの対策**: `hooks.read-source-state.pre`（`scripts/clean_stale_source.py`）。hooks は既存の設定ファイルから読まれるので、設定の再生成（`chezmoi update --init` か `chezmoi init`）を通すまでその機械では効かない。`init` を前提にしてよいことは [ADR-0038](../../../../docs/adr/0038-allow-chezmoi-init-dependency.md)（[下](#update-は-init-を呼ばない)）。
- `.chezmoiremove` はソースから消えたものを宛先から片付けるための仕組みで、移行が行き渡ったら消す。ディレクトリを消すなら中身を並べずディレクトリ自体を書く。

## update は init を呼ばない

- **症状**: 設定テンプレート（`.chezmoi.toml.tmpl`）や、その `[data]` を直したのに、他の機械・自分の機械で反映されない。`apply` が「config file template has changed, run chezmoi init」と警告する。
- **原因**: `chezmoi update` は `git pull --autostash --rebase` と `apply` だけ。設定ファイル（`chezmoi.toml`）は `init` か `--init` を付けたときにしか再生成されない。[docs・src] `applyArgs`（`options.init` のときだけ `createAndReloadConfigFile`）
- **対処**: 機械ごとに変わる判定は `.chezmoitemplates/` の共有テンプレートへ置き、描画のたびに評価させる。設定の再生成が要るときは `chezmoi update --init` / `chezmoi init --apply`。`[data]` に入れた値・`hooks`・`interpreters` は `init` 前に古いまま。
- **付記**: v2.74.1 で `init --apply` が確実に apply を実行し、設定テンプレートのデータを再読み込みするよう直った（以前の版に不具合があった）。

## `.chezmoiignore` が効かない

- パターンは**ターゲットのパス**。`dot_foo` と書くと一致しない（`.foo` と書く）。[docs・実測]
- テンプレートとして描画される。`{{ if }}` の外に出るパターンを意図せず書いていないか。`chezmoi ignored` で実際の無視の一覧を見る。
- 除外（`!`）は包含より優先。ディレクトリ自体（`dir/`）と中身（`dir/**`）は別のパターン。
- サブディレクトリの `.chezmoiignore` はそのディレクトリにだけ効く。

## scripts が走らない / 走りすぎる

- `run_once_`: 内容が同じなら**別名でも走らない**。`run_onchange_`: **改名すると走る**。どちらも成功時だけ状態に記録される。[実測]
- 描画結果が空・空白だけなら実行されない。`.tmpl` の先頭の改行は `exec format error`。
- `chezmoi diff` / `status` には「走る」ことしか出ず、効果は出ない。
- 状態を消して走らせ直す: `chezmoi state delete-bucket --bucket=entryState`（onchange）/ `scriptState`（once）。
- 外部（`.chezmoiexternal`）に依存する処理は `run_after_` に置く（`run_before_` は取得前に走りうる）。[docs]

## dry-run・diff は安全ではない

- hooks と `modify_` スクリプトは dry-run でも実行される。`modify_` に副作用（書き込み・通信）を持たせない。[docs・実測]

## modify_ の書き方

- 標準入力が空（ファイル無し）でも完全な内容を出す。出力が空だとファイルが空になる。
- `chezmoi:modify-template` を使うとき、ファイル名に `.tmpl` を付けない。[docs]
- スクリプトの interpreter が要る環境（Python の版など）は `[interpreters.py]` で固定する。このリポジトリの例は `home/.chezmoi.toml.tmpl` と dotfiles-conventions。

## テンプレート

- `.chezmoitemplates` の中は `.` を渡さないと `nil`。`{{ template "x" . }}`。[docs]
- `.chezmoidata` はテンプレートにできない。動的な値は設定テンプレートか `output` で。[docs]
- `prompt*` は設定テンプレートだけ。
- `.ps1.tmpl` の BOM は `chezmoi:template:encoding=utf-8-bom`。[docs・推測]
- `.tmpl` ではないファイルに `{{ }}` を書いても展開されない。`.tmpl` を付け忘れると、そのまま配備される。
- シェルへ値を埋めるときは `quote` ではなく `shellQuote`（v2.72.0〜。v2.73.1 で二重バックスラッシュの不具合が直った）。

## 状態・ロック・環境

- `timeout obtaining persistent state lock`: 別の chezmoi が動いている、または `run_` スクリプトが `chezmoi` を呼んでいる。[docs]
- `permission denied`（一時ファイルの exec）: `$TMPDIR` が `noexec`。`scriptTempDir` を設定する。[docs]
- `~/.ssh/config` が group 書き込み可になる: `umask` 設定。[docs]
- `chezmoi edit` で空のバッファ: エディタが fork する。`--wait` / `-f` を付ける。[docs]
- `chezmoi add` が外部の暗黙ディレクトリで失敗: source に `.keep` を作る。[docs]

## 外部

- 既定では再取得しない（`refreshPeriod` が 0）。`-R` で強制。[docs]
- `git-repo` は組み込み git では使えない。
- `archive` の `include`・`exclude` はアーカイブ内のパスで照合する。[docs]

## 版の差

- v2.67.0 → 最新で、`.ps1` の既定 interpreter（Windows は `pwsh` 優先）・`chezmoi remove` の撤去・`unmanaged --include` 等が変わった。[sources.md](sources.md#版ごとの差分v2670-以降)。
- このリポジトリの挙動は v2.67.0 で確かめる。新機能を使うなら `.chezmoiversion` と、各機械の版を確かめる。
