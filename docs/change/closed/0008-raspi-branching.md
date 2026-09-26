# CHG-0008: Raspberry Pi（64bit / ヘッドレス）を導入対象に加える

- **状態**: Done
- **更新日**: 2026-09-26
- **終了日**: 2026-09-26
- **基準**: 導入対象は Windows / Ubuntu / WSL / macOS の 4 つ。Linux の分岐は
  WSL / native の 2 値のみで、アーキテクチャ軸と GUI 有無の軸が無い

> **この文書は当時の記録。** 現在の仕様は
> [プロジェクト構造](../../spec/structure.md#raspberry-pi)。
>
> 実機で 3 周した記録を含む。1 周目は ruby のビルドで停止、2 周目は
> `chezmoi init` 未実行で分岐が発動せず、3 周目で完走した。
> **途中で撤回した判断（ruby を Pi から外す / GitHub CLI の APT 鍵を
> 自動更新する）もそのまま残している。**

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
| 5 | 実機の Raspberry Pi で apply を完走させる | **完了**（2026-09-26。3 周目で達成） |
| 6 | 判定を `chezmoi update` だけで効く形にする | **完了**（2026-09-26） |

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

### 判定を `[data]` から `includeTemplate` へ移した（2 周目の教訓）

2 周目の実機適用で **raspi 分岐が 1 つも発動しなかった**。原因は判定の置き場所。

```text
chezmoi: warning: config file template has changed, run chezmoi init to regenerate config file
```

`[data] is_raspi` は `chezmoi init` のときにしか書かれない。**`chezmoi update` は
`git pull` + `apply` であって `init` を呼ばない**ため、判定が生成されず全分岐が
「非 raspi」に倒れた。実機では `code` を 219 MB 更新し、GUI パッケージと ClamAV も
そのまま導入された。

**`[data]` 方式が間違っていたわけではない。** `init` を都度実行すれば成立する。
問題は、普段の運用が `chezmoi update` 中心で **`init` を忘れやすい**こと。
`apply` は警告を出すが、大量の出力に埋もれて見逃す（実際に見逃した）。
「README に手順を書く」で守らせる設計が弱かった。
**運用が `chezmoi update` 中心なら、`init` を前提にした設計を選んではいけない。**

`home/.chezmoitemplates/is-raspi` へ移し、参照側は毎回評価する形にした。

```gotmpl
{{ $raspi := eq (includeTemplate "is-raspi" .) "true" }}
```

`is_raspi` をデータで渡せば検出より優先されるので、`lint_templates.py` の
raspi 軸と手動での強制はそのまま使える。

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

終了時点で残っているもの。いずれも Raspberry Pi の運用を妨げない。

- **`rust` / `go` の個別確認はしていない。** 3 周目で
  `mise all tools are installed` を確認したので導入自体は成立しているが、
  どちらがプレビルドで入ったかは見ていない
- **`LC_ALL=ja_JP.UTF-8` の影響は未確認。** ロケール未生成なら警告が出るはず
  だが、3 周目のログには出なかった。問題が出たら対処する
- **`.chezmoi.toml.tmpl` は `lint_templates.py` の除外対象。** テンプレート
  コメントの `*/` 事故のように lint では捕まらない壊れ方がある。
  変更したら `chezmoi execute-template --init` で描画を確かめる
- **32bit（armhf）は対象外のまま。** AI CLI 4 本が arch 判定で拒否するため、
  分岐では解決しない

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
| `121_ubuntu.sh.tmpl` | VS Code の APT ソース重複を掃除 | `vscode.list` と `vscode.sources` が二重登録され `apt update` が毎回警告。`110_native` は raspi で無視されるのでここに置く | **完了** |
| `111_microsoft.sh.tmpl` | `vscode.sources` があれば `.list` を作らない | 重複の再発を防ぐ | **完了** |
| GitHub CLI の APT 鍵を自動更新 | **やらない**（一度書いて撤回） | `121_ubuntu` は gh の APT 登録・鍵に触らない方針で、`test_github_cli_has_no_separate_apt_install` が守っている。手当ては `troubleshooting.md` へ | **撤回** |
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
- **2026-09-26**: 2 周目の実機適用。**ruby は実証、分岐は 1 つも発動せず**。
  `all_compile` の縮小が効き、ruby はプレビルドで 57.3 秒（前回は 956 秒で失敗）。
  一方 `chezmoi init` を通していなかったため `[data] is_raspi` が無く、
  raspi 分岐が全部「非 raspi」に倒れた
- **2026-09-26**: 判定を `[data]` から `.chezmoitemplates/is-raspi` へ移した。
  運用が `chezmoi update` 中心で `init` を呼ばないため。
  この教訓は `AGENTS.md` へ「`chezmoi init` を前提にした設計にしない」として
  一般化した
- **2026-09-26**: 2 周目までに入った GUI 一式・VS Code・ClamAV を消す
  `scripts/raspi/uninstall_gui.sh` を追加。xrdp も手動導入だが i3 セッション
  前提なので対象に含めた（ユーザー判断）。ブラウザ類と `~/.vscode-server` は残す

## 終了結果

**採用・配備済み。** 2026-09-26 の 3 周目で、実機（Ubuntu 22.04 / aarch64 /
Raspberry Pi）の `chezmoi update` が 45 秒で完走し、raspi 分岐が全て発動した。

### 判定が効いた証拠

```console
$ chezmoi execute-template '{{ includeTemplate "is-raspi" . }}'
true
```

`chezmoi init` は実行していない。`chezmoi update` だけで効いた（段 6 の狙いどおり）。

### 分岐が効いた証拠（適用ログの「出なかったもの」）

| 期待 | ログの観測 |
| --- | --- |
| GUI パッケージを入れない | 基本ツールは `manpages-ja` / `python3-tomlkit` / `tig` / `tree` / `curl` / `git` / `jq` / `unzip` / `wget` / `xdg-utils` のみ。`xsel` `i3` `rofi` `polybar` `lxappearance` が**無い** |
| `xdg-user-dirs-update` を飛ばす | 「既知のフォルダを整理します」が**出ない** |
| `systemctl --user mask` を飛ばす | 「i3wm で GUI アプリケーションを使うための設定」が**出ない** |
| ClamAV を入れない | 「ClamAV をインストール/更新します」が**出ない** |
| `110_native` を無視する | VS Code の apt 更新が**走らない** |
| apply が完走する | Herdr integration（`~/.copilot/hooks/herdr-agent-state.sh`）まで到達 |

### 併せて解消したもの

| 項目 | 結果 |
| --- | --- |
| ruby のソースビルド失敗 | `mise all tools are installed`。2 周目で 57.3 秒のプレビルド導入に成功済み（1 周目は 956 秒で BUILD FAILED） |
| VS Code の APT 二重登録 | `apt update` から `vscode.list` と `vscode.sources` の重複警告が**消えた**（2 周目は大量に出ていた） |
| `libyaml-dev` | 導入済みで維持 |

### 残したもの（意図的）

- **GitHub CLI の `NO_PUBKEY` 警告は残っている。** `121_ubuntu` は gh の APT
  登録・鍵に触らない方針で、`test_github_cli_has_no_separate_apt_install` が
  それを守っている。手当ては
  [トラブルシューティング](../../spec/troubleshooting.md)に記載した
- **2 周目で入った `code` / GUI 一式 / ClamAV は残っている。** `.chezmoiignore`
  は展開を止めるだけで、apt で入れたパッケージは消さない。終了後に
  `scripts/raspi/uninstall_gui.sh` を用意し、実機で実行した
- `.chezmoi.toml.tmpl` を変更したため
  `run chezmoi init to regenerate config file` の警告が出る。判定はもう
  `[data]` に依存しないので実害は無い。気になれば `chezmoi init` を 1 回打つ

### 学び（`AGENTS.md` へ一般化した）

- **`chezmoi init` を前提にした設計にしない。** 運用は `chezmoi update` 中心で
  `init` を呼ばない。マシン判定は `.chezmoitemplates/` に置き、`apply` の
  たびに評価させる
- **裏を取らずに原因を断定しない。** 「mise の ruby は常にソースビルド」と
  思い込んで ruby を Pi から外しかけた。実際はプレビルドが既定で、
  arm64 版も存在し、真犯人は `all_compile` だった
- **設定ファイルのコメントは参照だけにする。** 説明は `docs/` が正本
