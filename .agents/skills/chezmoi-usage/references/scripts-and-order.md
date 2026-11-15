# scripts・適用順序・hooks・interpreters

印: `[docs]` 公式 / `[src]` ソース / `[実測]` v2.67.0（この worktree で隔離実行）/ `[推測]`。

## 適用順序 [docs]

1. source state・宛先を読み、ターゲット状態を計算する
2. `run_before_` を**辞書順**で実行
3. ファイル・ディレクトリ・外部・symlink・（属性なしの）scripts を、**属性を除いたターゲット名の辞書順**で更新。ディレクトリはその中のファイルより先
4. `run_after_` を辞書順で実行

- `create_alpha` と `modify_dot_beta` なら `.beta` が `alpha` より先（属性を除いた名前で並ぶ）。
- 並べ方は 3 桁の番号接頭辞で管理する（このリポジトリの番号体系は dotfiles-conventions）。
- 隔離実行で、`.chezmoiscripts/` のサブディレクトリ（`100_a/`・`200_b/`）の scripts と、ルート直下の scripts が、フェーズごとにパスの辞書順で並ぶことを確認した [実測]。
- chezmoi は、実行中に source / 宛先が変わらないことを前提にする。`run_before_` で source や宛先を書き換えるのは前提違反で、挙動は未定義。[docs]
- 外部は更新フェーズで取得される。`run_before_` はその回の外部に依存しない。[docs]

## 実行条件と状態 [docs・src・実測]

| 種類 | 実行条件 | 状態の持ち方（`chezmoistate.boltdb`） |
| --- | --- | --- |
| `run_` | 毎回の `apply` | なし |
| `run_once_` | **同じ内容**（テンプレート描画後の SHA256）がまだ成功していないとき | `scriptState` バケットに内容のハッシュ |
| `run_onchange_` | そのスクリプトの**ターゲットパスで最後に成功した内容**と違うとき | `entryState` バケットにパスごとの内容のハッシュ |

- `once_` は内容だけがキー。**別名で同じ内容を置いても再実行されない**（`run_once_x.sh` を複製して `run_once_y.sh` を足しても走らない [実測]）。逆に、内容を変えれば走る。失敗したものは次回も走る。
- `onchange_` はパスがキー。**改名すると内容が同じでも走る**（`run_onchange_o.sh` → `run_onchange_o2.sh` で再実行 [実測]）。
- 状態は成功後に記録される。実行が失敗すると記録されず、次の `apply` で再試行される。[src] `TargetStateScript.Apply`
- テンプレートが**空または空白だけ**になったスクリプトは実行されない（動的な無効化に使える）。[docs]
- 別ファイルの変更で `onchange_` を走らせるには、そのハッシュをスクリプトに埋める: `# hash: {{ include "x.ini" | sha256sum }}`。埋めたファイルは `.chezmoiignore` に書く。[docs]
- `git-repo` 外部の更新で走らせるには、`run_onchange_after_` に `output "git" "-C" ... "rev-parse" "HEAD"` をコメントで埋める。定期実行は日付（`now | date "2006-01-02"`）を埋める。[docs] FAQ
- 状態の消去: `chezmoi state delete-bucket --bucket=entryState`（onchange）/ `--bucket=scriptState`（once）。[docs]

## 実行の作法 [docs]

- スクリプトは一時ディレクトリに実行ビット付きで書き出して `exec` する。**shebang が必須**（実行可能バイナリでもよい）。`.tmpl` で先頭に改行が入ると `exec format error` になる（`{{ if ... -}}` のように `-` で詰める）。
- `$TMPDIR` が `noexec` なら `permission denied`。`scriptTempDir` で変える。
- 作業ディレクトリは、宛先ツリーで最初に存在する親ディレクトリ。
- NixOS・Termux のように `/bin/bash` が無い環境は、`#!{{ lookPath "bash" }}` か `#!/usr/bin/env bash`。
- 環境変数: `CHEZMOI=1`、`CHEZMOI_OS`・`CHEZMOI_ARCH` など。追加は設定の `[scriptEnv]`。
- **`run_` スクリプトの中から `chezmoi` を呼ばない**（永続状態のロックで `timeout obtaining persistent state lock`）。書き込みロックを取るのは `add`・`apply`・`edit`・`forget`・`import`・`init`・`state`・`unmanage`・`update`、読み取りは `diff`・`status`・`verify`。
- 冪等にする。`diff` は既定でスクリプトの内容を出し、`status` は `R`（Run）で出す。出したくなければ `diff.exclude = ["scripts"]` / `status.exclude`。
- `--dry-run` では scripts は実行されない。[docs] ただし `modify_` は実行される（[attributes.md](attributes.md#modify_-スクリプト)）。

## hooks

- [docs・src] 設定ファイルの `[hooks.<event>.pre|post]`。event はコマンド名（`add`・`apply`…）・`git-auto-commit`・`git-auto-push`・`read-source-state`。`command` + `args` か `script`（interpreters 経由）。
- **hooks は `--dry-run` でも必ず実行される**。速く、冪等に。環境変数 `CHEZMOI_COMMAND`・`CHEZMOI_COMMAND_DIR`・`CHEZMOI_ARGS`。
- `read-source-state.pre` は source state を読む直前に走る。`chezmoi update` は `git pull` してから適用に入る（`applyArgs` → `newSourceState`）ので、**pull 後の source** を読む前に走る。[src] `updatecmd.go`・`config.go`
- hooks は**既存の設定ファイルから**読まれる。設定テンプレートへ hook を足しても、`chezmoi init`（か `update --init` / `apply --init`）を 1 回通すまで、その機械では有効にならない。[推測: 設定の生成と読み込みの関係から。hook の読み込み経路は `config.go` で確認、init 前の挙動を実機では確かめていない]
- pre hook が失敗すると、そのコマンドは中断する（`runHookPre` のエラーをそのまま返す）。[src]

## interpreters

- [docs] Windows は `.bat`・`.cmd`・`.com`・`.exe` を直接実行。他の拡張子は `PATH` 上の interpreter が要る。
- 既定: `.nu`→`nu`、`.pl`→`perl`、`.py`→`python3`、`.rb`→`ruby`、`.ps1`→下記。追加・上書きは `[interpreters.<拡張子(ドット無し)>]`（`command`・`args`）。
- `.tmpl` の scripts は `.tmpl` を外した次の拡張子で interpreter を選ぶ（`x.ps1.tmpl` は `.ps1`）。
- **`.ps1` の既定は版で違う**:
  - v2.67.0（このリポジトリの版）: Windows は `powershell -NoLogo`（Windows PowerShell）。[src] `v2.67.0/internal/cmd/util_windows.go`
  - v2.69.4 以降: `pwsh` を優先し、無ければ Windows では `powershell` へ（`-NoLogo -File`）。unix では `pwsh` が無ければ interpreter 無し。[docs・src]
  - chezmoi を更新すると、`pwsh` が入っている Windows 機で `.ps1` の実行系が 5.1 から 7 へ**黙って変わる**。BOM・文字コードの前提（このリポジトリは 5.1 向けに BOM を付ける）は、`[interpreters.ps1]` で固定して守る。[推測: 更新後の実機の挙動は未検証。Windows は未確認]
