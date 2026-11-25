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
| `~/.local/bin/pi-t3` | T3 Code が pi を起動するとき（login シェルを通らない非対話の bash。Linux / WSL のみ） | `shellenv.sh` を読むだけ。[詳細](#t3-code-から起動する-pi-の入口-pi-t3) |

`.zshenv` には環境変数のほかに例外が 1 つある。リポジトリ内にいる間 `TMPDIR` を
そのリポジトリの `.tmp` に向けるため、関数を 1 つ定義して `mkdir -p` を実行する
（出力はしない）。`TMPDIR` が既に `<repo>/.tmp/s/` の配下（pi のセッションの置き場。
CHG-0042）のときは、そのまま維持する（子の zsh が戻さない。試験は
`test_zshenv_tmpdir.py`）。`.tmp` が書き込めない、または自分の所有でない
（他のユーザーが先に作った）ときは、向けずに元の `TMPDIR` を保つ。 Windows の PowerShell は、`TEMP` / `TMP` で同じことをする（[リポジトリごとの TEMP](#仕組みと制約)）。継承した `TMPDIR` が
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
`runcpp`、`drypi`・`superpi`、`pi-t3`）。一時 HOME に描画結果を
置いて実行し、zinit・mise・fzf・ネットワークは使わない。実機の対話シェルの
起動（プロンプトまで）は検査しない。

## pi の特殊な起動 drypi と superpi

2026-11-20。外部の `pi`（alias・関数ではない実行ファイル）が PATH にある機だけ、対話シェルに 2 つの関数を定義する（`functions/pi.sh`。bash・zsh。Windows の PowerShell にも同名の関数がある: [対応表](#bashzsh-と-powershell-の対応)。`superpi` は Windows の `sudo`）。引数は pi へそのまま渡す。

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

## T3 Code から起動する pi の入口 pi-t3

2026-11-22。T3 Code（WSL 内のサーバ）が起動する pi には、`userenv.sh` の変数（`HF_HOME` など）が届かない。そのため `~/.local/bin/pi-t3`（Linux / WSL のみ。`home/dot_local/bin/executable_pi-t3`）を足した。`shellenv.sh`（`wslenv.sh`・`userenv.sh` を含む）を読んでから `exec pi "$@"` するだけの bash の wrapper で、決めた理由と選ばなかった案は [ADR-0042](../adr/0042-t3-code-pi-wrapper-reads-shellenv.md)。

- **原因**（t3code 側の調べ。この repo では未確認）: Windows のデスクトップは `wsl.exe --exec env PATH=… <t3> --bootstrap-fd 0` で WSL のサーバを起動し、login シェルを通らない。サーバが起動時に 1 回だけ `$SHELL -ilc` から取り込むのは `PATH`・`__MISE_DIFF`・`JAVA_HOME` だけ。Pi の起動・状態確認・text generation は、binary path（既定は `pi`）をシェルを介さず直接起動する。上の契約表のどの入口も通らないので、`shellenv.sh` が作る環境（`LC_ALL`・`LD_LIBRARY_PATH`・条件つきの `AWS_REGION`・`userenv.sh` の変数）が pi に届かない。
  出典（2026-11-22 取得）: [pingdotgg/t3code#16703](https://github.com/pingdotgg/t3code/issues/16703)（Open。WSL のサーバに、シェルのプロファイルで export した `NODE_EXTRA_CA_CERTS` が届かない、という報告。同じ原因）、[#12494](https://github.com/pingdotgg/t3code/pull/12494)（Closed。login シェルの全環境を取り込む案）。メンテナの見解と、直った版は未確認。
- **中身**: `#!/bin/bash -p`。`[ -r shellenv.sh ] && . shellenv.sh >&2 </dev/null` のあと `exec pi "$@"`。
  - stdout・stdin は pi との RPC なので、読み込みの出力（`userenv.sh` が出すものを含む）は stderr へ回し、stdin は読み込みに渡さない（`userenv.sh` が stdin を読んでも、pi 向けの入力を消費しない）。
  - `-p` で、継承した `BASH_ENV`（読まれると stdout へ出しうる）と `SHELLOPTS`（`errexit` など）を無視する（`pib-shell` と同じ。サンドボックスのためではなく、stdout の契約を守るため）。
  - `HOME` が空・相対のときは、`shellenv.sh` を読まない。
  - `set -e` は付けない（`userenv.sh` が非 0 を返しても、そこまでの変数で pi を起動する）。
  - `shellenv.sh` が無い機でも、何も足さずに pi を起動する。pi が PATH に無ければ、stdout に何も出さず 127 で終わる。
  - `pi` は、読み込み後の PATH で探す（`~/bin/pi`。mise の shim に `pi` は無い）。
- **設定（利用者が行う。この repo は配るだけ）**: T3 の Pi インスタンスの binary path に、絶対パス（`$HOME/.local/bin/pi-t3` を展開したもの）を指定する。T3 の起動環境で `~/.local/bin` が PATH に入る保証は無い（この repo では `.profile` が足すが、zsh と、`.bash_profile` がある bash は読まない）ので、名前でなく絶対パスにする。戻すときは空にする。複数の機へ配るときは、T3 の managed policy の `providers.instances.pi.binaryPath`（`locked: false`。root 権限が要る。`t3 policy check` で確認）でも配れる（t3code 側の調べ。任意。この repo では未検証）。
- **実測**（2026-11-22。この機は WSL2。`shellenv.sh` は `chezmoi verify` で source と一致）:

  | 項目 | 結果 |
  | --- | --- |
  | 出力 | `env -i … bash -c '. shellenv.sh'`（非対話・stdin なし）で stdout・stderr とも 0 B。`set -eu` 下でも同じ |
  | 所要時間 | `shellenv.sh` の読み込みは約 5 ms（`bash -c true` は 2 ms）。wrapper 全体は 6〜9 ms |
  | 冷えた経路 | `~/.cache/win_user` が無く、システム全体の VS Code も無い機だけ、`wslenv.sh` が `cmd.exe` を 1 回呼び、結果が非空ならキャッシュを書く。77〜97 ms（偽の HOME で再現） |
  | 増える変数 | `BROWSER`・`DefaultIMModule`・`EDITOR`・`GHQ_ROOT`・`GTK_IM_MODULE`・`HF_HOME`・`INFOPATH`・`LANG`・`LC_ALL`・`LD_LIBRARY_PATH`・`LIBGL_ALWAYS_INDIRECT`・`MANPATH`・`PATH`・`QT_IM_MODULE`・`VISUAL`・`XAUTHORITY`・`XMODIFIERS`。トークン・鍵・パスワードに見える名前は無い。`userenv.sh` が足すのは `HF_HOME` だけ |
  | PATH | T3 が取り込み済みの PATH に対して、新しい要素は 0。重複が 4 要素（texlive・`/usr/local/cuda/bin`・`~/bin`・`/snap/bin`）と、mise の shims が先頭へ移る |

- **限界・未確認**:
  - **bash では `shellenv.sh` は冪等でない**（snap・`~/bin`・CUDA・go・cabal・texlive は読むたびに足される。zsh は `.zshenv` の `typeset -U path` で PATH だけ畳まれる）。pi の起動のたびにサーバの環境から作り直すので、累積はせず、実害は軽微。wrapper には重複の除去を足さない。恒久策は、別件として `shellenv.sh` 側を冪等にすること。
  - **T3 のインスタンス環境変数との優先順位**（推論。実機では未確認）: T3 は、起動環境にインスタンス環境変数を上書きで合成し、その後で wrapper が `shellenv.sh` を読む。無条件に export する名前（`XAUTHORITY`・IME 系・`GHQ_ROOT`・`BROWSER`・`LIBGL_ALWAYS_INDIRECT`、条件を満たせば `JAVA_HOME`・`CLASSPATH`）は wrapper 側が勝ち、`${VAR:-既定}` の名前（`LC_ALL`・`LANG`・`EDITOR`・`VISUAL`。方針 4）は、すでに値があるインスタンス側が勝つ（ただし `userenv.sh` が同じ名前を再代入すると、最後に読まれる `userenv.sh` の値が、どちらにも勝つ）。同じ名前を両方に書く前に、実機で確かめる。
  - **範囲は Pi だけ**。T3 経由で Claude Code や Codex を使うときは、同様の wrapper が別に要る（今回は対象外）。
  - **T3 が wrapper を実際にどう起動するか**（`--version` の stdout の扱いなど）は未確認。次の「T3 での確認」で確かめる。
  - **信頼するもの**: wrapper は、T3 が pi を起動するたびに `~/.config/shell/{shellenv,wslenv,userenv}.sh` を実行し、読み込み後の PATH（`~/bin`・mise の shims が先頭側）で `pi` を探す。対話シェルや agent のシェルがすでに読むファイルだが、T3 の起動の経路にも、同じ信頼が及ぶ。これらは pi の `path_write` の deny に無い（既存の穴。別件）。wrapper 自身は `~/.local/bin`（deny 済み）にある。
- **T3 での確認**（利用者が行う）: Pi の状態確認（バージョン検出）が通る。1 ターン実行できる。pi に `HF_HOME` と `LC_ALL` を出力させる。text generation が通る。
- **検査**: `test/test_shell_startup.py` の `test_pi_t3_*`（偽の pi で、exec・引数と終了コードの素通し・stdout が pi のものだけ・`HF_HOME`/`LC_ALL`・出力の stderr への退避・stdin を渡さない・継承した `BASH_ENV`/`SHELLOPTS` の無視・`userenv.sh` が非 0 でも起動・`shellenv.sh` 無し・空/相対の `HOME`・読み込み後の PATH で pi を探す・pi が PATH に無いとき 127。WSL の機で `cmd.exe` を呼ばないよう、Windows のユーザー名のキャッシュを先に置く）、`test/test_chezmoi_templates.py` の `test_pi_t3_is_linux_only`。実際の T3 からの起動は検査しない。

## マシン固有の設定の置き場

マシンごとに違う値（データセットの置き場、プロキシなど）は、リポジトリに書かず次のどれかへ置く。

| 置き場 | 何を置くか | いつ読まれるか | 注意 |
| --- | --- | --- | --- |
| `~/.config/shell/userenv.sh`・`.bash`・`.zsh` | 環境変数・プロキシ。例: `export http_proxy=http://address:port` | シェルの起動ごと（`userenv.sh` は `shellenv.sh` が読む。T3 Code から起動する pi は `pi-t3` が読む） | chezmoi の管理外。同じ場所の `.example` から作る |
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

Windows native では rc を配らないため、`iceberg.vim` 以外は対象外です。`~/.vimrc` は Windows にも
配り、`colorscheme iceberg` が読むので、`iceberg.vim` だけは Windows でも取得します（Git for Windows の vim は
`~/.vim/colors`、ネイティブ版の vim は `~/vimfiles` を見るため、`.vimrc` が `runtimepath` へ `~/.vim` を足します）。
Linux / WSL / Raspberry Pi / macOS では、表の 5 項目すべてを取得します。

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

## bash/zsh と PowerShell の対応

2026-11-25。Ubuntu（bash / zsh）にあって Windows の PowerShell に無かった機能のうち、PowerShell の標準の仕組みで自然に再現できるものを足した。
Linux 側の定義（`shellrc.sh`・`fzf/*.sh`・`functions/*.sh`・`.zshrc.d/`・`.zshenv`・zeno）は変えない。調査と実測は [記録](../research/shell/powershell-linux-parity-2026-11.md)。

### 対応表

| bash / zsh | PowerShell | 置き場・仕組み |
| --- | --- | --- |
| `up` / `upp` / `uppp`・`jcd`・`cleanup`・`sha1`・`wcc`・`fcr`・`search`・`y`（yazi） | 同名の関数 | モジュール `ShellShortcuts`。`search` は `find \| grep -n` の代わりに `Select-String`（`パス:行:内容`） |
| `ll` / `la` / `lla` / `lal` / `lt` / `ltl`（`ls=eza`） | 同名の関数。eza があれば eza、無ければ `Get-ChildItem` と、`.git` などを除く簡易の木 | `ShellShortcuts`。標準の `ls`（`Get-ChildItem`）は、パイプラインへオブジェクトを流すので上書きしない |
| `alias cat='bat --paging=never -p'` | `cat`。bat があり、オプション・パイプラインの入力が無いときだけ bat。それ以外は `Get-Content` | `interactive.ps1` が標準のエイリアスを外し、`ShellShortcuts` の `Invoke-ShellCat` を呼ぶ関数を定義 |
| `dirs -v` | `dirs`（`Get-Location -Stack`） | `interactive.ps1`（場所のスタックは SessionState ごとなので、モジュールに置けない） |
| `v`・`shellf`・`mise-select` | 同名の関数（`v` は `~/.viminfo` か `~/_viminfo`。`shellf` は入っているシェルから選ぶ） | `ShellShortcuts` |
| `fbr` / `fbrm` / `fshow` / `cdworktree` / `fadd` / `xgw` / `gwcode` | 同名の関数 | モジュール `ShellGit`。`fshow` は Enter で内容を見て、閉じると一覧へ戻る（Esc で終わる）。`fadd` は Ctrl-D で差分 |
| `extract` / `zpack` / `zunpack` | 同名の関数。GNU tar（Git for Windows）と bsdtar（Windows 標準）の両方で動く | `ShellArchive`。zstd は scoop。パイプを使わず tar に圧縮を任せる |
| `runcpp` | 同名の関数（フラグ・環境変数 `RUNCPP_*` は同じ） | `ShellCpp`。差は下の「差が出るもの」 |
| `drypi` / `superpi` | 同名の関数。`superpi` は Windows の `sudo` で、ドライブの根から起動 | `ShellPi`（[詳細](#pi-の特殊な起動-drypi-と-superpi)） |
| `pk` | `pk`（Python の `~/.local/bin/pk` を python で呼び、`sh` は Git for Windows のものを使う） | `ShellPk`。`pk` は `interactive.ps1` が定義する薄い関数 |
| `code-exam`・`audio-dl`・`video-dl`（個人 PC） | 同名の関数 | モジュール `PersonalShell`（個人 PC だけに配る） |
| `setopt auto_cd` / `shopt -s autocd`・`cdpath=(.. ~)` | ディレクトリ名だけの入力で cd（カレント → 親 → `~` の順。`..`・`...`・`~`・`./x` も） | `CommandNotFoundAction`（`interactive.ps1`）。**入力された**コマンド（`CommandOrigin` が Runspace）の、**引数なしの 1 語**だけ（`build --help` は移動せず、通常のコマンドの未検出のエラー）。関数・スクリプトの中と、ファイルシステム以外の場所は何もしない |
| `chpwd()`（cd のたびに `ls`） | cd のたびに一覧（eza の格子、無ければ名前の格子）。標準出力が端末のときだけ | `LocationChangedAction`（PowerShell 6 以降） |
| `HISTSIZE`・`hist_ignore_space`・`hist_ignore_all_dups` | `-MaximumHistoryCount 100000`・先頭が空白の行は残さない・重複なし | PSReadLine（`interactive.ps1`）。秘密らしい語を含む行は、既定どおりメモリだけ |
| zsh-autosuggestions | 履歴からの候補を入力の右に薄く出す（右矢印・Ctrl+f・End で確定） | PSReadLine 2.1 以降（PowerShell 7）。5.1 は飛ばす |
| fast-syntax-highlighting | PSReadLine の色づけ | 標準 |
| fzf-tab・fzf の Alt+C | Tab の候補を fzf で絞る。Alt+C は fzf で cd（割り当てだけ確認。実際の選択画面は未確認） | PSFzf。**初めて押したときに** PSFzf を読み込む（`commands/fzf.ps1`）。Tab は、候補が 1 つならそのまま入り、複数なら fzf（確認済み） |
| zeno の snippet（`gs,` + Space） | 同じ定義で、Space で展開。`{{名前}}` は最初のものを消してカーソルを置く。`evaluate: true` は実行した出力で置き換える。Ctrl+x, Ctrl+s で fzf から選ぶ | `snippets.json`（zeno の YAML から chezmoi が生成）と `ShellSnippets` |
| compinit・zsh-completions・`_mise`・docker の補完 | gh・chezmoi・docker・mise・uv・uvx・rg・fd・herdr は各ツールの PowerShell 用の補完、git は posh-git、winget は公式、ssh/scp/sftp は `~/.ssh/config` の Host | `interactive.ps1` のスタブ。**初めて Tab を押したときに**生成してキャッシュする |
| `LESS`・`FZF_*`（`rg --files`・bat / eza のプレビュー） | 同じ値（fzf は cmd.exe で実行するので、道具が無いときは `\|\|` で標準のコマンドへ落ちる） | `interactive.ps1` |
| `.zshenv` の `TMPDIR`（リポジトリの `.tmp`） | `TEMP` / `TMP` | `profile.ps1.tmpl` の `Update-RepoLocalTemp`（非対話でも効く。下の「リポジトリごとの TEMP」） |

### 仕組みと制約

- **起動時間**: `.ps1` を 1 つ dot-source するたびに約 16〜20 ms かかる（実測。原因は未調査。既存の小さい `commands/*.ps1` でも同じだった）。関数は `commands/` ではなく、`home/dot_config/powershell/modules/<名前>/` の小さなモジュールにして、`interactive.ps1` が `PSModulePath` へ足す。**関数を初めて呼んだときに** PowerShell が自動で `Import-Module` する（manifest の `FunctionsToExport` が一覧。ワイルドカードにしない）。起動で読むのは `commands/interactive.ps1` の 1 ファイルだけ。この構成での、プロンプトまでの時間の増加は、基準（1255〜1282 ms）に対して約 +25〜60 ms（中央値 約 +40 ms。[内訳と測り方](../research/shell/powershell-linux-parity-2026-11.md#起動時間の内訳)）。Management / Utility モジュールの読み込みを伴う cmdlet（`Test-Path`・`Remove-Item` など）と `GetNewClosure()` は、`interactive.ps1` の最上位では使わない（`$ExecutionContext.InvokeProvider` などを直接呼ぶ）。
- **外部の実行ファイルが先に解決される**: 自動読み込みは、PATH の実行ファイルより**後**に解決される。`cat`（Git・gow の `cat.exe`）と `pk`（`~/.local/bin/pk` という拡張子の無いファイル）は負けるので、`interactive.ps1` が薄い関数（`cat` / `pk`）を定義して、モジュールの関数（`Invoke-ShellCat` / `Invoke-ShellPk`）を呼ぶ。同じ名前の実行ファイルが PATH に入ると、他の関数も隠れうる（見つけたら同じ形にする）。
- **外部コマンドの有無**は、`Get-Command`（初回に 0.25 秒前後。[既存の計測](#powershellプロファイル)。見つからないコマンドは PATH 全体を走査する）ではなく、`Find-Executable`（.NET で PATH を探す）で調べる。起動時には調べず、使う時点で決める。
- **場所のスタック**（`Push-Location`）はモジュールごとの SessionState なので、`dirs` はグローバルの関数にする。
- **補完のスタブ**: ツールの補完スクリプトは大きい（uv は 750 KB）ので、起動では登録だけ（`Register-ArgumentCompleter -Native`）。初めて Tab を押したときに、`Get-CachedInitScript`（[cache.ps1](#powershellプロファイル)）で生成・キャッシュ（`%LOCALAPPDATA%\PowerShellProfileCache\completion-<名前>.ps1`。実行ファイルが変わるまで再生成しない）し、スクリプトの `Register-ArgumentCompleter` を**横取り**して、そのスクリプトブロックを呼ぶ。本物の登録でスタブを置き換える方式は、cobra 製（gh・chezmoi）で効かなかった。cobra の補助の `function`・`filter` はグローバルへ定義し直す。補完の登録を含まない出力（使い方の表示）はキャッシュしない。
- **snippet**: `home/dot_config/powershell/snippets.json.tmpl` が、zeno の YAML（`home/dot_config/zeno/*.yml`）のうち Windows で通じるもの（`01_git`・`02_docker`・`05_gh`・`10_cpp` と、`00_config` の `null,`（`*> $null` へ書き換え）・`b,`・`kgen,`・`pgen,`・`sha2,`）を `include | fromYaml | toJson` で JSON にする。YAML を二重に持たない。Space のハンドラは、左の語が `,` で終わるときだけモジュールを読む（ふつうの空白でモジュールを読み込まない）。Enter での展開は、oh-my-posh が Enter のハンドラを持つので足さない。
- **リポジトリごとの TEMP**: `Update-RepoLocalTemp` が、git のリポジトリ（`.git` がディレクトリでもファイルでも）の中にいる間、`TEMP` / `TMP` を `<repo>\.tmp` へ向ける。外では、最初に読まれた時点の値へ戻す。`TEMP` と `TMP` は、別の値でも別々に控える（`_TMPDIR_REPO_LOCAL_ORIG` が `TEMP`、`_TMPDIR_REPO_LOCAL_ORIG_TMP` が `TMP`。未設定は `<unset>`）。`TEMP` が `<repo>\.tmp\s\`（pi のセッションの置き場）の配下なら維持する。次のときは向けず、元の値を保つ: `.tmp` が作れない・ディレクトリでない（ファイルがある）、`.tmp` が再解析ポイント（ジャンクションなど。行き先がリポジトリの外かもしれない）、リポジトリが UNC（`\\wsl.localhost\…` など）。cd への追従は `LocationChangedAction`（PowerShell 6 以降。5.1 は起動時だけ）。別の拡張が登録済みのハンドラは残して呼び、プロファイルや `interactive.ps1` の再読み込みでは、自分の古いハンドラを置き換える（登録したデリゲートを読み戻して見分ける）。**書き込みの試しはしない**（ファイルの作成はウイルス対策の走査で起動が遅れる。Linux の `-w` / `-O` の確認の代わりに、作れるかだけを見る）。Windows の所有者の確認はしない。mise の cache は、Windows では既定で `%TEMP%` の下の `mise` ディレクトリなので、TEMP を向けるとリポジトリごとに冷える（`<repo>/.tmp/mise` が増える）。そのため `MISE_CACHE_DIR` が未指定なら、向ける前の TEMP の `mise` に固定する（利用者の指定を優先）。
- **クロスプラットフォームの Python**: `home/dot_local/bin/executable_pk` は、Windows では `os.execvp` が子の終了を待たずに親が終わる（終了コードも失う）ので、`subprocess.call` で待つ。

### 差が出るもの

- **`runcpp`**: MinGW（scoop の `mingw-winlibs`）は AddressSanitizer / UBSan を持たないので、debug は警告と STL のデバッグモード（`-D_GLIBCXX_DEBUG`）だけ。sanitizer が使えるコンパイラなら足す（初回にコンパイルを 1 回試して覚える）。`ulimit -s` の代わりに、リンク時に `-Wl,--stack,1073741824`。標準入力は `<` が無いので、パイプで渡す（`Get-Content in.txt | runcpp a.cpp`）。キャッシュは `%LOCALAPPDATA%\runcpp`。
- **`extract`**: `.bz2` は `bzip2 -dk`（Linux の `-dc` は標準出力へ出すだけだった）。`.zip` は `unzip`（Git for Windows）、無ければ `Expand-Archive`。`.lzh` / `.arj` / `.7z` / `.rar` は `7z`。
- **`superpi`**: Windows には root が無いので、`sudo`（Windows 11 24H2 以降の組み込み）で昇格する。昇格しても同じユーザーなので `HOME` の受け渡しは要らない。`sudo` の既定は新しいウィンドウで起動する（`sudo config` で変える）。**この機では sudo を実行していない（実機の昇格は未検証）。**
- **fzf**: `FZF_DEFAULT_OPTS` は `--reverse --border` のまま（Linux の `--height 60%` は、Windows の fzf では未確認なので入れていない。[wiki](https://github.com/junegunn/fzf/wiki/Windows)）。

### 再現していないもの

| 機能 | 理由 |
| --- | --- |
| `fgg`・Ctrl+z（`fancy-ctrl-z`） | PowerShell に、ジョブの中断・再開（`fg`）が無い |
| 拡張子による suffix alias（`alias -s`） | 拡張子での起動は Windows の関連付けに委ねる。`extract` と `runcpp` は関数で呼べる |
| `auto_pushd`・`pushd_ignore_dups` | `cd` の意味を変える。標準の `cd -` / `cd +`（場所の履歴）で足りる |
| `share_history`・`hist_reduce_blanks` | PSReadLine は他のセッションの履歴を即時には取り込まない。空白の圧縮は無い |
| `diff=colordiff -u`・`hub alias` | `diff` は `Compare-Object` のエイリアス。colordiff・hub は Windows に無い |
| `EDITOR` / `VISUAL` | Git for Windows が、自前の vim を既定のエディタにする（`vim` 関数も同じ実体を呼ぶ） |
| zeno の補完（`kill`・`docker stop` の fzf 補完など） | 各ツールの補完スクリプト（docker・gh など）と PSFzf の Tab で足りる。シェルのパイプに依存した定義は移せない |
| zeno の snippet のうち ros2・tmux、`find,`・`grep,`・`relogin,` | Windows に無い道具・Unix のコマンド |
| ROS・Modules・iTerm2・NAS・bash-it・Cline の shell integration | Linux / macOS 専用。VS Code の統合は pwsh では自動で入る |
| singularity・Homebrew・`unmount` の fzf 関数 | Linux / macOS 専用 |

### 検査

- `test/test_windows_assets.py`: モジュールの manifest と実体の一致、起動で読むファイルが 1 つ、`Get-Command` を起動で呼ばない、`Update-RepoLocalTemp` の位置と形、snippet の生成元、道具の宣言（mise・scoop・PSGallery）、個人用モジュールを他の機へ配らない、`pk` の Windows 分岐。
- `test/test_powershell_functions.py`（新規）: 各関数を、本物と同じ経路（`interactive.ps1` を読み、モジュールを自動読み込み）で実行する。外部の道具（fzf・gwq・pi・sudo・bat・eza）は PATH の先頭に置く偽物で、渡した引数・標準入力・終了コードを確かめる。tar は GNU と bsd の両方。補完のスタブ、`TEMP`、auto_cd（入力された場合と、スクリプトからの場合）。
- `test/test_powershell_interactive.py`: 実際の対話セッション（ConPTY）で、snippet の展開（`gs,` と `gcim,` に Space）・auto_cd + chpwd・Tab・キー割り当て・履歴・`TEMP`、5.1 では 7 専用の機能を飛ばして起動エラーが無いこと。配備前は、描画した profile を `PWSH_TEST_PROFILE` で渡して試せる。

## PowerShellプロファイル

設定の実体は `home/dot_config/powershell/` に置き、`$PROFILE`
（`Documents/PowerShell/` と `Documents/WindowsPowerShell/`）へは
それをdot-sourceするだけのローダーを配置します。

| パス | 役割 |
| --- | --- |
| `home/dot_config/powershell/profile.ps1.tmpl` | PowerShell 7 / 5.1 共通の本体 |
| `home/dot_config/powershell/cache.ps1` | init 出力のキャッシュ（`Get-CachedInitScript`）。本体がトップレベルで dot-source する |
| `home/dot_config/powershell/commands/*.ps1` | 用途別の関数（wsl、docker、fzf、pwgen、chocolatey）。fzf と chocolatey は、遅いモジュールを使うときまで読み込まない仮の定義も持つ |
| `home/dot_config/powershell/commands/interactive.ps1` | 対話だけで読む 1 ファイル。環境変数・履歴・auto_cd・chpwd・snippet のキー・補完のスタブ・`cat` / `pk` / `dirs`・`PSModulePath` への `modules/` の追加（[対応表](#bashzsh-と-powershell-の対応)） |
| `home/dot_config/powershell/modules/<名前>/` | bash / zsh の関数に相当する小さなモジュール（`ShellShortcuts`・`ShellGit`・`ShellArchive`・`ShellCpp`・`ShellPi`・`ShellPk`・`ShellSnippets`、個人 PC だけ `PersonalShell`）。使うときに自動で読み込まれる |
| `home/dot_config/powershell/snippets.json.tmpl` | zeno の YAML から生成する snippet の定義 |
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
- **oh-my-posh は streaming で動かす（pwsh のみ）**: テーマ（`themes/pure.omp.json`）の `"streaming": 100` が、
  プロンプトごとの `oh-my-posh.exe` の起動（MSIX の別名経由で約 65 ms）を、常駐の `oh-my-posh serve` に置き換える。
  遅い区画（git）は 100 ms で打ち切って `...` を出し、結果が出たらその場で描き直す。`Enter`→次のプロンプトは
  非 git で 146→48 ms、git で 269→142 ms（[実測](../research/shell/powershell-slow-2026-11.md)）。
  - **5.1・PSES・ISE では切る**: 5.1 は常駐でなくプロンプトごとの `stream` の起動になり、実測で遅かった。
    プロファイルは、ConsoleHost 以外と 5.1 のとき、`POSH_DISABLE_STREAMING` を init の間だけ立てる
    （init が `Enable-PoshStreaming` を呼ぶ時点で読まれる。子プロセスへ漏らさない。利用者が自分で立てていれば触らない）。
    5.1 は `$env:X = ''` が変数を削除するので、値は `'1'`、戻すときは `[NullString]::Value`。
  - **streaming が無いときは transient prompt を切る**: transient prompt は streaming が先に描いておく。
    無いと Enter ごとに `oh-my-posh` を起動し、5.1 で 143→295 ms（git で 270→393 ms）に遅くなる。
    `POSH_THEMES_PATH` のテーマ（`streaming` を持たない）のときも同じで、これまでの見た目と速さを保つ。
  - **テーマへの設定は `streaming` だけが効く**: 環境変数 `POSH_STREAMING` は、oh-my-posh が書き出す init スクリプトが
    設定の変更でしか作り直されないので、一度作られた後は反映されない（実測）。
- **キーバインドの設定は oh-my-posh の init より前に置く**: `Set-PSReadLineOption -EditMode` は割り当てを初期化する。
  init の後に置くと、init が足した Enter / Ctrl+c のハンドラが消え、transient prompt が出ず、streaming の
  プロンプトが更新されなくなる（`Get-PSReadLineKeyHandler -Bound` で Enter が `AcceptLine` なら消えている。
  試験は `test_deployed_profile_in_interactive_terminal`）。
- **起動後の idle の処理は最小にする**: `PowerShell.OnIdle` の action は PSReadLine の入力ループと同じスレッドで走り、
  その間は打った文字が画面に出ない（実測: Chocolatey・PSFzf・ZLocation を読むと、プロンプトの後 0.3〜1.1 秒）。
  登録は 1 箇所に集約し、中身は ZLocation の読み込みと `Register-FzfKeyHandler` だけにする。
  - PSFzf の Ctrl+t / Ctrl+r は、仮のハンドラ（`PSFzf (lazy)`）を置き、初めて押されたときに読み込んで本物へ差し替える（約 0.25 秒）。
    読み込めないとき（未導入・壊れている）は警告し、標準の割り当て（Ctrl+r は履歴の逆方向の検索、Ctrl+t は文字の入れ替え）へ戻す。
  - Chocolatey のプロファイル（`refreshenv`・`choco` の補完）は、仮の関数と補完を置き、使われたときに読み込む（約 0.3 秒）。
    読み込み済みのとき（プロファイルの再読み込み）は仮の定義を置かない。仮の補完が本物を上書きした状態で自分自身へ戻らないよう、仮の補完の `Import-Module` は `-Force`。
  - ZLocation は、プロンプトごとに `prompt` を包んで重みを書くので、使うときまで遅らせられない。起動後に 1 回、約 0.37 秒止まる。
- **遅さを測る**: `scripts/windows/measure_pwsh_latency.py`（ConPTY。起動・打鍵の反映・Enter→プロンプト）。
  結果と、原因でなかったもの・残った候補は [調査記録](../research/shell/powershell-slow-2026-11.md)。

- **ssh では RedirectionGuard が junction を止める**: sshd は RedirectionGuard（管理者でないユーザーが作った junction を
  辿らせない保護）を有効にして動き、子のシェルも引き継ぐ（scoop の
  [Issue #6594](https://github.com/ScoopInstaller/Scoop/issues/6594)。2026-11-25 取得）。この機で、保護を有効にしたプロセスから
  scoop の shim を呼ぶと、報告と同じ `Shim: Could not create process` を再現した
  （`scripts/windows/run-with-redirection-guard.ps1`。再現の記録と、ほかの影響は
  [調査記録](../research/shell/redirectionguard-ssh-2026-11.md)）。
  - **scoop の `current`（junction）は実体のバージョンのディレクトリで置き換える**: 環境変数 `SSH_CONNECTION` がある
    （ssh のセッションと、その子孫が継承する。保護が効いているかの判定ではない）ときだけ `scoop-path.ps1` を読み、
    `Add-ScoopRealPathEntry` が PATH を次のとおりにする（PowerShell 7.2 以降の `ResolveLinkTarget`。sshd の既定シェルは pwsh 7）。
    1. PATH の `apps/<app>/current/…` の項目は、**その位置で**実体へ置き換える（`gcc` など、別のツールとの解決の順を変えない）。
       入れ子のシェルが引き継いだ前の版の実体の項目（`apps/<app>/<版>/…`）も、最新の実体へ置き換える（scoop の更新後に旧版が先に解決されない）。
    2. shim（`shims/*.shim`）の指す先のディレクトリを、shims の直前へ足す。ローカルと同じ優先順位（shims より前の Windows 標準のコマンドが先）を保つ。
       shim の無いディレクトリと、`current` が壊れている・無いアプリは対象にしない。失敗しても PATH は変えず、警告だけ出す。
    ローカルの起動の時間は増えない。確認したのは、保護を有効にしたプロセスでの `ghq`・`gcc`・`make`・`7z`・`pdftk` の起動まで
    （shim 119 個すべてを実行したわけではない。実際の ssh は未確認）。
  - **`vim` は Git for Windows の実体を直接呼ぶ**（対話時だけの関数。実体が無い機では定義しない）: gow の `vim` は 7.4（2013 年）で、
    この `.vimrc` の `signcolumn` や `fixendofline` を解釈できず、構文の runtime も無い。ssh でなくても、Git の vim を使う意味がある。
    パイプの入力は `$MyInvocation.ExpectingInput` で明示的に渡す。
  - **uv は システムの Python だけを使わせる**: uv が管理する Python は、`%APPDATA%\uv\python\cpython-3.14-…` の junction 経由なので、ssh では
    `uv run`・`uvx`・pre-commit の ruff などが `Failed to inspect Python interpreter` で動かない。ssh のとき（`SSH_CONNECTION`）だけ
    `UV_PYTHON_PREFERENCE=only-system` を設定する（利用者が指定していれば尊重）。システムに無い版を求めると `No interpreter found` になる。
    uv の管理 Python で作った既存の `.venv`（`pyvenv.cfg` の `home` が junction）は、この設定でも ssh では動かない。作り直す
    （[調査記録](../research/shell/redirectionguard-ssh-2026-11.md#対処)）。
- **PATHを冪等に更新する**: `mise activate` は毎回PATHの先頭へ追加するため、
  追加後に重複を畳みます。
  あわせて未展開の `%VAR%`（例: `%USERPROFILE%\AppData\Local\Microsoft\WindowsApps`）を展開します。
  ssh（`sshd`）経由のセッションは、ユーザー PATH の `%VAR%` を展開せずに渡し、MSIX 版 oh-my-posh の
  エイリアス（`WindowsApps`）が見つからずテーマが出なかった（[観測](../research/chezmoi/structure-windows-notes.md)）。

この構成にしたときの起動時間の計測は
[PowerShell プロファイルの起動時間](../research/shell/powershell-profile-startup.md)
にあります。
