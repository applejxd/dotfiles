# Raspberry Pi への導入（ヘッドレス）

Raspberry Pi（ARM の Linux）へ dotfiles を導入するときの仕様と、そこで起きる固有の問題（ruby のプレビルド・clang の標準ヘッダ・OOM・GUI 一式の削除）。全体の構成は [プロジェクト構造](structure.md)。

## Raspberry Pi

64bit の Raspberry Pi OS（ヘッドレス）を対象にします。**32bit（armhf）は対象外**です。
Claude Code / Copilot CLI / OpenCode V2 / oh-my-pi の公式インストーラーはいずれも
x64 と arm64 しか受け付けず、`armv7l` を検出すると明示的に終了します。

判定は `home/.chezmoitemplates/is-raspi` が単一ソースです。次の 3 つの OR で
判定し、`"true"` か空文字を返します。単独ではどれも取りこぼします。

| 手がかり | 拾えるもの |
| --- | --- |
| `/proc/device-tree/model` の存在 | ハードウェアの申告。OS を問わず Raspberry Pi なら必ずある |
| `.chezmoi.kernel.osrelease` に `raspi` / `-rpi-` | Ubuntu for Raspberry Pi の `-raspi` フレーバー、Raspberry Pi OS の `+rpt-rpi-` |
| `/etc/rpi-issue` の存在 | Raspberry Pi OS のイメージ |

参照側はこう書きます。

```gotmpl
{{ $raspi := eq (includeTemplate "is-raspi" .) "true" }}
```

**`chezmoi.toml` の `[data]` には置きません。** `[data]` でも判定自体は動きますが、
値が書かれるのは `chezmoi init` のときだけです。普段の運用は `chezmoi update`
（`git pull` + `apply`）が中心で、**これは `init` を呼びません**。

