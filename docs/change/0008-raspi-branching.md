# CHG-0008: Raspberry Pi（64bit / ヘッドレス）を導入対象に加える

- **状態**: In progress
- **更新日**: 2026-09-25
- **基準**: 導入対象は Windows / Ubuntu / WSL / macOS の 4 つ。Linux の分岐は
  WSL / native の 2 値のみで、アーキテクチャ軸と GUI 有無の軸が無い

## 目的と非目的

**目的**: 64bit の Raspberry Pi OS（ヘッドレス）で `chezmoi apply` が完走し、
画面が無い機械に GUI 一式・GPU 前提のツール・ソースビルドを入れない状態にする。

**非目的**:

- **32bit（armhf）対応。** AI CLI 4 本すべてが arch 判定で `armv7l` を拒否する
  ため、分岐では解決しない。「対象外」と明記する
- デスクトップ構成の Raspberry Pi への対応。必要になってから軸を足す
- Raspberry Pi 固有の設定（`/boot/firmware/config.txt`、`raspi-config`、GPIO、
  zram、log2ram）を chezmoi へ取り込むこと。`scripts/raspi/` のままにする

**発端**: 「raspi 向けに chezmoiscripts や mise などのインストール内容を
分岐させた方がいいところある？」という網羅調査の依頼。

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | 網羅調査（arm64 資産の実在確認、破綻箇所の特定） | **完了**（2026-09-25） |
| 2 | 既存バグの修正（WSL ガードの不一致） | **完了**（2026-09-25） |
| 3 | `all_compile` を python 限定へ絞る | **完了**（2026-09-25） |
| 4 | `is_raspi` の導入と分岐の実装 | **完了**（2026-09-25） |
| 5 | 実機の Raspberry Pi で `chezmoi init` から通す | **進行中**（2026-09-26 に 1 周目。3 つの誤りが出た） |

## 現在地

### 参照側の書き方

`.chezmoi.toml.tmpl` が `[data] is_raspi = true` を出し、参照側は
`{{- if and (hasKey . "is_raspi") .is_raspi }}` の形で書く。
**`chezmoi init` をし直していないマシンには鍵自体が無い**ので、
鍵の不在を既存動作（= 非 raspi）として扱う必要がある。

### 見つけた既存バグ: WSL ガードが機能していなかった

`home/.chezmoiignore.tmpl` が無視対象を `190_wsl.sh` と書いていたが、
実際のターゲット名は `120_wsl.sh`。パターンが一致せず、**native Linux でも
WSL スクリプトが走って `/etc/wsl.conf` を書いていた**。

```text
$ chezmoi managed --include=scripts | grep wsl
.chezmoiscripts/100_linux/120_wsl.sh        ← 実ターゲット名
（無視リストの記述は 190_wsl.sh）
```

raspi とは独立の不具合だが、raspi では「WSL でもないのに WSL 設定が入る」
という形で目に見えるので、同じ案件で直した。

### `all_compile` は目的より広すぎた

`[settings] all_compile = true` の注記は「Tkinter のため」だが、mise の定義は
**全言語**でプリコンパイル済みバイナリを使わない、である。つまり `node` と
`ruby` までソースビルドになっていた。Raspberry Pi では Node のソースビルドが
数時間 + OOM リスクになる。

目的が Python だけなので `[settings.python] compile = true` へ絞った。
**x86 側にとっても正しい変更**で、raspi では更にこれ自体を外す
（画面が無いので Tkinter が要らない）。

mise 側も `all_compile` の自動既定を非推奨化しており、2027.8.0 で削除予定。

### 判定方法: `/etc/rpi-issue` だけでは足りなかった

当初は `/etc/rpi-issue` の有無だけで判定していたが、**実機で通らなかった**。
実機は Ubuntu 22.04 for Raspberry Pi（aarch64）で、このファイルは
Raspberry Pi OS のイメージ専用なので存在しない。

64bit の Raspberry Pi OS は `/etc/os-release` が `ID=debian` になるため
os-release でも判定できない（`raspbian` になるのは 32bit 版だけ）。
3 つの手がかりの OR にした。

| 手がかり | 拾えるもの |
| --- | --- |
| `/proc/device-tree/model` の存在 | ハードウェアの申告。OS を問わず Pi なら必ずある |
| `kernel.osrelease` に `raspi` / `-rpi-` | Ubuntu for Pi の `-raspi` フレーバー、Pi OS の `+rpt-rpi-` |
| `/etc/rpi-issue` の存在 | Raspberry Pi OS のイメージ |

> **テンプレートコメントに `*/` を書くと早期終了する。** 最初の修正で
> `**/etc/rpi-issue だけでは不足**` と書いたところ、`**/etc` の `*/` が
> Go テンプレートのコメントを閉じてしまい
> `comment ends before closing delimiter` で落ちた。
> `.chezmoi.toml.tmpl` は `lint_templates.py` の除外対象なので、
> **lint では検出されない**。`chezmoi execute-template --init` で確かめる。

### ruby のソースビルドが実機で失敗した — 原因は `all_compile` だった

