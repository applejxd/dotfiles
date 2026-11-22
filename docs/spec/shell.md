# シェル

シェルの起動ファイルの契約、マシン固有の設定の置き場、zsh の起動時間とプラグイン（zinit・fzf）、PowerShell のプロファイル。全体の構成は [プロジェクト構造](structure.md)。

## シェルの起動契約

シェルの主な利用者は AI エージェントである。エージェントは、シェルを非対話・非 TTY で起動する
（zsh なら `.zshenv` だけが読まれる）。そのため、どのファイルが
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
（出力はしない）。`TMPDIR` が既に `<repo>/.tmp/s/` の配下（pi のセッションの置き場。
CHG-0042）のときは、そのまま維持する（子の zsh が戻さない。試験は
`test_zshenv_tmpdir.py`）。`.tmp` が書き込めない、または自分の所有でない
（他のユーザーが先に作った）ときは、向けずに元の `TMPDIR` を保つ。継承した `TMPDIR` が
`<repo>/.tmp/s/` の配下のときは、親の pi が決めた値として、所有者を見ずに維持する。

`shellenv.sh` は mise の shims（`${MISE_DATA_DIR:-~/.local/share/mise}/shims`）を、
存在するときだけ PATH の先頭へ 1 回置く（継承した PATH に既にあれば先頭へ移す。venv の
`bin` が PATH にあればその直後）。非対話でも cwd の `mise.toml` の版で解決される。
版の再現性が要る操作（lint・ビルドなど）は shim ではなく `mise exec` を使う。
実測は[調査記録](../research/shell/mise-shims-resolution.md)。

WSL では `shellenv.sh` が `wslenv.sh` を読み、Windows 側のディレクトリ（`Windows` /
`System32`、PowerShell 5.1、PowerShell 7（`C:\Program Files\PowerShell\7` があるとき
だけ）、システム全体に入れた VS Code、Java）を PATH の先頭へ足す。ユーザー別に入れた
VS Code の `bin`（ユーザーが書き込める場所）は、Linux 側のコマンドを隠さないよう、
`shellenv.sh` が PATH の最後へ 1 つだけ置く（継承した PATH に先頭のものがあれば、除いてから）。`/etc/wsl.conf` の
`appendWindowsPath=false` で Windows の PATH は引き継がないため、`pwsh.exe` なども
ここで足したものしか名前で呼べない。入れ子のシェルで読み直しても重複しないよう、
PATH と `LD_LIBRARY_PATH`（`/usr/lib/wsl/lib`）は既にあれば足さない。足すための
補助関数は読み終えたら `unset -f` で消す（方針 1）。`DISPLAY` は WSLg か SSH の X11 転送が
決める（`wslenv.sh` は補わない）。VcXsrv を使うときは、`userenv.sh` に `DISPLAY` を自分で書く
（認証なしの TCP の X11 になるので、VcXsrv 側でアクセス制御を有効にする）。

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
   （`archive.sh`: `extract` / `zpack` / `zunpack`、`cpp.sh`: `runcpp`、`pi.sh`: `drypi` / `superpi`。
   `pi.sh` は、外部の `pi`（alias・関数ではない実行ファイル）が PATH にある機だけ定義する）。
   テンプレート機能が要らないので素の `.sh` にし、pre-commit の shellcheck を効かせる。
   読み込み元が `shellrc.sh` だけなので、対話シェル専用であることは変わらない。
   小さい関数は `shellrc.sh` に残す。zsh の `autoload` は bash で使えないので採らない。

Nix 化・`rm` の alias 差し替え・環境変数の列挙による人間判定は採らない（検討した記事との比較は [記録](../research/shell/structure-shell-notes.md)）。

