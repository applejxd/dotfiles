# シェル

シェルの起動ファイルの契約、マシン固有の設定の置き場、zsh の起動時間とプラグイン（zinit・fzf）、PowerShell のプロファイル。全体の構成は [プロジェクト構造](structure.md)。

## シェルの起動契約

シェルの主な利用者は AI エージェントである。OpenCode は `/usr/bin/zsh` を
非対話・非 TTY で起動し、`.zshenv` だけが読まれる。そのため、どのファイルが
どの起動形態で読まれるかを次のとおり固定する。

| ファイル | 読まれる起動 | 置いてよいもの |
| --- | --- | --- |
| `.zshenv` | 全 zsh（対話・非対話を問わない） | PATH と環境変数だけ（例外は表の下） |
| `.bash_profile` | login bash（非対話の login を含む。`bash -lc` など） | PATH と環境変数だけ |
| `~/.config/shell/shellenv.sh` | `.zshenv` と `.bash_profile` から読まれる（素の `bash -c` や非 login の bash は読まない） | PATH と環境変数だけ |
| `.bashrc` のガード前 | 対話 bash と、`.bash_profile` から読まれる login bash（素の `bash -c` は読まない） | `mise activate` と ROS の `setup.bash`（PATH のため） |
| `.zshrc`（先頭の `[[ -o interactive ]] \|\| return 0` の後）、`.bashrc` のガード後、`shellrc.sh` | 対話シェル | alias・関数・キー設定・補完・プラグイン・出力 |

`.zshenv` には環境変数のほかに例外が 1 つある。リポジトリ内にいる間 `TMPDIR` を
そのリポジトリの `.tmp` に向けるため、関数を 1 つ定義して `mkdir -p` を実行する
（出力はしない）。

`shellenv.sh` は mise の shims（`${MISE_DATA_DIR:-~/.local/share/mise}/shims`）を、
存在するときだけ PATH の先頭へ 1 回置く（継承した PATH に既にあれば先頭へ移す。venv の
`bin` が PATH にあればその直後）。非対話でも cwd の `mise.toml` の版で解決される。
版の再現性が要る操作（lint・ビルドなど）は shim ではなく `mise exec` を使う。
実測は[調査記録](../research/shell/mise-shims-resolution.md)。

WSL では `shellenv.sh` が `wslenv.sh` を読み、Windows 側のディレクトリ（`Windows` /
`System32`、PowerShell 5.1、PowerShell 7（`C:\Program Files\PowerShell\7` があるとき
だけ）、VS Code、Java）を PATH の先頭へ足す。`/etc/wsl.conf` の
`appendWindowsPath=false` で Windows の PATH は引き継がないため、`pwsh.exe` なども
ここで足したものしか名前で呼べない。入れ子のシェルで読み直しても重複しないよう、
PATH と `LD_LIBRARY_PATH`（`/usr/lib/wsl/lib`）は既にあれば足さない。足すための
補助関数は読み終えたら `unset -f` で消す（方針 1）。

