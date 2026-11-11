# pi-sandbox-runner（pi のコマンド実行を包む囲い）

pi の `shellPath`（pi のシェル）に差す囲い。pi が実行するコマンド（bash ツール・`bg_run`・利用者の `!`・子エージェントの bash）を、bwrap の内側で動かす。見える範囲は許可リスト型で、GPU は通す。
採用の判断は [ADR-0036](../../adr/0036-pi-sandbox-shell-wrap-and-tool-policy.md)（拡張を使う [ADR-0035](../../adr/0035-pi-sandbox-gpu-runner.md) を置き換えた）、実測は [調査記録（Fence と bwrap）](../../research/agents/fence-latency-2026-11.md)・[調査記録（拡張の比較）](../../research/agents/pi-gpu-sandbox-2026-11.md)。Linux（Ubuntu / WSL）専用。

## 位置づけ

- **コマンドの実行だけを包む。** pi 本体・LLM の認証・拡張・MCP は外側で動く（信頼するコード）。ファイルの道具（`read`・`write`・`edit`）は囲いの外で、権限の層（`pi-permission-system`）がパスで判定する。
- 守る対象は、外部の文章に指示された、敵対的でないモデルの危険な操作（うっかりを含む）。悪意のあるコードやモデルは範囲外（環境ごとの隔離の領分。[ADR-0027](../../adr/0027-isolation-unit-is-environment.md)）。
- `pis`（pi 全体を Fence で包む。凍結。[ADR-0030](../../adr/0030-freeze-agent-stack-return-to-stock-pi.md)）とは別物。docker・compose を内側で使う開発は扱わない（docker を塞ぐ）。

### 隔離の層（どこに境界を引くか）

判断の層（`pi-permission-system`・`cc-safety-net`。実行前の許可・確認・拒否）の下に、実行の隔離が 4 通りある。

| 層 | 何を包むか | LLM の認証 | 例 |
| --- | --- | --- | --- |
| a. pi ごと | pi のプロセス全体 | 内側 | Docker（`pi-less-yolo`）、`pis`（凍結） |
| **b. コマンドの実行だけ（同じホスト）** | pi が起動するシェル。パスはホストのまま | 外側 | **この囲い（`pib`）** |
| c. ツールを別環境へ | ツールの実行先（別の OS・ファイルシステム） | 外側 | `ssh.ts`（公式の例）、Gondolin |
| d. 環境ごと | エージェントも docker も環境の中 | 環境ごと | 専用 WSL・Incus・devcontainer（[ADR-0027](../../adr/0027-isolation-unit-is-environment.md) の P3） |

```text
pi 本体・LLM 認証・拡張・MCP（外側）
 ├ 判断: pi-permission-system / cc-safety-net（コマンドの文字列と、ファイルの道具のパスを判定）
 ├ ファイルの道具（read / write / edit）→ 囲いの外（パスの判定だけで守る）
 └ コマンドの実行（bash ツール・bg_run・利用者の !・子エージェントの bash）
     → shellPath = pib-shell → pi-sandbox-runner → bwrap（カーネルの namespace）→ bash -c <コマンド>
```

### 起動の選択肢（隔離の強さと手軽さ）