検査は `test/test_shell_startup.py`（非対話 zsh / login bash の alias・環境変数・
出力、`.zshrc` の早期 return、`shellenv.sh` 単体、`functions/` の読み込み、`zpack`、
`runcpp`、`drypi`・`superpi`）。一時 HOME に描画結果を
置いて実行し、zinit・mise・fzf・ネットワークは使わない。実機の対話シェルの
起動（プロンプトまで）は検査しない。

## pi の特殊な起動 drypi と superpi

2026-11-20。外部の `pi`（alias・関数ではない実行ファイル）が PATH にある機だけ、対話シェルに 2 つの関数を定義する（`functions/pi.sh`。bash・zsh。Windows の PowerShell は対象外）。引数は pi へそのまま渡す。

| 名前 | 中身 |
| --- | --- |
| `drypi` | 起動した場所のまま、`pi --no-extensions --no-skills --no-prompt-templates --no-context-files --no-approve` を呼ぶ |
| `superpi` | `drypi` と同じ一覧に `--no-session --offline` を足し、`cd /` したサブシェルから `sudo env HOME=… PATH=… PI_CODING_AGENT_DIR=… pi …` で root として呼ぶ |

- **由来（dry mode）**: 2026-11-19（UTC）の @skirano のツイート（`https://x.com/skirano/status/2123524161192743060`。取得は 2026-11-20）。「サブエージェントのモデルは、モデルの上に載るものを全部切った dry mode で動かすと、速く効率よく動く」。添付の画像は、Codex の `codex exec -m <モデル> -s workspace-write -C <dir> -c 'mcp_servers={}' --disable plugins --disable apps … --disable browser_use … --disable skill_search … -- -`（標準入力から依頼を読む非対話の実行）。ツイートの主張（速く効率的になる）は未検証。
- **Codex から pi への対応**:

  | Codex | pi |
  | --- | --- |
  | `-c 'mcp_servers={}'`・`--disable plugins`・`apps`・`browser_use`・`computer_use`・`image_generation` など | `--no-extensions`（組み込みの MCP・`tool_search`・`codemode`、設定した package 由来の拡張も切る。`--no-mcp` はこれに含まれるので足さない） |
  | `--disable skill_search`・`skill_mcp_dependency_install` | `--no-skills` |
  | （対応なし） | `--no-prompt-templates`・`--no-context-files`（`AGENTS.md`・`CLAUDE.md`）・`--no-approve`（信頼の対象になる、プロジェクトの `.pi/` の設定・拡張・MCP を無視する。ただし、起動時の `sessionDir` の先読みは残る。出典は pi 1.5.2 同梱の `docs/security.md`） |
  | `-C <dir>` | 付けない（起動した場所のまま。利用者の指定） |
  | `-m <モデル>` | 付けない（既定のモデル。`drypi --model …` で指定できる） |
  | `-s workspace-write`（囲い） | 付けない（利用者の判断。下の注意） |
  | `exec … -- -`（非対話・標準入力） | 対話が既定。`drypi -p "依頼"` や、標準入力を渡す `drypi -p` で非対話にできる |

  残るもの: pi の既定のシステムプロンプト、ユーザー設定（`settings.json`。既定のモデル・`defaultTools`・テーマなど）、agent ディレクトリの `SYSTEM.md`・`APPEND_SYSTEM.md`（あれば。この機には無い）、組み込みの道具（read・bash・edit・write。設定の `defaultTools` で足した grep・find・ls は残るはずだが、未確認）。明示した `-e`・`--skill`・`--prompt-template` は、停止のフラグがあっても読み込まれる。