`init` を都度実行すれば `[data]` 方式でも成立します。ただし忘れると判定が
生成されず、全分岐が「非 raspi」に倒れます。`apply` の警告
（`config file template has changed, run chezmoi init to regenerate config file`）は
**大量の出力に埋もれて見逃します**（実機で見逃した経過は
[CHG-0008](../change/closed/0008-raspi-branching.md#判定を-data-から-includetemplate-へ移した2-周目の教訓)）。

手順で守らせる設計をやめ、`includeTemplate` で `apply` のたびに評価する形に
しました。`init` を実行してもしなくても同じ結果になります。

データで上書きもできます。`is_raspi` を渡すと検出より優先されるので、
テスト（`lint_templates.py` の raspi 軸）と手動での強制に使えます。

**`/etc/rpi-issue` だけでは足りません。** このファイルは Raspberry Pi OS 専用で、
Ubuntu for Raspberry Pi には存在しません（実機がそうでした）。
64bit の Raspberry Pi OS は `/etc/os-release` が `ID=debian` になるので、
os-release でも判定できません（`raspbian` は 32bit 版のみ）。

| 対象 | Raspberry Pi での扱い |
| --- | --- |
| `100_linux/110_native/`（VS Code 本体のみ） | 導入しない |
| i3 / rofi / polybar / lxappearance / xsel | 導入しない |
| `.config/i3`、`.config/polybar`、`.Xmodmap`、`.xsession`、`.xsessionrc` | 展開しない |
| `xdg-user-dirs-update`、`systemctl --user mask` | 実行しない（ヘッドレスでは失敗して apply が止まる） |
| ClamAV | 導入しない（`clamd` が常駐で 1GB 超を占める） |
| `pipx:nvitop` | 宣言しない（NVIDIA GPU が前提） |
| `[settings.python] compile` | 宣言しない（Tkinter が要らない） |
| `[settings.ruby] compile` | `false` を宣言する（後述） |
| Cica フォント | fontconfig が無ければスクリプト側で早期終了 |
| zram-tools / earlyoom | **Raspberry Pi だけで導入する**（[後述](platform-raspberry-pi.md#メモリが尽きても-ssh-できるようにする)） |

`xdg-user-dirs-update` は Raspberry Pi 以外でも、コマンドが無ければ（Server 版・WSL・
コンテナなど Desktop 環境の無い機械）既知フォルダの整理ごと飛ばします。

## ruby はプレビルドで入れる

`ruby` と `gem:tmuxinator` は Raspberry Pi でも宣言します。mise は既定で
`jdx/ruby` のプレビルド版を落とし、**Linux arm64 (glibc) 向けも用意されています**。

ruby がソースビルドへ落ちるのは、`all_compile = true` が**全言語で**
プリコンパイル済みバイナリを禁じるためです（実機でビルドが失敗した経過は
[CHG-0008](../change/closed/0008-raspi-branching.md#ruby-のソースビルドが実機で失敗した--原因は-all_compile-だった)）。
この設定を `[settings.python] compile` へ絞ったことで、ruby はプレビルドに戻ります。

Raspberry Pi では加えて `[settings.ruby] compile = false` を宣言します。
mise の既定は「プレビルドが無ければ `ruby-build` へフォールバック」で、
Pi でそこに入ると十数分かけてから失敗します。`false` にすると
**プレビルドが無い時点で即エラー**になり、長時間の徒労を避けられます。

`libyaml-dev` は `121_ubuntu` の build tools に入れてあります。プレビルドを
使う限り不要ですが、x86 / WSL がソースビルドへ落ちたときの保険です
（`psych` 拡張のビルドに要ります）。

## clang が C++ の標準ヘッダを見つけられるようにする

`121_ubuntu` は build tools の後で、**clang が選ぶ gcc の版**に合わせて
`libstdc++-<版>-dev` を入れます。版は `/usr/bin/clang -x c++ -E -v` の
`Selected GCC installation:` 行から取り（`14.2.0` のような形なら先頭の `14`）、
入れた後に `#include <cstdio>` が通ることを確かめます。版が判定できない・
パッケージが無い・確認が通らないときはエラーで止めます（黙って飛ばすと
`run_once_` が成功として記録され、やり直されないため）。

gcc の triplet から版を推測する方式は採りません（clang の選択と一致する保証が無いため。[観測](../research/chezmoi/structure-raspi-notes.md)）。`/usr/bin/clang` を明示するのも、conda などの
clang ではなく apt の clang を直すためです。

clang（`clang-tidy` も）は、C++ の標準ヘッダを探すときに最も新しい gcc の版の
ディレクトリを選びます。そのディレクトリは `libgcc-<版>-dev` だけでも作られ、
別のパッケージ（例: `libgccjit0`）がそれを引き込むことがあります。その版の
`libstdc++-<版>-dev` が無いと、`#include <cstdio>` すら `file not found` になります。

観測の記録は [記録](../research/chezmoi/structure-raspi-notes.md)。
版を決め打ちしないのは、Ubuntu の版ごとに gcc の版が違うためです。

`clang-tidy` は OpenCode の編集直後の lint で C/C++ に使います。

## ツール 1 個の失敗で apply を止めない

`125_mise` は `mise install` が失敗しても**警告に留めます**。非ゼロで抜けると、
ツール 1 個の失敗で後続の `126_agent_cli` / `140_herdr_integration` / `400_unix` が
丸ごと走らなくなるためです（実機で ruby が落ちたときに起きました）。
未導入のものは `mise ls --missing` で確認できます。

`140_herdr_integration` も同じ方針で、herdr や AI CLI が無いときは警告して飛ばします（`exit 0`）。
毎回走る `run_after_` なので、導入できた後の `apply` で設定されます。herdr が動いたうえでの異常
（不正な skill を返したなど）は、失敗のままにします。

## メモリが尽きても SSH できるようにする

Raspberry Pi 4（RAM 3.7GB、SD カード）は swap が 0 だと、メモリが尽きても
OOM キラーがなかなか動きません。その間カーネルはプログラムのコードを追い出しては
SD から読み直すため、**sshd も応答しなくなり、電源を抜くしかなくなります**
（[実機で起きた経過](../research/testing/raspi-oom-ssh-freeze.md)）。
`121_ubuntu` が Raspberry Pi でだけ次を入れます。

| 設定 | 値 | 理由 |
| --- | --- | --- |
| zram（`/etc/default/zramswap`） | `zstd`、RAM の 50%、優先度 100 | RAM を圧縮して swap にする。SD に swap を置くと読み書きが遅く、溢れたときに結局固まるうえ、SD も傷む。既定の 256MB では足りない |
| `linux-modules-extra-raspi` | zram モジュールが無いときだけ入れる | Ubuntu for Raspberry Pi は zram を別パッケージに分けている（約 95MB）。無いと `zramswap` が `Module zram not found` で起動しない |
| `vm.swappiness` | 100 | zram は速いので、早めに使わせる |
| `vm.page-cluster` | 0 | zram では先読みの効果が無い |
| earlyoom（`/etc/default/earlyoom`） | 既定のしきい値（空きメモリと空き swap の両方が 10% 以下）で最大のプロセスを止める。sshd / systemd / tailscaled は対象外 | 固まる前に重い処理を止めて、SSH できる状態を保つ |

earlyoom の `--avoid` の正規表現に空白や引用符を入れてはいけません。
systemd は `$EARLYOOM_ARGS` を空白で分割するだけで、引用符を解釈しないためです。
効いているかは `swapon --show` と `journalctl -u earlyoom -b` で確認できます。
systemd が動いていない環境（Docker の検証コンテナなど）では、設定ファイルだけ置いて
サービスの再起動を飛ばします。

## 入ってしまった GUI 一式を消す

raspi 判定が効く前の `apply`（2026-02 の初回と、CHG-0008 の 2 周目）では、
上の表で「導入しない」としたものが入りました。`.chezmoiignore` は展開を
止めるだけで、**既に入ったものは消しません**。`scripts/raspi/uninstall_gui.sh`
でまとめて取り除きます。

```bash
chezmoi execute-template '{{ includeTemplate "is-raspi" . }}'   # true でないと次の apply で戻る
scripts/raspi/uninstall_gui.sh --dry-run   # 消すものを表示するだけ
scripts/raspi/uninstall_gui.sh
```

| 種類 | 消すもの |
| --- | --- |
| apt | `i3 rofi polybar lxappearance xsel`、`code`、`clamav clamav-daemon`、`xrdp xorgxrdp` と、それらを消すと孤立する依存（X サーバ、`i3-wm` など） |
| APT ソース | `vscode.list` / `vscode.sources` / `microsoft-edge.list`。他のソースが使っていなければ `microsoft.gpg` も |
| ファイル | `~/.vscode`、`~/.config/Code`、`~/.config/i3`、`~/.config/polybar`、X 系ドットファイル、Cica フォント、xrdp / ClamAV のログと定義 DB |
| その他 | `xdg-desktop-portal-gnome` の mask、空の `~/thinclient_drives` |

`xrdp` は chezmoi ではなく手動で入れたものですが、セッションが `~/.xsession`
（`exec i3`）前提なので一緒に消します。次のものは残します。

- `~/.vscode-server`（Remote-SSH で繋いだときに VS Code が使う）
- chromium / firefox / chromedriver（chezmoi 由来ではない）
- 実行前から `autoremove` の対象だったパッケージ
- GitHub CLI の APT 登録（`121_ubuntu` と同じく触らない）

Raspberry Pi と判定できないとき（手がかりは `is-raspi` と同じ）と、対象以外の
パッケージが依存で巻き込まれるときは、何も消さずに中止します。

Raspberry Pi 固有のシステム設定（memlock など）は chezmoi では管理せず、
`scripts/raspi/` に置いたまま手動で実行します。
詳細は [CHG-0008](../change/closed/0008-raspi-branching.md) を参照。