実測 **956 秒で BUILD FAILED**。

```text
ruby@4.0.7 psych: Could not be configured. It will not be installed.
ruby@4.0.7 BUILD FAILED (Ubuntu 22.04 on aarch64 using ruby-build 20260924)
✗ gem:tmuxinator@latest  failed: Skipped due to failed dependency
mise ERROR Failed to install tools: core:ruby@latest, gem:tmuxinator@latest
chezmoi: .chezmoiscripts/100_linux/125_mise.sh: exit status 1
```

**最初は「mise の ruby は常にソースビルドだから Pi では外す」と判断したが、
これは裏を取らずに書いた誤りだった。** 公式ドキュメントを読むと、mise は
既定で `jdx/ruby` のプレビルドを落とし、**Linux arm64 (glibc) 向けも存在する**。
実機が落とそうとした 4.0.7 にも `ruby-4.0.7.arm64_linux.tar.gz` がある。

ソースビルドへ落ちた原因は **`all_compile = true`**。「全言語でプリコンパイル
済みバイナリを使わない」設定なので、ruby も強制的に `ruby-build` になっていた。
つまり **arm64 でも `libyaml-dev` でもなく、`all_compile` が原因**であり、
それは同じ案件で既に python 限定へ絞ってある。

| 当初の判断 | 訂正後 |
| --- | --- |
| mise の ruby は常にソースビルド | **既定はプレビルド**。無いときだけ ruby-build |
| arm64 にプレビルドが無い | **ある**（`jdx/ruby` の `arm64_linux`） |
| Pi では ruby を外す | **外さない**。`all_compile` の縮小で解決する |

採った対処は 3 つ。

1. **`all_compile` を `[settings.python] compile` へ絞る**（本来の修正）
2. **Pi では `[settings.ruby] compile = false`**。既定のフォールバックに入ると
   十数分かけてから失敗するので、プレビルドが無い時点で即エラーにする
3. **`libyaml-dev` を `121_ubuntu` の build tools へ**。プレビルドを使う限り
   不要だが、x86 / WSL がソースビルドへ落ちたときの保険
   （`125_mise` の apt ブロックは `python` 不在時しか走らない）

### ツール 1 個の失敗が apply 全体を巻き添えにしていた

ruby が落ちただけで `125_mise` が非ゼロを返し、**後続が丸ごと走らなかった**
（`126_agent_cli` / `140_herdr_integration` / `400_unix` の 3 本）。
AI CLI の導入で既に採っている「警告に留める」方式へ揃えた。
未導入のものは `mise ls --missing` で分かる。

### arm64 で心配が要らないと確認できた範囲

実際に資産の実在を確認した（静的な期待ではない）。

| 対象 | 確認方法 | 結果 |
| --- | --- | --- |
| AI CLI 4 本 | インストーラを取得して arch 判定部を読む | x64 / arm64 のみ。**armhf は exit 1** |
| mise の主要ツール | GitHub Releases / aqua registry / dev.yorhel.nl を照会 | `herdr` `tmux-builds` `lazygit v0.59.0` `fzf 0.53.0` `ncdu 2.9.1` `zenith` `neovim` `yazi` `ctop` `hadolint` `gwq` `deno` すべて arm64 資産あり |
| `aqua:dylanaraps/neofetch` | registry.yaml | bash スクリプト配布。アーキ非依存 |
| Claude の seccomp | npm パッケージのファイル一覧 | `vendor/seccomp/arm64/apply-seccomp` を同梱。`generate.py` の `seccomp_arch()` が既に `aarch64` を処理 |
| VS Code の APT リポジトリ | `binary-arm64/Packages` を取得 | HTTP 200。`dpkg --print-architecture` 由来なので分岐不要 |

## 未解決点

- **段 5 の 1 周目で 3 つの誤りが出た**（2026-09-26）。判定方法・ruby・
  失敗の伝播。いずれも直したが、**直した版はまだ実機で通していない**
- **`[settings.ruby] compile = false` の効きを実機で確認していない。**
  `jdx/ruby` に `ruby-4.0.7.arm64_linux.tar.gz` があることは確認したが、
  Pi で実際にプレビルドが選ばれるかは見ていない。もし選ばれなければ
  ソースビルドではなく**即エラー**になるので、失敗は早く分かる
- **`rust` / `go` は Raspberry Pi でも残した。** どちらもプリコンパイル済み
  バイナリが arm64 にあるので ruby のような問題は起きないはずだが、未確認
- `LC_ALL=ja_JP.UTF-8` を `shellenv.sh` が無条件に設定する。ロケールが
  生成されていないと毎コマンド警告が出る可能性がある。実機で確認する
- `.chezmoi.toml.tmpl` で判定するため、**`chezmoi init` を再実行しないと
  `is_raspi` が現れない**。既存マシンでは鍵が無く既存動作のままになる
- **`.chezmoi.toml.tmpl` は `lint_templates.py` の除外対象**。テンプレート
  コメントの `*/` 事故のように、lint では捕まらない壊れ方がある。
  変更したら `chezmoi execute-template --init` で必ず描画を確かめる