- **注意（権限の方針も囲いも効かない）**: 拡張を切るので、権限の拡張（`pi-permission-system`）の deny・ask が効かない（`.env` や鍵のパス・危険なコマンドの拒否も無い）。囲い（`pib`）も通さない（2026-11-20 の利用者の判断。`pib` 経由にする案もあったが、素の `pi` を選んだ）。囲いが要るときは `pib --no-extensions …` を直接使う。
- **`superpi` の注意**: root で、権限の方針も囲いも無く動く。
  - `cd /` はサブシェルの中だけで、呼んだシェルの作業ディレクトリは変わらない。
  - `HOME` と `PI_CODING_AGENT_DIR`（設定済みならそれ、無ければ `~/.pi/agent`）は、利用者のものを渡す（認証・設定を共有するため）。**root が `~/.pi/agent` に root 所有のファイルを作ると、あとで通常の pi が書けなくなる**。そのため、セッションを保存せず（`--no-session`）、起動時の自動の通信もしない（`--offline`）。認証の更新などで、root 所有のファイルが残りうる。直すには `sudo chown -R "$USER" ~/.pi/agent`。
  - sudo が落とす環境変数（プロキシ・`AWS_PROFILE` など）は渡さない。渡すのは `HOME`・`PATH`・`PI_CODING_AGENT_DIR` だけ（`TERM` は sudo が保つ）。必要なら `functions/pi.sh` の `env` に足す。
  - `PATH` を丸ごと root へ渡す（利用者の例と同じ。sudo の `secure_path` は使わない）。利用者が書き込める場所の実行ファイルを、root が実行しうる。**これは利用者の判断で変えない**（2026-11-22。`superpi` はシステム全体の更新・不具合対応を制限なしで行う用途で、固定の PATH にすると mise の node を使う pi が起動しない。この機で、固定の PATH では `node`・`rg`・`fd`・`uv` が見つからないことを確かめた）。
  - pi の実体は、外部の実行ファイルの絶対パス（bash は `type -P pi`、zsh は `whence -p pi`）。相対の `PATH` 要素で見つかったときは、`cd /` する前の作業ディレクトリで絶対にする。alias・関数の `pi` は使わない。`$HOME/.local/bin/pi` に固定しない（この機には無く、`~/.pi/agent/bin/pi` と `~/bin/pi` がある）。
  - sudo が無ければ `superpi: sudo が無い`、読み込んだあとで PATH から pi が消えたら `superpi: pi の実行ファイルが PATH に無い` と出して、sudo の前に失敗する。
- **ADR-0037 との関係**: 撤去したのは、pi 以外の CLI の起動関数と `agent` の別名。pi を起動する別名は対象外（`test_shellrc_defines_no_agent_alias_or_copilot_function` は、そのまま通る）。
- **既存の評価（ADR-0031）**: pi の標準のフラグだけで足りる。自作は関数 2 つ（約 20 行）で、拡張・package は足さない。pi 1.5.2 の `pi --help` と docs に、一括で切る profile のようなフラグは無い（2026-11-20 に確認）。あれば置き換える。
- **変え方**: 切る範囲は `_PI_DRY_ARGS`（`drypi` も `superpi` も共有）。試験は `test/test_shell_startup.py`（偽の `pi`・`sudo` を PATH に置いて、渡す引数・作業ディレクトリ・環境変数を、bash と zsh で確かめる。偽の sudo は環境を捨てるので、`HOME`・`PATH`・エージェントの置き場を明示して渡さないと、pi に届かない）。**未検証**: 実機の `sudo` と、実際の pi の起動（`--no-extensions` で、設定の package・権限の拡張・MCP が本当に読まれないこと）。

## マシン固有の設定の置き場

マシンごとに違う値（データセットの置き場、プロキシなど）は、リポジトリに書かず次のどれかへ置く。