Copilot CLI がツールとして起動するシェルへ渡す git の既定値（入力待ちにしない）は、
対話側の `shellrc.sh` にある `copilot()` 関数が、未設定の変数だけをコマンド前置きの
代入で入れる（空文字は空のまま、呼び出し元の環境は変えない）。値の正本は
`common.toml.tmpl` の `[agent_env]`（[詳細](agent-config-generation.md#shell-ツールの環境変数)）。

`.zshrc` の冒頭は `/etc/zsh/zshrc` の読み込みも含む（`.zshenv` の `no_global_rcs`
で自動では読まれないため、対話のときだけ読む）。

方針:

1. 非対話でも読まれる起動ファイル（表の `.zshenv` / `.bash_profile` /
   `shellenv.sh`、`.bashrc` のガード前）には alias・関数・出力・キー設定を置かない
   （`TMPDIR` の例外を除く）。
2. 対話判定は zsh の `[[ -o interactive ]]`、bash の `$-` で行う。TTY の有無は
   表示用の補助にとどめ、環境変数を並べて「人間か」を推測する判定は採らない。
3. 標準コマンドの意味を変える alias（`cat=bat`、`ls=eza`、`diff=colordiff`、
   `vi` / `vim` / `agent` など）は対話 rc（`shellrc.sh`）だけに置く。
4. 呼び出し元が明示した `LC_ALL` / `LANG` / `EDITOR` / `VISUAL` は上書きしない。
   未設定のときだけ既定値を決める。自動実行は入力待ちで止まらないようにするが、
   `EDITOR=true` のように成功を偽装する値は採らない。
5. 関数内の失敗は `exit` ではなく `return` で抜ける（`ccd` / `jcd` / `cdf`）。
   `zpack` は既存の出力先を上書きせず、一時ファイル経由で成功したときだけ移す。
6. 大きい関数は `~/.config/shell/functions/` に分け、`shellrc.sh` の末尾で読み込む
   （`archive.sh`: `extract` / `zpack` / `zunpack`、`cpp.sh`: `runcpp`）。
   テンプレート機能が要らないので素の `.sh` にし、pre-commit の shellcheck を効かせる。
   読み込み元が `shellrc.sh` だけなので、対話シェル専用であることは変わらない。
   小さい関数は `shellrc.sh` に残す。zsh の `autoload` は bash で使えないので採らない。

Nix 化・`rm` の alias 差し替え・環境変数の列挙による人間判定は採らない（検討した記事との比較は [記録](../research/shell/structure-shell-notes.md)）。

検査は `test/test_shell_startup.py`（非対話 zsh / login bash の alias・環境変数・
出力、`.zshrc` の早期 return、`shellenv.sh` 単体、`functions/` の読み込み、`zpack`、
`runcpp`）。一時 HOME に描画結果を
置いて実行し、zinit・mise・fzf・ネットワークは使わない。実機の対話シェルの
起動（プロンプトまで）は検査しない。

## マシン固有の設定の置き場

マシンごとに違う値（データセットの置き場、プロキシなど）は、リポジトリに書かず次のどれかへ置く。

| 置き場 | 何を置くか | いつ読まれるか | 注意 |
| --- | --- | --- | --- |
| `~/.config/shell/userenv.sh`・`.bash`・`.zsh` | 環境変数・プロキシ。例: `export PIS_EXTRA_READ="$HOME/dataset:/data2"` | シェルの起動ごと（`userenv.sh` は `shellenv.sh` が読む） | chezmoi の管理外。同じ場所の `.example` から作る。`PIS_EXTRA_READ` は読み取り専用で、詳細は [環境変数での追加](sandbox/fence-boundary.md#環境変数での追加) |
| `~/.config/mise/conf.d/*.toml` | `mise` の設定のマシン固有分 | `mise` が設定を読むとき | chezmoi の管理外。`[env]` は mise を有効化したシェルでしか効かない（**推測**。公式 docs では未確認） |
| `<起動ディレクトリ>/.opencode/sandbox.toml` | リポジトリごとの `read`・`write`・`network_allow` | `pis` の起動時 | パスがマシン依存なら、1 行目の環境変数のほうがよい（環境変数で足せるのは読み取りだけ） |

出典: `home/dot_config/shell/shellenv.sh.tmpl`（「User settings」の節が `userenv.sh` を読む）、
`home/dot_config/mise/config.toml.tmpl` の冒頭のコメント（`conf.d` の案内）。

## zsh の起動時間

現在は `zsh -i -c exit` で 0.24〜0.25 s（WSL2。改善前は 0.37〜0.40 s）。測定の記録は
[記録](../research/shell/zsh-startup-time.md)。
診断は `zmodload zsh/zprof` 後に `source ~/.zshrc; zprof`、区間ごとの時間は `EPOCHREALTIME` で測る。

効いた原因と対処:

- **未導入コマンドの `command -v` が約 10 ms**: PATH の `/mnt/*`（WSL の 9p）を走査するため。
  `.zshrc` は起動中だけ `/mnt/*` を PATH から外し、末尾で戻す（約 -60 ms）
- **`.zshenv` の shims 処理が約 40 ms**: 長い PATH に対する `${__p#*"…"}`（先頭 `*` の
  最短一致）が二次的に遅い。zsh では `path` 配列で処理する（`shellenv.sh`）。
  `.zshenv` は非対話の起動でも読まれるため全 zsh に効く
- **`mise activate zsh` の fork が約 30 ms**: 出力を `~/.cache/zsh/mise-activate.zsh` に
  キャッシュし、mise 本体が新しいときだけ作り直す。一時ファイルへ生成して成功時だけ
  `mv` で置き換え、失敗時は旧キャッシュを使う（旧キャッシュも無ければ直接 `eval`）

残り: 初回 `_mise_hook`（約 40 ms、環境の確定に必要なため同期のまま）と zinit の
同期ロード（zeno・fast-syntax-highlighting・pure）。

## シェルプラグインの取得

シェルの rc が読み込むプラグインのうち、下の表の 5 項目は起動時ではなく
`chezmoi apply` が `home/.chezmoiexternal.toml.tmpl` で取得します。rc は存在する
ときだけ読み込み、無くてもシェルは起動します（zinit が無い場合は案内を 1 行出し、
`zinit` を何もしない関数にします）。

zinit が管理するプラグイン（`yuki-yano/zeno.zsh`、`zsh-users/zsh-completions`、
`Aloxaf/fzf-tab` など）は apply では取得しません。`home/dot_zshrc.tmpl` の
`zinit light` / `zinit snippet` に任せており、zinit が起動時に未取得のものを
取得します。

| 取得先 | 取得元 | 種類 |
| --- | --- | --- |
| `~/.z` | rupa/z | git-repo（`--depth 1`） |
| `~/.zinit/bin` | zdharma-continuum/zinit | git-repo |
| `~/.bash_it` | Bash-it/bash-it | git-repo（`--depth 1`） |
| `~/.tmux/plugins/tpm` | tmux-plugins/tpm | git-repo（`--depth 1`） |
| `~/.vim/colors/iceberg.vim` | cocopon/iceberg.vim | file |

Windows native では rc を配らないため対象外です。Linux / WSL / Raspberry Pi /
macOS では同じです。

## zinit の遅延読み込みの順序

`home/dot_zshrc.tmpl` は重いプラグインを `wait` ice で遅延読み込みし、
`wait'0a'` → `'0b'` → `'0c'` の順に読み込ませます。

- 末尾の文字に使えるのは `a` / `b` / `c` か、何も付けないかだけ。新しい zinit は
  それ以外（`wait'0e'` など）に「`wait ice received invalid suffix letter`」と警告する
- 同じ文字のプラグインは書いた順に読み込まれる。4 段目以降が要るときは文字を
  増やさず、同じ文字の中で並べる（ohmyzsh の `lib/git.zsh` や docker 関連は
  `'0c'` で fzf-tab の後に置いている）

## fzf の関数

`~/.config/shell/fzf.sh` は、fzf がある場合だけ `.bashrc` / `.zshrc` から
読み込まれる入口です。同じ階層の `fzf/` にある次の 3 ファイルを順に読み込みます。

| ファイル | 中身 |
| --- | --- |
| `fzf/core.sh` | `FZF_*` のオプションと、移動・汎用の関数（`xf` / `xg` / `xgw` / `v` / `sshf` / `fgg` など） |
| `fzf/git.sh` | git の関数（`fbr` / `fbrm` / `fshow` / `cdworktree` / `fadd`） |
| `fzf/tools.sh` | mise / Singularity / Homebrew の関数（Homebrew は `fcask` / `funcask`。`install` は `/usr/bin/install` を隠すので使わない） |

各ファイルの関数は、対応するコマンドがある場合だけ定義されます。Windows では
`.chezmoiignore` の `.config/*` によって `fzf/` ごと配られません。

## PowerShellプロファイル

設定の実体は `home/dot_config/powershell/` に置き、`$PROFILE`
（`Documents/PowerShell/` と `Documents/WindowsPowerShell/`）へは
それをdot-sourceするだけのローダーを配置します。

| パス | 役割 |
| --- | --- |
| `home/dot_config/powershell/profile.ps1.tmpl` | PowerShell 7 / 5.1 共通の本体 |
| `home/dot_config/powershell/cache.ps1` | init 出力のキャッシュ（`Get-CachedInitScript`）。本体がトップレベルで dot-source する |
| `home/dot_config/powershell/commands/*.ps1` | 用途別の関数（wsl、docker、fzf、pwgen） |
| `home/Documents/*/profile.ps1.tmpl` | `$PROFILE` から本体を呼ぶローダー |
| `home/.chezmoitemplates/powershell/profile-loader.ps1` | `$PROFILE` ローダーの本文。Documents 配下と `run_after_345` が共有する |
| `home/.chezmoitemplates/powershell/git-config-env.ps1` | プロファイルとScoopスクリプトで共有する `GIT_CONFIG_*` の正規化 |
| `home/.chezmoiscripts/300_windows/run_after_345_powershell_profile.ps1.tmpl` | `Documents` がリダイレクトされている場合のローダー再配置 |

この構成には次の理由があります。

- **実体を `Documents` の外に置く**: OneDriveの既知フォルダーリダイレクトが
  有効だと `$PROFILE` はOneDrive側を指し、`~/Documents` へ配置したファイルが
  読まれません。実体を `~/.config` に置き、ローダーだけを実際の `MyDocuments`
  へ再配置します。
- **パスは `{{ .chezmoi.homeDir }}` で埋め込む**: PowerShellの `$HOME` は
  `HOMEDRIVE`+`HOMEPATH` 由来で、ホームをリダイレクトしたドメイン参加機では
  chezmoiの `~`（`%USERPROFILE%`）と一致しません。
- **PowerShellソースにはUTF-8 BOMを付ける**: Windows PowerShell 5.1はBOMの無い
  `.ps1` をANSIコードページ（ja-JPならCP932）として読みます。日本語コメントの
  行末バイトが改行を飲み込み、**直後のコードがエラーも警告も無く実行されなく
  なります**。`test_powershell_sources_start_with_a_utf8_bom` で強制します。
- **分割したファイルはトップレベルで dot-source する**: 関数の中から dot-source すると
  定義がその関数のスコープに閉じ、セッションから見えなくなります。
  `test_init_cache_is_dot_sourced_at_the_top_level` で固定します。
  `.chezmoitemplates/` 配下は他ファイルへ埋め込むため対象外です。
- **対話時と非対話時を分ける**: `profile.ps1` はAllHostsプロファイルのため、
  エージェントやスクリプトからの起動でも毎回読み込まれます。プロンプト
  （oh-my-posh）、キーバインド、モジュール読み込み、関数（`open` や
  `commands/*.ps1`）は対話時だけ定義・実行します。docker の `dclean` などは
  hookがコマンド名しか見ないため、非対話で定義すると権限規則を素通りします。
  cmdletの既定エンコーディング（`*:Encoding`）は非対話でも `utf8` にします。
  外すと5.1の既定（`Out-File` はUTF-16LE、`Set-Content` はANSI）に戻るためです。
  5.1では `utf8` がBOM付きになりますが、こちらを許容します。
  Consoleのエンコーディングは非対話でも設定し、失敗は無視します。
  判定はstdioのリダイレクトに加え、起動引数（`-Command` / `-File` /
  `-EncodedCommand` / `-NonInteractive`。ただし `-NoExit` があれば対話）も見ます。
- **`copilot` 関数**: 対話ブロックに置き、`common.toml.tmpl` の `[agent_env]` の値を
  未設定のものだけ環境変数へ入れてから本物の `copilot` を起動し、`finally` で入れた分だけ
  消します。PowerShellの環境変数はプロセス全体なので、Copilotの実行中は親の環境も
  変わります。Windowsは空文字の変数を保持できないため、親から空で渡された値は残し、
  シェル内で空を代入した変数は未設定と同じ扱いになります
  （[shell ツールの環境変数](agent-config-generation.md#shell-ツールの環境変数)）。
- **起動経路でcmdletを使わない**: `Microsoft.PowerShell.Management`
  （`Test-Path`、`Join-Path`）、`Microsoft.PowerShell.Utility`
  （`New-Object`、`Set-Alias`）、`Get-Command` のコマンド探索は、初回呼び出しに
  それぞれモジュールの読み込みが乗り、起動が目に見えて遅くなります
  （[計測](../research/shell/powershell-profile-startup.md)）。対話ブロックより前は
  同等の.NET APIで書きます。
  `pbcopy` はエイリアスから関数へ変えたため、`$input` で明示的にパイプライン
  入力を渡します。
- **init出力をキャッシュする**: `mise activate` の外部プロセス起動を避けるため、
  出力を `%LOCALAPPDATA%\PowerShellProfileCache` へ保存し、実行ファイルのパス・
  サイズ・更新時刻が変わったときだけ再生成します。キャッシュは最適化なので、
  読み書きに失敗しても警告に留め、`mise` を直接実行するフォールバックへ回ります。
  一時ファイルは `.ps1` で終わらせます（dot-sourceは `.ps1` 以外を `Application`
  として扱い、実行しません）。
  なお **`oh-my-posh init` はキャッシュしません**。oh-my-posh はテーマ設定を
  セッションIDに紐付けて登録するため、別セッションでIDを採番し直すと設定を
  引けず、既定のpowerlineテーマに戻ります。
- **oh-my-posh のテーマ**: `POSH_THEMES_PATH` の `pure.omp.json` があればそれを、無ければ `~/.config/powershell/themes/pure.omp.json`
  （同梱の複製）を使います。winget の MSIX 版（`ohmyposh.cli`）は `POSH_THEMES_PATH` を設定せず、
  従来はテーマが見つからないまま既定のプロンプトで起動していました（[観測](../research/chezmoi/structure-windows-notes.md)）。
- **PATHを冪等に更新する**: `mise activate` は毎回PATHの先頭へ追加するため、
  追加後に重複を畳みます。
  あわせて未展開の `%VAR%`（例: `%USERPROFILE%\AppData\Local\Microsoft\WindowsApps`）を展開します。
  ssh（`sshd`）経由のセッションは、ユーザー PATH の `%VAR%` を展開せずに渡し、MSIX 版 oh-my-posh の
  エイリアス（`WindowsApps`）が見つからずテーマが出なかった（[観測](../research/chezmoi/structure-windows-notes.md)）。

この構成にしたときの起動時間の計測は
[PowerShell プロファイルの起動時間](../research/shell/powershell-profile-startup.md)
にあります。