| 起動 | 層 | 守り・手軽さ |
| --- | --- | --- |
| `pi` | 判断だけ | 隔離なし。最も手軽。ホストの認証が見える。docker・Windows 側の実行ファイルも使える |
| `pib` | b | 作業ツリーだけ書き込み可。ホーム・`/mnt`・`/tmp` は空で覆い、設定に書いた所だけ見せる。秘密を隠す・docker 遮断・環境変数のトークンを消す。GPU 可。通信は開いている |
| `pib --offline` | b | `pib` に加えて、通信を丸ごと遮断する（強い設定）。ネットワークが要る作業は、`pib` か `pi` で行う |
| `pi -e <ssh.ts> --ssh root@host:/work` | c | read・write・edit・bash が環境の中で動く。GPU・compose は環境が持つ。環境の準備が要る（[調査記録](../../research/agents/pi-gpu-sandbox-2026-11.md#sshts-によるツール委譲の試験)） |

`pib --help`（日本語の使い方。**pi のヘルプを上書きする**。pi のヘルプは `pi --help`。先頭に置いたときだけ。配備が壊れていても読める）と `pib [--offline] --status`（読み取り専用の診断。囲いが使える状態か、いま効いている設定を見せる）がある。

強さは**起動時に選ぶ**（実行中には切り替えない）。囲いの外が要る作業（`gh`・`git push`・docker・Windows 側の実行ファイル）は、`pi`（囲いなし）か別のターミナルで行う。昇格の仕組みは作らない。

## 部品

| 部品 | 置き場（source state） | 配備先 |
| --- | --- | --- |
| 囲い（runner） | `home/dot_local/bin/executable_pi-sandbox-runner` | `~/.local/bin/pi-sandbox-runner` |
| シェル（pi の `shellPath`） | `home/dot_local/bin/executable_pib-shell` | `~/.local/bin/pib-shell` |
| 起動 | `home/dot_local/bin/executable_pib` | `~/.local/bin/pib` |
| `shellPath` の設定 | `home/.chezmoitemplates/modify_pi_stock_settings.py.tmpl`（`home/dot_pi/agent/modify_settings.json.py.tmpl` が呼ぶ） | `~/.pi/agent/settings.json` の `shellPath`（Linux だけ。利用者が別の値を書いていれば保つ） |
| 設定（共有） | `home/dot_config/pi-sandbox/runner.toml` | `~/.config/pi-sandbox/runner.toml`（chezmoi 管理。apply で上書きされる） |
| 設定（このマシンだけ） | `home/dot_config/pi-sandbox/runner.local.toml.example`（見本） | `~/.config/pi-sandbox/runner.local.toml`（**chezmoi の管理外**。見本をコピーして作る。任意） |
| 実機の確認 | `scripts/pi_sandbox_selftest.py` | `python3 scripts/pi_sandbox_selftest.py`（リポジトリ直下で実行） |
| 試験 | `test/test_pi_sandbox_runner.py` | — |

Linux 以外へは配らない（`.chezmoiignore.tmpl`）。pi の拡張は使わない（`@yuru7/pi-sandbox` を外した。[ADR-0036](../../adr/0036-pi-sandbox-shell-wrap-and-tool-policy.md)）。

## 仕組み

### 呼び出し

pi は、シェルを `<shellPath> -c <コマンド>` で起動する（`shellPath` は `settings.json` の設定。pi の bash ツール・`bg_run`（`pi-background`）・利用者の bash（`!`）・子エージェントの bash が、同じ経路を通る。実測は下の「導入と確認」）。

```text
pib-shell -c <コマンド>
  PIB_SANDBOX が空   → /bin/bash -c <コマンド>（普段の pi は何も変わらない）
  PIB_SANDBOX = 1    → pi-sandbox-runner -c <コマンド>
  PIB_SANDBOX = offline → pi-sandbox-runner --offline -c <コマンド>
```

`pib` が `PIB_SANDBOX` を立てて pi を exec する。囲いを通すと決まったのに runner が無いときは、`pib-shell` の exec が失敗して終わる（**素の bash へ落とさない**）。`pib-shell` は、自分の隣の `pi-sandbox-runner` を呼ぶ。

### bwrap の引数（並びはコードに固定。設定では変えられない）

後から重ねた mount が勝つので、並びが意味を持つ。

| 順 | 引数 | 内容 |
| --- | --- | --- |
| 1 | `--die-with-parent --new-session --unshare-pid` | 親が死ねば終わる。端末の入力の注入（TIOCSTI）を防ぐ。PID の名前空間を分ける |
| 2 | `--ro-bind / /`、`--dev /dev`、`--proc /proc` | ルートを読み取り専用で重ね、`/dev` と `/proc` を作り直す |
| 3 | `--tmpfs` で、`/tmp`・`/var/tmp`・`/mnt`・`/media`・`/run/user`・**ホーム**を空にする | ホストと共有しない場所。tmux・X11・ssh-agent のソケット、Windows のドライブ、docker のソケット、ホームの履歴・鍵を見せない。無い場所は覆えない（読み取り専用のルートに作れない）ので飛ばす |
| 4 | `visible.read`（`--ro-bind`）、`visible.write`（`--bind`） | 設定に書いた所だけを、覆ったホームなどの上に重ねる。無い場所は飛ばす。ホームそのものとその親は書けない（エラー）。書いたパスの途中がシンボリックリンクなら（例: `~/papers -> /data/papers`）、実体を重ね、覆われて消えたリンクも `--symlink` で作り直す。リンクの先がまた覆った場所（`/mnt` など）の中なら、その先のリンクも作る。覆っていない場所のリンクは、ルートの重ねに残る。リンクかどうかは実際のリンクで判定し（`.` や `//` は整える）、`..` を含むパスは設定の検証でエラー |
| 5 | `--bind <作業ディレクトリ>` | pi を起動した場所（cwd）だけを書き込み可にする。ホームを含む場所（`/`・ホーム・その親）では起動しない |
| 6 | worktree の git ディレクトリを `--bind` | 作業ディレクトリが git の worktree のとき、共有の `.git` と worktree の領域（下の「git」） |
| 7 | `--chdir <作業ディレクトリ>` | |
| 8 | GPU のデバイスを `--dev-bind` | `gpu.devices`。`auto` は `/dev/dxg`・`/dev/nvidia*` のうち存在するもの。`--dev /dev` の**後**に置く（前だと隠れる。通常の `--bind` は nodev でデバイスを開けない） |
| 9 | 書き込み可で渡る git ディレクトリの、**存在する** `hooks`・`config`・`config.worktree` を `--ro-bind` | `git.protect` |
| 10 | 隠す場所: ディレクトリは `--tmpfs`、ファイルは `--ro-bind /dev/null` | `hide.dirs` / `hide.files`。**`visible` の後**なので、見せた場所の中の秘密（例: `~/.config/git/credentials`）も隠せる。シンボリックリンクは解決した実体で覆う（リンクのままだと bwrap が失敗する） |
| 11 | `/run/user/<uid>` を空にし、`/run/docker.sock`・`/var/run/docker.sock` を `/dev/null` で覆う | `docker.block` |
| 12 | `--unshare-net`（`--offline` のときだけ）、`--unsetenv <名前>`、`--setenv MISE_STATE_DIR /tmp/pib-mise-state` | `env.unset`。`mise` の状態（信頼の記録）をホームの外の使い捨ての場所へ向け、ホームの状態を書き換えさせない |
| 13 | `--`、`/bin/bash -c <コマンド>` | |

ホームは空の tmpfs なので、内側から `~/…` に書いても成功するが、外へは届かない（コマンドは終わると消える）。

### git

- 作業ディレクトリが通常のリポジトリなら、`.git` は作業ディレクトリの中にある。9 で `hooks`・`config` を読み取り専用にする。
- **worktree**（`.git` がファイル）は、`gitdir:` の先を信じない（エージェントが書き換えられるため）。git が worktree の登録時に書く **back-reference**（`<gitdir>/gitdir` が、この作業ディレクトリの `.git` を指す）と、`commondir`（`<共有 .git>/worktrees/<名前>` の形）が揃うときだけ、共有の `.git` と worktree の領域を書き込み可で渡す。揃わなければ渡さず、標準エラーに理由を出す（git は動かないが、他の場所は見えない）。
  - **共有の `.git` は、gitdir の位置から決める**: gitdir は `<共有 .git>/worktrees/<名前>` の**直接の子**でなければならず、`commondir` の値は、その位置と一致するかの確認にだけ使う（`commondir` を書き換えて別の git ディレクトリへ向けられない）。
  - **登録情報がエージェントの書ける場所（作業ディレクトリ・書き込み可の `visible`）にあるものは、形が揃っても信じない。** gitdir のディレクトリだけでなく、読む 2 つのファイル（`gitdir`・`commondir`）の実体（リンク先を含む）も調べる。そこに `.git`・`gitdir`・`commondir` を作って自己証明すれば、形の検証を通せるため（祖先に `HEAD` と `objects` がある場所を、共有の `.git` に見せかけて書き込み可にされる）。
  - 共有の `.git` が作業ディレクトリを含む場合も渡さない。
- pi は、**リポジトリの根か、worktree の根**で起動する。サブディレクトリで起動すると、親の `.git` は渡らない。サブモジュール（back-reference が無い）も渡らない。

## 設定（`runner.toml`）

既定では、利用者の階層（`$XDG_CONFIG_HOME/pi-sandbox/runner.toml`、無ければ `~/.config/pi-sandbox/runner.toml`）だけを読む。**作業ツリーは探さない**（エージェントが書き換えられるため）。`PI_SANDBOX_RUNNER_CONFIG` で場所を変えたときは、その場所を読む（試験・調査用。信頼できる利用者が指定する前提）。

```toml
version = 1
[gpu]
devices = ["auto"]          # "auto" か /dev/ 以下の絶対パス。無効にするなら []
[visible]                   # 許可リスト: ホーム・/mnt・/tmp・/run/user は空で覆われ、ここに書いた所だけが見える
read  = ["~/.local/share/mise", "~/.gitconfig", "~/.config/git/config"]   # 読み取り専用。~/.config/git は丸ごと見せない
write = ["~/.cache/uv", "~/.npm", "~/.cache/huggingface/hub"]            # 書き込み可（標準のキャッシュ。huggingface は全体にしない）
[hide]                      # visible の中や下の秘密をさらに隠す（hide が勝つ）
dirs  = ["~/.ssh", "~/.config/gh"]   # 空の tmpfs で覆う
files = ["~/.netrc", "~/.git-credentials", "~/.config/git/credentials"]   # /dev/null で覆う
[env]
unset = ["GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK"]   # 内側へ渡さない環境変数（拒否リスト）
[docker]
block = true                # compose を内側で使うときだけ false
[git]
protect = true
```

- 設定にするのは、リストとオン・オフだけ。任意の追加引数（`extra_args`）は作らない（抜け道になる）。
- **このマシンだけの追記（`runner.local.toml`）**: `runner.toml` と**同じ場所**に置く任意のファイルで、共有設定に**足す**。chezmoi の管理外なので、`chezmoi apply` で消えず、`chezmoi diff` にも出ない。見本（`runner.local.toml.example`）をコピーして作る。
  - 書けるのは `[hide] dirs` / `files`、`[visible] read` / `write`、`[env] unset`。リストは共有設定の**後ろ**に足し、重複は 1 つにする。`version` は省略できる（書くなら 1）。**データセットなど、このマシンだけの見せたい場所は、ここに足す**（例: `read = ["/mnt/d/datasets"]`）。共有の `hide` は後から勝つので、見せた場所の中の秘密は隠れたまま。
  - **共有設定を緩めるものは書けない**: `[gpu]`（デバイスの公開）・`[docker]`・`[git]`（共有側の `block = true`・`protect = true` を、このマシンだけ false にする抜け道）があれば、起動しない。共有のエントリを消すこともできない。
  - 検証は共有設定と同じ規則。**エントリがあるのに読めない**（壊れたシンボリックリンク・ディレクトリ・権限・UTF-8 でない・構文エラー）ときは、fail-closed（下）。無視するのは、エントリ自体が無いときだけ。有効なシンボリックリンクはたどる。
  - 反映は、次にコマンドを実行したとき（runner は毎回読む）。`chezmoi apply` は要らない。
  - 場所は、共有設定の場所の隣の `runner.local.toml`。作業ツリーは探さない。
- **検証は厳格**: `version = 1`（整数。`true`・`1.0` は不可）が必須。未知のキー・型の誤り・`gpu.devices` の `/dev/` 以外（`/dev/` 自体・末尾の `/`・`//` を含む）・`hide`・`visible` の相対パスや `/`・`~/` そのもの・`..` を含むパス・`env.unset` が環境変数の名前でないものは、エラー。起動時には、`visible` がホームかその親を指す、作業ディレクトリがホームを含む、もエラー。
- **fail-closed**: 設定（共有・このマシンだけの追記のどちらも）が読めない（UTF-8 でない場合を含む）・壊れている、共有設定が無い、使い方が違う（`-c <コマンド>` 以外）、作業ディレクトリが広すぎるときは、bwrap を起動せず終了コード 2。エラーは `pi-sandbox-runner:` で始める。bwrap が無いときは 127。
- 環境変数（試験・調査用）: `PI_SANDBOX_RUNNER_CONFIG`（設定の場所）、`PI_SANDBOX_RUNNER_DRYRUN=1`（exec せずに最終の引数を JSON で出す）。`PIB_SANDBOX`（`pib` が立てる。`1` か `offline`）。

## 導入と確認

1. `chezmoi apply` で、上の部品が配備され、`~/.pi/agent/settings.json` に `shellPath`（`~/.local/bin/pib-shell`）が入る（Linux だけ。利用者が別の値を書いていれば保つ）。`shellPath` は全セッション共通の設定だが、`PIB_SANDBOX` が無いときは素の bash なので、普段の `pi` は変わらない。
2. **`pib` で起動する**（`pib --offline` は通信なし）。囲いが効かない状態では**起動しない**。黙って囲いなしで動き、守られているつもりになるのを避けるため。
   - runner・`pib-shell`・設定・bwrap のどれかが無い。
   - 利用者の `settings.json` の `shellPath` が、配備した `pib-shell` の**絶対パスそのもの**（`~/` の略記は可）でない。**別名（シンボリックリンク）は認めない**: 作業ツリーの中のリンクを、囲いの内側から別のシェルへ付け替えられる（pi は値を realpath にせず、そのパスを実行する）。
   - `HOME` と `PI_CODING_AGENT_DIR`（`~`・`~/` の略記は展開して判定）が、**正規の絶対パス**（`.`・`..`・連続する `/`・末尾の `/`・先頭の `//` を含まない）でない。pi は設定のパスを、文字列だけで整える（Node の `join`。`~//x` はホームの下の `x`、`link/../x` は `link` の親の `x`）。OS は、シンボリックリンクを辿ってから `..` を解く。この違いで、pib が検査する設定と pi が読む設定が別になりうる（既定の設定ディレクトリは `HOME/.pi/agent` なので、`HOME` も同じ）。`pib` は pi の解釈を再現せず、**食い違いようのない表記だけを受け付ける**（相対パス・`file://` も不可）。
   - `--approve` / `-a` が引数にある。`pib` は pi を**常に `--no-approve` で起動する**。プロジェクトの `.pi/settings.json` は利用者の設定に勝ち、`shellPath` を上書きできる。起動時の作業ディレクトリを検査するだけでは、セッションの再開（`--session`）や `/resume` で別のディレクトリのセッションへ移ったときに、その設定を検査できない。`--no-approve` は、実行時（runtime）に、プロジェクトの `.pi/` の設定・拡張・MCP を読まない（pi の project trust の仕様で、コマンドラインの指定が最優先。実測: 作業ツリーの `shellPath` が、`--no-approve` なしでは効き、ありでは無視された）。**起動時の例外**: セッション保存先の `sessionDir` だけは、信頼の判断より前に読まれる（pi 同梱の文書 security.md の「Understand project trust」）。これは `shellPath` に影響しない。runtime は別の設定管理を、プロジェクトを信頼しない状態で作る（pi 1.5.0 のソースで確認）。**代償**: `pib` の実行では、プロジェクトの `.pi/` の設定（例: データセットを読み取り専用にする権限の設定）が効かない。そういう作業は `pi` で行うか、見せたい場所を `runner.local.toml` の `visible` に足す。
   - 早期の警告として、作業ツリーの `.pi/settings.json` に `shellPath` のキーがあり**、値が `pib-shell` の絶対パスそのものでない**（`null`・`false`・`0` も含む）、または**読めない**（壊れた JSON・オブジェクトでない・ディレクトリ・不正な文字コード。BOM は pi と同じく取り除いて読む）場合も、起動しない。保証は `--no-approve` が担い、この検査は、起動時の作業ディレクトリの誤りを早く知らせるもの。
3. **`pib --status` で、いま効いている設定を確かめる**（`pi-sandbox-runner [--offline] --status` が本体で、`pib` は配備の検査を足して呼ぶ。bwrap は起動しない）。表示するのは、設定の場所と、このマシンの追記の有無・通信（開いている／遮断）・GPU・作業ディレクトリ（`.git` を渡せない理由、ホームを含む場所では起動できない理由を含む）・見える場所（読み取り専用／書き込み可）・隠す場所・消す環境変数。`visible` / `hide` の無い場所は黙って飛ばされるので、**存在の印**を付ける: `✓` ある、`-` この PC に無い（共有の既定。入れていない道具が多いので警告しない）、`✗` **このマシンの追記なのに無い**（綴りの誤り。`hide` の綴りの誤りは、秘密を隠せないので特に注意）。使える状態なら終了コード 0、使えないなら 2（理由を列挙する）。runner が、この場所・この設定では起動できないと答えたとき（作業ディレクトリがホームかその親、`visible` がホームを指す、など）も、一覧は出したうえで 2 を返し、`pib --status` の見出しは「使えない」になる。
4. `python3 scripts/pi_sandbox_selftest.py` で、書き込み・見えない場所（履歴・Windows のドライブ・共有の `/tmp` とソケット）・秘密の隠蔽・git の認証・環境変数・docker・worktree の git・`--offline`・GPU の CUDA カーネルを、内側から確かめる（確認できない項目は SKIP）。
5. pi を通した確認（2026-11-12、WSL2、pi 1.5.0）: 作業ツリーの `.pi/settings.json` に `shellPath` を置き、`PIB_SANDBOX=1` で `pi -p` を動かした。次の 4 つが、同じ囲いを通った（内側では `/mnt/c` が見えず、`MISE_STATE_DIR` が設定される）。
   - bash ツール（`/mnt/c` のエントリ数 0。ホストでは 19。作業ツリーに書け、`git status` が動く）。
   - `bg_run`（同じく 0）。
   - 利用者の bash（`!` と同じ経路。RPC の `bash`）。TUI での `!` は未確認。
   - 子エージェント（`worker`）の bash（`printenv MISE_STATE_DIR` が `/tmp/pib-mise-state`。ホストでは空。子の返答に基づく）。

## 認証情報の扱い

ホームは空で覆われ、見えるのは `visible` に書いた所だけ。そのうえで `hide` が後から勝つ。観測は 2026-11-12、WSL2。

| 認証情報 | 囲いの内側 | 確認 |
| --- | --- | --- |
| pi の LLM 認証（`~/.pi/agent/auth.json` など） | 見えない。pi 本体は外側で動くので使える | 設計（ホームは覆われる） |
| gh（`~/.config/gh`） | 見えない。内側の `gh auth status` は「未ログイン」 | 実測 |
| git の push（https。`credential.helper = store`） | `~/.git-credentials` は見えず、`~/.config/git/credentials` は `hide` で隠す。内側の `git credential fill` は認証を見つけない（終了コード 128。ホストでは 0） | 実測 |
| ssh 鍵（`~/.ssh`）・ssh-agent | 見えない。agent のソケットは `/tmp`・`/run/user` が空で、`SSH_AUTH_SOCK` も消す | 設計・自己確認 |
| aws・gcloud・kube・docker の設定 | 見えない（ホームは覆われ、`hide` にも入れてある） | 設計（この機は aws CLI が無く、動作は未確認） |
| 環境変数のトークン（`GH_TOKEN`・`GITHUB_TOKEN`・`AWS_*`・`ANTHROPIC_API_KEY` など） | `env.unset` の一覧の名前は消える。**一覧に無い名前は渡る**（拒否リスト） | 自己確認（`GH_TOKEN`） |
| シェル履歴・Windows のドライブ | 見えない | 自己確認 |

- **見えないのは、コマンドの内側だけ。** pi の `read` ツール（プロセス内）は囲いの外。秘密のパスを読ませない役は、`pi-permission-system` の path ルールが担う。ファイルの道具が作業ツリーの外を触るときの判定は、ソースで確認した: 外かどうかの判定は、**シンボリックリンクを解決した実体のパス**で行う（`external-directory` のゲート）。ただし方針は `external_directory` が **ask**（`/tmp/*` だけ allow）で、YOLO が入っていると自動承認になり、誰も答えない確認は 5 分で拒否される。**止めるのではなく確認にする**ことと、YOLO では効かないことは、実機での試験をしていない（認証ファイルへのリンクが権限の方針で拒否され、一時の agent ディレクトリを作れなかった）。
- **通信は開いている**ので、内側から見えるものは外へ出せる。見える範囲を絞ることで、持ち出せるものを減らす。通信を使わない作業は `pib --offline`。
- **gh・git push・issue / PR の投稿は、内側では認証がなく失敗する。** 利用者が打つ `!gh ...` も囲いの内側なので失敗する。外側が要るときは、`pi` か別のターミナルで行う。権限の方針（`git push` は deny、`gh` の変更系は強制 ask）が第一の層で、囲いは第二の層。

## 保証しないこと・限界

- **コマンドの実行だけを包む。** ファイルの道具（`read`・`write`・`edit`）・pi 本体・拡張・MCP サーバーは外側で動く。MCP で GitHub などへ書き込めるものを入れると、囲いの外から書き込める。
- **ルートは読み取り専用で見える。** 覆うのは、ホーム・`/tmp`・`/var/tmp`・`/mnt`・`/media`・`/run/user` だけ。それ以外の場所（`/etc`・`/opt`・`/srv`・他のユーザーのホームなど）は読める（書けない）。他のユーザーのホームは、ファイルの権限が守る。
- **通信は無制限**（`--offline` で全遮断。ドメインの許可リストは作らない）。
- **環境変数は拒否リスト。** `env.unset` に無い名前（独自のトークンなど）は渡る。
- **docker を塞ぐので、compose は内側で使えない。** docker 経由で書き込み制限を破れるため（[実測](../../research/agents/pi-gpu-sandbox-2026-11.md#発見)）。塞ぐのは `/run/user` と、`/run/docker.sock`・`/var/run/docker.sock` だけ。ほかの場所のソケット（rootful の podman・containerd など）と、ネットワーク越しの `DOCKER_HOST`（tcp）は塞げない。
- **`/mnt` を覆うので、Windows 側の実行ファイル（`powershell.exe`・`code` など）は内側で呼べない。** `PATH` に `/mnt/c/...` があっても、内側では存在しない。
- **GPU のデバイスをさらす**ため、内側のコードにドライバの入口が開く（攻撃面は広がる。推測）。GPU の使用を制限する機能はない。
- **標準のキャッシュは書き込み可**（`visible.write`）。ホストが後で使う成果物（wheel・hook の環境・モデル）を、内側から差し替えられる。Hugging Face は、認証（`token`・`stored_tokens`）が同居するので、`hub`・`datasets` の下だけにし、認証は `hide` にも入れてある。
- **git の保護は限定的**:
  - 覆えるのは**既存**の `hooks`・`config`・`config.worktree` だけ。`hooks` が無いリポジトリや、`extensions.worktreeConfig` が有効で `config.worktree` がまだ無いリポジトリでは、内側から新規に作れる（ホストの git が後で実行・解釈する）。
  - `core.hooksPath` が作業ツリーの中を指すときは、その先は書き込み可。`info/`・`modules/`・ネストしたリポジトリ・サブモジュールは対象外。
  - 作業ツリーの外の `.git`（サブディレクトリで起動したとき）は渡らない。
- 隠したファイルは、内側から開くと権限エラーになる（空のファイルには見えない）。
- `mise` の状態（信頼の記録）は、コマンドごとの使い捨て（`/tmp/pib-mise-state`）。新しい worktree の信頼は、毎回やり直す。`mise install` は内側ではできない（`~/.local/share/mise` は読み取り専用）。
- `pib` の中で、さらに `pib` や `pi` を起動すると、入れ子の bwrap になる（動くかは未確認）。
- **抽象 UNIX ソケット（X11 の `@/tmp/.X11-unix/X0` など）は、パスを覆っても届きうる**（ネットワークの名前空間を分けていないため）。`pib --offline` は `--unshare-net` で名前空間を分けるので、届かない。通常の `pib` では未確認。
- 検証してから bwrap が mount するまでの間（パス名で渡すため）の競合は、実 bwrap での再現を確かめていない。
- 守るのは「うっかり」と、外部の文章に指示された非敵対的なモデルまで。悪意のあるコードは範囲外。

## 試験

- `uv run --with pytest --no-project pytest test/test_pi_sandbox_runner.py -q`: 設定の検証（このマシンだけの追記の併合・緩める指定の拒否を含む）・引数の組み立て（許可リスト型の並び・worktree の git の検証・hide が visible に勝つ・環境変数・`--offline`）・CLI の fail-closed・`pib` の起動の検査（`shellPath`・プロジェクトの上書き）・`pib-shell`（素の bash・runner への委譲・runner が無いときに素の bash へ落ちない）・実際の bwrap（使える環境だけ）での見える範囲・書き込み・隠蔽・git・環境変数・通信の遮断。CLI と実 bwrap の試験は Linux 以外では skip する（runner は `os.getuid()` と bwrap を使う）。
- `python3 scripts/pi_sandbox_selftest.py`: 実機の確認（上の「導入と確認」）。