## 評価基準

**必須**:

- 既存の 4 OS の生成物が変わらない（`is_raspi` 不在で従来どおり）
- `scripts/lint_templates.py` と `test/` が全件通る
- ヘッドレス Pi で `chezmoi apply` が完走する（段 5）

**望ましい**:

- Pi に GUI パッケージ・VS Code・ClamAV・ソースビルドが入らない

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `.chezmoiignore.tmpl` | `190_wsl.sh` → `120_wsl.sh` | ターゲット名の不一致で WSL ガードが死んでいた | **完了** |
| `.chezmoi.toml.tmpl` | （なし）→ `[data] is_raspi` | 判定を 1 箇所に集める。`/proc/device-tree/model` + osrelease + `/etc/rpi-issue` の OR | **完了**（2026-09-26 に判定を修正） |
| `.chezmoiignore.tmpl` | （なし）→ raspi で GUI 資産と `110_native/` を無視 | 画面が無い機械に VS Code と i3 / polybar を入れない | **完了** |
| `mise/config.toml.tmpl` | `all_compile` → `[settings.python] compile` | 目的は Tkinter だけ。node / ruby のソースビルドは副作用 | **完了** |
| 同上 | raspi では `python.compile` も `pipx:nvitop` も出さない | 画面が無いので Tkinter が不要。nvitop は NVIDIA GPU 前提 | **完了** |
| `121_ubuntu.sh.tmpl` | raspi で GUI / `xdg-user-dirs` / `systemctl --user` / ClamAV を飛ばす | ヘッドレスでは前 3 つが `set -e` で apply を止め、ClamAV は常駐 1GB 超 | **完了** |
| `122_font_cica.sh` | （なし）→ fontconfig の有無で早期 return | `fc-cache` 不在で apply 全体が止まっていた | **完了** |
| `shellenv.sh.tmpl` | TeX Live の `x86_64-linux` 固定 → arch 分岐 | aarch64 では `aarch64-linux` | **完了** |
| `scripts/lint_templates.py` | （なし）→ raspi 軸を追加 | 新しい分岐が shellcheck / TOML 検査を素通りしないように | **完了** |
| `121_ubuntu.sh.tmpl` | build tools へ `libyaml-dev` を追加 | ソースビルドへ落ちたときの保険。既存の宣言は `python` 不在時しか走らない | **完了** |
| `125_mise.sh.tmpl` | `mise install` の失敗を警告に留める | ruby 1 個の失敗で後続 3 スクリプトが丸ごと走らなかった | **完了** |
| `mise/config.toml.tmpl` | raspi では `[settings.ruby] compile = false` | 既定のフォールバックに入ると十数分かけてから失敗する | **完了** |
| raspi で `ruby` / `gem:tmuxinator` を外す | **やらない**（一度やって撤回） | arm64 のプレビルドが `jdx/ruby` に実在する。原因は `all_compile` だった | **撤回** |
| 32bit（armhf）対応 | **やらない** | AI CLI 4 本とも arch 判定で拒否する。分岐では解決しない | **対象外** |
| Pi 固有設定の chezmoi 管理 | **やらない** | `scripts/raspi/browser_mem.sh` のままにする | **対象外** |

## 重要な更新

- **2026-09-25**: 起票。網羅調査の結果、raspi 固有の問題より先に
  **既存の WSL ガードのバグ**と**`all_compile` の範囲過大**が見つかった。
  どちらも raspi と独立に直す価値がある
- **2026-09-25**: 段 2〜4 を実装。実機検証（段 5）は未着手
- **2026-09-26**: 段 5 の 1 周目。実機で `chezmoi apply` が `125_mise` で停止した。
  **3 つの誤りが出た**。(1) 実機は Ubuntu 22.04 for Raspberry Pi で
  `/etc/rpi-issue` を持たず、**判定が効いていなかった**
  (2) ruby のソースビルドが 956 秒で失敗
  (3) ツール 1 個の失敗で後続 3 スクリプトが丸ごと走らなかった。
  いずれも修正済みだが、**直した版は実機で未検証**
- **2026-09-26**: ruby の対処を**撤回して差し替えた**。当初「mise の ruby は
  常にソースビルド」と判断して Pi から外したが、**裏を取らずに書いた誤り**。
  mise は既定で `jdx/ruby` のプレビルドを落とし、arm64 Linux 向けも実在する。
  ソースビルドへ落ちた原因は `all_compile = true` で、同じ案件で既に縮小済み。
  `ruby` / `gem:tmuxinator` は Pi でも宣言し、代わりに
  `[settings.ruby] compile = false` で徒労なフォールバックを止める
- **2026-09-26**: テンプレートコメントに `*/` を書くと Go テンプレートの
  コメントが早期終了すると判明（`**/etc/...` で踏んだ）。
  `.chezmoi.toml.tmpl` は lint の除外対象なので検出されない

## 終了結果

<!-- Done にするとき記入 -->