| 置き場 | 何を置くか | いつ読まれるか | 注意 |
| --- | --- | --- | --- |
| `~/.config/shell/userenv.sh`・`.bash`・`.zsh` | 環境変数・プロキシ。例: `export http_proxy=http://address:port` | シェルの起動ごと（`userenv.sh` は `shellenv.sh` が読む） | chezmoi の管理外。同じ場所の `.example` から作る |
| `~/.config/mise/conf.d/*.toml` | `mise` の設定のマシン固有分 | `mise` が設定を読むとき | chezmoi の管理外。`[env]` は mise を有効化したシェルでしか効かない（**推測**。公式 docs では未確認） |
| `~/.config/chezmoi/chezmoi.toml` の `[data]` | chezmoi のテンプレートに渡すマシン固有の値（例: `no_proxy`） | `chezmoi apply` のとき | chezmoi の管理外。値の使い道はテンプレートが決める。`http_proxy`・`https_proxy` は写さない（認証情報を平文で残さないため）。以前の `init` で残った値は `chezmoi init`（または `chezmoi update --init`）で描き直すと消える |
| `~/.config/git/config.local` | git の設定のマシン固有分 | git が設定を読むとき | chezmoi の管理外。`home/dot_config/git/config.tmpl` が、共有設定の後ろに `[include]` で読む（**共有設定を上書きもできる**） |
| `~/.config/pi-sandbox/runner.local.toml` | pi の囲い（`pib`）で、隠す場所の追記 | `pib` の囲いでコマンドを実行するたび | chezmoi の管理外。追記のみで、`[gpu]`・`[docker]`・`[git]` は書けない。同じ場所の `runner.local.toml.example` から作る（[設定](sandbox/pi-sandbox-runner.md#設定runnertoml)）。Linux / WSL のみ |
| `~/.pi/agent/extensions/permission-explain/config.local.json` | pi の説明（`Ctrl+E`）に使うモデルの上書き（`model` だけ。`key` は書いても無視される）。同じ場所の `config.local.json.example` から作る | 拡張の起動時（`/reload` か pi の再起動） | chezmoi の管理外。リポジトリの `config.json`（`is-work` でモデルを切り替える）に重ねて読む。詳細は [ローカル版の記録](../research/agents/ask-auto-judge-evaluation-2026-11.md#ローカル版への切り替え2026-11-15) |
| pi の確認（YOLO など） | `/permission-system` で切り替える | すぐ | 機械ごとの設定で、`chezmoi apply` では戻らない（[YOLO mode](agent-config-generation.md#permission-system-の設定)） |

**共通の約束**（共有の設定とマシン固有の設定を分ける）:

- 共有の設定（リポジトリ。chezmoi が管理し、`apply` で上書きされる）とは別に、マシン固有のファイルは **chezmoi の管理外**に置く。`chezmoi apply` で消えず、`chezmoi diff` にも出ない。
- chezmoi が管理するファイル（`~/.pi/agent/settings.json`・`~/.claude/CLAUDE.md` など）は直接編集しない。`apply` で作り直される。
  `~/.claude/settings.json` は、`permissions.deny` と `permissions.ask` だけを chezmoi が置き換える（ほかのキーは保つ。[Claude Code の設定](claude-code.md)）。

**sandbox の許可を足すファイル**（`agents/local.toml` の `[sandbox]`・`runner.local.toml`）は、さらに次を守る。

- **追記のみ**。共有のエントリを消したり、緩めたりしない（`[sandbox]` は緩めるキーを無視し、`runner.local.toml` は緩める指定があると起動しない）。
- 利用者の階層（`~/.config/…`）に置く。エージェントが書き換えられる作業ツリーの中には置かない。

git の `config.local` のように、共有設定を上書きできるものもある。

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
  権限の規則がコマンド名しか見ないため、非対話で定義すると権限規則を素通りします。
  cmdletの既定エンコーディング（`*:Encoding`）は非対話でも `utf8` にします。
  外すと5.1の既定（`Out-File` はUTF-16LE、`Set-Content` はANSI）に戻るためです。
  5.1では `utf8` がBOM付きになりますが、こちらを許容します。
  Consoleのエンコーディングは非対話でも設定し、失敗は無視します。
  判定はstdioのリダイレクトに加え、起動引数（`-Command` / `-File` /
  `-EncodedCommand` / `-NonInteractive`。ただし `-NoExit` があれば対話）も見ます。
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
