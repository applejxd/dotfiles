# AI CLI の sandbox (Claude Code / Copilot CLI)

Claude Code / Copilot CLI の sandbox 層 (`[sandbox]`) とネットワーク層、
マシン固有の許可の足し方をまとめる。この文書は Claude Code / Copilot CLI の
sandbox (`[sandbox]`) の仕様で、`pis` の Fence の仕様ではない
(`pis` の読み手は [sandbox の仕様一覧](index.md) から入る)。
全体像は [AI CLI 統合 permission / hook 管理](../agent-permissions.md)、
OpenCode の隔離起動 (`ocs`) は [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)
が正本。

## sandbox 層 (`[sandbox]`)

> [!NOTE]
> `[sandbox]` が扱うのは**パスのポリシー**だけで、sandbox が起動できること自体は
> ホスト側の前提条件になる。Linux の bubblewrap backend は `bwrap` /
> `slirp4netns` / `unshare` / `nsenter` / `iptables` などを probe し、1 つでも
> 欠けると**起動を拒否して全ツールが失敗する**。症状と一覧は
> [Linux で sandbox がコマンドを 1 つも実行できない](../troubleshooting-agents.md#linux-で-sandbox-がコマンドを-1-つも実行できない)
> を参照。

### なぜ既定が逆なのに揃えるのか

**既定は実際に逆向き**である。Claude は「read はほぼ全許可 + deny を引く」
ブラックリスト、Copilot は deny-by-default のホワイトリスト。
それでも揃えているのは次の理由による。

1. **Claude の既定が緩すぎる。** 公式が
   「この既定では `~/.aws/credentials` や `~/.ssh/` も読める」と明記している。
   何もしなければ Copilot より明確に緩くなり、
   「Copilot は緩め、Claude は制約のある環境でも使えるよう厳し目」という運用方針が逆転する
2. **ブラックリストは fail-open。** 列挙し忘れた秘密は黙って読める。
   ホワイトリストは fail-closed で、新しいツールが動かなくなる形で
   気付ける。**壊れ方が見える側**を選んでいる
3. **公式に支持された構成。** `denyRead: ["~/"]` + `allowRead` は
   Anthropic のドキュメントが例示している形で、回避策ではない

コストは `claude_read_allow` のパスを手で維持していること。
Copilot 側も `copilot_read_allow` で同じものを列挙する。以前は
`allowDevToolAccess` が自動で行っていたが、不具合のため切っている
([ADR-0008](../../adr/0008-explicit-dev-tool-grants.md))。

> [!NOTE]
> 揃えているのは **filesystem だけ**。network は Copilot にドメイン単位の
> 制御が無く、`allowedUrls` も「プロンプトを省略する URL」であって制限では
> ないため、**実効ポリシーを揃えられない**。
> 層ごとの方式の違いは
> [sandbox機能の包括調査](../../research/agents/sandbox-capabilities.md) を参照。

### ホーム外の経路は塞いでいない（契約と実装の不一致）

`deny` / `claude_read_allow` が扱うのは **`~/` 配下だけ**。ホーム外の扱いは
Claude と Copilot で既定が逆なので、分けて書く。

- **Claude**: `denyRead: ["~/"]` の外は sandbox runtime の既定（読みは全許可）の
  まま残る
- **Copilot**: 全体が whitelist なので、ホーム外も明示の許可が無ければ見えない
  （下の「どちらの CLI で不足しているのかを切り分ける」）。`copilot_read_allow` が
  ホーム外に開けているのは `/usr/include` `/usr/local` `/usr/src` `/opt` だけ

| 経路 | 明示の deny（両 CLI） | Claude の明示の allow | Copilot の明示の allow | `ocs`（OpenCode） |
| --- | --- | --- | --- | --- |
| `/mnt`（WSL の Windows 側） | なし | なし（既定で読める） | なし | 開けていないので見えない（`defaultDenyRead`） |
| `/tmp` `/var/tmp` `/dev/shm` | なし | なし（既定で読める。ホストと共有） | なし（`$TMPDIR` は既定で read-write） | `/tmp` と `/dev/shm` は専用の tmpfs、`/var/tmp` は見えない |

Claude の `/mnt` `/tmp` 系への `denyRead` / `allowRead` の指定は無く、sandbox 内から実際に読めるかは
**未検証**。Copilot の既定は `/mnt/wsl/resolv.conf` と `$TMPDIR` を除いて見えないが、現在の設定での
表示は未検証。実測の状況と未決の点は
[記録](../../research/agents/agent-sandbox-measurements.md#ホーム外の経路の実測の状況と未決の点)。
`deny` に足すときは、Copilot の `deniedPaths` にも流れるので両 CLI への影響を確かめてから入れる。

### キー名の規則

`common.toml` のキーは **共有 = 無印 / CLI 固有 = CLI 名の接頭辞** で統一する
(`[[hooks]]` の `claude_event` / `copilot_event` と同じ規則)。

| キー | 効く CLI | 用途 |
| --- | --- | --- |
| `[sandbox] deny` | Claude・Copilot | whitelist の内側でも遮断する秘密情報 (read/write 両方) |
| `[sandbox] seccomp_apply_path` | Claude | seccomp の適用バイナリ |
| `[sandbox] claude_read_allow` | Claude | whitelist に開ける読み取りの穴 |
| `[sandbox] claude_write_allow` | Claude | cwd + temp 以外に書き込みを許す場所 |
| `[sandbox] claude_write_deny` | Claude | read は許すが write を禁止する対象。`deny` に**追加**される |
| `[sandbox] shell_network_allow` | Claude・隔離起動 (`ocs` / `pis`) | shell が実際に通信する先 (CDN 等) |
| `[sandbox] claude_network_strict` | Claude | 許可外ドメインを拒否する (v2.1.219+) |
| `[sandbox] copilot_read_allow` | Copilot | Copilot が読める場所 (whitelist の本体) |
| `[sandbox] copilot_write_allow` | Copilot | 同上の書き込み |
| `[sandbox] copilot_allow_dev_tool_access` | Copilot | 開発ツール自動許可 (開発ツールの置き場へ sandbox の読み書きの許可を自動で足す)。`false` 固定 |
| `[file] claude_read_allow` | Claude | `Read()` の allow |
| `[file] read_ask_globs` / `write_ask_globs` / `read_deny_globs` / `write_deny_globs` | Claude・OpenCode (Copilot は `read_deny_globs` のみ) | Claude の `Read()` / `Edit()`、OpenCode の `read` / `edit` の ask / deny。Copilot は `check_file_read.py` が view へ適用 |
| `[bash] allow` / `ask` / `deny` | Claude・Copilot | ただし粒度が違う |

**新しく足すキー**では、無印は「Claude と Copilot の両方に効く」を意味する。
**片方にしか渡らない設定を無印で足してはいけない。** `[sandbox]` の既存の
`seccomp_apply_path`（Claude のみ）と `shell_network_allow`（Claude と `ocs` / `pis`）は
無印でも Copilot に効かない例外で、上の表の「効く CLI」列が正しい。`[file]` の
無印の `*_globs` も Claude と OpenCode 向けで、Copilot には `read_deny_globs` だけが
渡る。
実際、`copilot_*` が生まれる前の `read_allow` / `write_allow` は
名前の上ではただの許可に見えて Claude にしか効いておらず、Copilot 側で
`uv run` が動かない原因になっていた。

キーを読み違えても `.get(key, [])` は静かに空リストを返すため、綴り間違いや
旧名の残りは **防御が黙って消える** 形で現れる。`generate.py` の
`validate_sandbox_keys()` が `[sandbox]` と `[file]` の未知キーを検出して
apply を止める。

### 許可を足したくなったときの判断手順

「動かないので許可を足したい」は頻出する。**足す前に必ずこの順で判断する。**

#### Step 1. 本当に遮断されているのか確認する

`ENOENT` は「未許可」と「本当に無い」の区別がつかない。実効ポリシーで見る
(Copilot は `/sandbox policy`、Claude は `/sandbox` の Config タブ)。
`ls` が成功して 0 件なら **deny された空の tmpfs**。`Path.exists()` は
denied path でも真を返すので判定に使わない。

#### Step 2. 許可ではなく別の層で解けないか考える

| 症状 | 許可を足す前に |
| --- | --- |
| `/tmp` に書けない | `./.tmp` を使う (`redirect-tmp.py` が誘導している) |
| ホーム配下の秘密を読みたい | **足さない。** 値を伏せて渡す |
| 1 回だけ必要 | `claude --settings` / `--add-dir` |
| このプロジェクトだけ | 対話プロンプトで承認 (下記「このマシンだけで許可を足す」) |

#### Step 3. どちらの CLI で不足しているのかを切り分ける

ここが最重要。**両方で不足しているとは限らない。**

| 不足している側 | 典型的な原因 | 書く場所 |
| --- | --- | --- |
| Copilot だけ | ホーム外、または `copilot_read_allow` に未列挙 | `copilot_read_allow` / `copilot_write_allow` |
| Claude だけ | ホーム配下で `denyRead: ["~/"]` に掛かった | `claude_read_allow` / `claude_write_allow` |
| 両方 | 真に共通の要件 | それでも**両方のキーに書く**。無印キーは作らない |

判別のコツ: **ホームの外 (`/usr`, `/opt`, `/etc`) は Claude では既定で読める。**
Claude の `denyRead` は `~/` 配下しか塞いでいないため。
逆に Copilot は全体が whitelist なので、ホームの外も明示が要る。

実例 (`/usr/include`): Copilot は不可視、Claude は既定で読める
→ `copilot_read_allow` にだけ追加した。

#### Step 4. 粒度と権限を絞る

- **read で足りるなら read に留める。** 特に実行ファイルとヘッダは
  write を与えると、以後のビルド成果物へ任意コードを混ぜられる
- ディレクトリ全体ではなく、必要な部分木を指す
- Copilot は**ワイルドカード非対応・絶対パス限定**

#### Step 5. スコープを選ぶ

| 範囲 | 置き場 |
| --- | --- |
| 全マシンで必要 (ツールチェーン・システム領域) | `common.toml` |
| このマシンだけ (データセット置き場など) | `~/.config/agents/local.toml` |
| このプロジェクトだけ | 対話承認 / `[[copilot.locations]]` / `.claude/settings.local.json` |

#### Step 6. 根拠を書き、テストで固定する

`common.toml.tmpl` のコメントには **その値を足す/消すときの制約** と参照先
(`see docs/spec/sandbox/agent-sandbox.md 「<見出し>」`) だけを残す。制約と短い理由は
この文書の該当節へ、**実測値**と**何が壊れたかの経過**は `docs/research/` へ書いて
該当節からリンクする ([コメントの書き分け](../agent-config-generation.md#コメントの書き分け))。
`test/agents/test_generate_sandbox.py` に、そのパスが期待どおりの権限で
生成されることと、**write を与えていない**ことを固定する。

> [!IMPORTANT]
> **禁止 (deny) をこの手順で足さないこと。** CLI 固有キーは許可の補償専用で、
> 禁止を置くと片方だけ無防備になる。遮断は `[sandbox] deny` (Claude・Copilot 共通) か
> hook で行う。境界は [ADR-0007](../../adr/0007-filesystem-guard-boundary.md)。

### Copilot が読み書きできる場所 (`copilot_read_allow` / `copilot_write_allow`)

Copilot の filesystem は deny-by-default なので、このリストが
**Copilot に見える範囲そのもの**になる。以前は `allowDevToolAccess` が
`PATH` 上のツールやキャッシュを自動で許可していたが、
**この自動付与は切ってある** ([ADR-0008](../../adr/0008-explicit-dev-tool-grants.md))。

切った理由は 2 つ。

1. **取りこぼす。** 公式ドキュメントはキャッシュの扱いを
   "read-only for most locations, and read/write for selected writable locations"
   と書いており、**uv はこの選別から漏れていた**
2. **ユーザ指定を上書きする。** `readwritePaths` に書いたパスを自動付与の
   read-only が潰す (`github/copilot-cli#4846`)。しかも `/sandbox policy` は
   Read-write と表示するので、**表示からは気付けない**

自動付与が有効だった間は、`~/.cache/uv` が read-only のまま (`uv run` が EROFS)、
`~/.local/share/uv/python` と `/usr/include`・`/usr/local` が不可視だった。
**ライブラリは見えるのにヘッダが見えない**ように、粒度が直感と一致しない
(実測は [開発ツール自動許可の実効権限](../../research/agents/copilot-dev-tool-access-grants.md))。

現在のリストは `claude_read_allow` とほぼ同じ内容に、ホーム外を足した形になる。

```toml
copilot_read_allow = [
  "~/.local", "~/.cargo", "~/.rustup", "~/.nvm",
  "~/go", "~/.texlive",           # ツールチェーン
  "~/.config", "~/.gitconfig",    # ツールの設定 (秘密は deny で個別に塞ぐ)
  "/usr/include",                 # システムヘッダ
  "/usr/local",                   # include / lib / share / cuda をまとめて
  "/usr/src",                     # カーネルヘッダ (DKMS, CUDA ドライバ)
  "/opt",                         # サードパーティのツールチェーン
]
copilot_write_allow = [
  "~/.cache", "~/.npm", "~/.cargo/registry", "~/.local/state",
  "~/.local/share/uv/tools",      # uvx の一時環境
  "~/.config/chezmoi",            # chezmoi の永続 state (boltdb)
]
```

書き込みは**キャッシュ類だけ**。それ以外は read-only にする。書ければ
以後のビルド成果物へ任意コードを混ぜられる。
**存在しないパスを書いても害は無い** (Copilot は実在しないパスをポリシーから
落とし `/sandbox policy` の Notes に記載するだけ)。
Claude は `denyRead` が `~/` 配下だけなので `/usr` や `/opt` は元から読める。

> [!CAUTION]
> **同じパスを read と write の両方に書いてはいけない。**
> sandbox 実装は同一パスの RO/RW 競合を「最も制限的な意図」= RO へ解決する
> ため、**write 指定が無言で消える**。これが上記 2 の不具合の本体で、
> ユーザ指定どうしでも同じことが起きる。
> write 権限は read を含むので、書きたい場所は `copilot_write_allow` にだけ
> 書く (`~/.cache` `~/.npm` がこれに当たる)。
> `build_copilot_sandbox` が重複を検出して apply を止める。
>
> 親子関係 (`~/.local` と `~/.local/state`) は
> 「より具体的なパスが勝つ」規則で解決されるので問題ない。

書き込みを許す場所の選び方にも注意が要る。

> [!WARNING]
> **`~/.local/share/mise` を `copilot_write_allow` に入れてはいけない。**
> PATH 上の全ツールが書き換え可能になり、`git` や `python` を差し替えて
> 以後のコマンドを乗っ取る経路ができる。sandbox が防ごうとしている当のもの。
> read だけで `mise exec` は動く。
>
> 対して `~/.local/share/uv/tools` は write に入れてある。**PATH に載らず**
> `uvx <tool>` からしか使われないので質が違う。しかも `~/.cache/uv` が
> rw な時点で uvx 経由のコードは同じ経路で汚染できるため、リスクは増えない。
> RO のままだと `uvx` が一時環境を作れず、pre-commit の ruff / yamllint が
> `Read-only file system (os error 30) at ".../uv/tools/.tmpXXXX"` で落ちる。

判断の基準は **「PATH に載るか」**。載るものは read だけにする。

許可した領域の内側に秘密があるときは、`deny` に個別のパスを書けば
「より具体的なパスが勝つ」規則で遮断される。
`~/.config/chezmoi` は state (boltdb) のために write を与えているが、
同じディレクトリの age 秘密鍵は `deny` で塞いである。

### `/sandbox policy` の表示は実効性を保証しない

上記 2 の不具合で分かったことだが、**`/sandbox policy` が Read-write と
表示していても、実際には read-only で bind されていることがある**。
sandbox 実装は同一パスに RO と RW が来たとき「最も制限的な意図」として
RO を採り、その解決は出所 (ユーザ指定 / 自動発見) を区別しない。

権限を疑ったときは表示ではなく mount を見る。

```bash
findmnt -T ~/.cache/uv -o TARGET,SOURCE,OPTIONS
```

### PATH 上のディレクトリは read-only で固定される (dev-tool access が ON のとき)

> [!NOTE]
> この節は `copilot_allow_dev_tool_access = true` のときの挙動。
> 現在は `false` にしているので、この自動付与は起きない。
> 他マシンや既定設定でこの症状に当たったときのために残してある。

`allowDevToolAccess` は `PATH` に載っているディレクトリを **read-only で
bind-mount** する。公式の意図は
"a command needs to run `git`, not modify it" で、実行ファイルの置き場を
改竄から守るもの。**保護されるのは PATH に載っているディレクトリそのもの**で、
その親は関係ない (mise なら `installs/<tool>/<版>` は rw、その下の `bin` だけが
RO。[実測](../../research/agents/copilot-dev-tool-access-grants.md#3-path-上のディレクトリは-read-only))。

このため `mise install --force` は、使用中のツールの `bin/` を消そうとして
`Read-only file system (os error 30)` で失敗する。sandbox の外で
ディレクトリごと消してから入れ直すこと。

### bind-mount は symlink を「実体」に置き換える

ディレクトリを bind-mount する副作用として、
**そのパスが symlink だとビューから消える**。bind-mount は symlink を辿った
先を貼るので、リンクそのものはマウント後の名前空間に存在しない。

mise はツールごとに `<tool>/latest` という symlink を作り、PATH には
`<tool>/latest/bin` を載せる。この結果:

```text
ホスト        : installs/node/{24.5.0, latest -> 24.5.0}
sandbox 内    : installs/node/{24.5.0}          ← latest が消える
PATH          : .../node/latest/bin             ← 解決できない
結果          : node: not found
```

`node` が消えると、shebang で node を呼ぶ npm 製ツール
(`markdownlint-cli2` など) が軒並み動かなくなる。`npx` も同じ理由で消える。
同じ現象は `/bin` `/lib` `/sbin` でも起きている。

**対処は親ディレクトリごと許可すること。** 親を許可した領域は bind-mount では
なく素通しになり、中の symlink はリンクのまま見える
([実測](../../research/agents/copilot-dev-tool-access-grants.md#4-mise-の-latest-symlink-が消える))。
`copilot_read_allow` が
`~/.local/share/mise/installs` ではなく **`~/.local` ごと** 許可しているのは
この理由による。

> [!NOTE]
> 「symlink が一律に消える」わけではない。消えるのは
> **bind-mount の対象になったパス自身**だけ。

### 機構の境界 (どこに書くか)

置き場所は **「誰が強制できるか」** で決める
([ADR-0007](../../adr/0007-filesystem-guard-boundary.md))。

| 表現したいもの | 置き場所 | 効く CLI |
| --- | --- | --- |
| 絶対パス・ワイルドカード無しの遮断 | `[sandbox] deny` | Claude・Copilot (OS レベル) |
| glob / cwd 相対 / 意味論を含む遮断 | hook | Claude・Copilot |
| CLI ごとに書き方が違う**許可** | `claude_*` / `copilot_*` | 片方ずつ |

規則は 1 つだけ覚えればよい。

> **CLI 固有キーに「禁止」を置かない。** 許可にだけ使う。

許可の非対称は実効ポリシーを揃えるためのもので安全側に働くが、
禁止の非対称はそのまま穴になる。実際、`[file] read_deny_globs` は
Claude の `Read()` deny にしかならず、**リポジトリ内に置かれた秘密ファイルが
Copilot からは読める**状態だった。現在は `check_file_read.py` が同じリストを
読んで Copilot 側を埋めている。

| 防御 | Claude | Copilot |
| --- | --- | --- |
| ホーム配下の秘密 | `[sandbox] deny` | 同左 |
| リポジトリ内の秘密 (glob) | `Read()` deny permission | `check_file_read.py` hook |
| bash 経由のアクセス | `check_bash.py` hook | 同左 |

`check_file_read.py` を Claude に付けないのは、permission が同じリストから
生成済みで防御が増えないうえ、**全ファイル読み取りに Python のプロセス起動が
乗る**ため (ADR-0004 の実測で hook 1 回あたり 110ms)。

### プロジェクト側の設定で `deny` を打ち消せるか

**打ち消せない。** ただし層ごとに理由が違う。

| 層 | プロジェクト設定からの上書き | 根拠 |
| --- | --- | --- |
| sandbox | **不可** | Claude は配列がスコープをまたいで**結合**され削除手段が無い。Copilot はリポジトリ設定に `sandbox` を許していない |
| permission (Claude) | **不可** | 「deny → ask → allow の順に評価し、**最初に一致したものが結果を決める**」 |
| hook (`preToolUse`) | **不可** | 「**いずれかの hook が deny を返せばブロック**」 |

> [!WARNING]
> **`permissionRequest` は別物。** この event だけは
> 「後の hook 出力が前を上書きする」と定義され、読み込み順は
> policy → user → **project** → plugins。リポジトリ側の hook が user の決定を
> 上書きできる。このリポジトリが `preToolUse` しか使っていないのは意図的で、
> **`permissionRequest` に移してはいけない** (test で固定)。

### 残る非対称

`claude_network_*` だけが残る。Copilot にドメイン単位の制御が無く
(`allowOutbound` の on/off だけ)、hook でも代替できない。

`[sandbox] deny` の実効性は実測済み。deny 配下のディレクトリは
**空の tmpfs として見える** (エントリ数 0) ので、`ls` は成功するが中身は
一切取れない。

Claude・Copilot とも **whitelist (deny-by-default)** で揃えてある。Copilot は元から
その方式で、Claude は `denyRead` に `~/` を置き `allowRead` で穴を開けることで
同じ形にしている (公式ドキュメントに構成例あり)。書き込み側は両者とも元から
whitelist (cwd + セッション temp + 明示許可のみ)。

`common.toml` の `[sandbox]` に書くパスは、permission の `Read()`/`Edit()`
glob 記法とは **書式が異なる**:

- `~/` 始まりで home からの相対、`/` 始まりで絶対、無印/`./` はプロジェクト
  相対 (ただし **user 設定 `~/.claude/settings.json` では無印/`./` は
  `~/.claude` 基準になる**)。ホーム全体に効かせたいパターンは必ず `~/` を
  明示すること。
- `deny` (Claude・Copilot 共通): whitelist の内側でも遮断する秘密情報。read/write 両方。
  公式に "Rules that you configure are always kept" とあり自動付与に勝つ。
- `claude_read_allow` (Claude のみ): whitelist に開ける読み取りの穴。
  ツールチェーン (`~/.local` `~/.cache` `~/.cargo` 等) と skill 置き場のみ。
- `claude_write_allow` (Claude のみ): cwd + temp 以外に書き込みを許す場所
  (パッケージマネージャのキャッシュ)。
- `claude_write_deny` (Claude のみ): read は許すが write を禁止する対象
  (hook/permission 設定の改竄防止、シェル起動ファイル、認証ファイル)。
- `.git/config` / `.git/hooks` はリポジトリ相対のパスなので `common.toml` には
  書けないが、**Claude sandbox の "Protected paths" が常時保護している**
  (`allowWrite` や `Edit` 許可ルールでも解除できない)。同じく cwd 配下の
  シェル起動ファイル・`.gitconfig`・`.claude/**`・`.mcp.json`、および
  `~/.claude` のほとんどと `~/.claude.json` も自動で write 保護される。
  Copilot 側は cwd 外に書けないこと自体が保護になる。
  hook の `check_guard_tampering` は、sandbox の外で動く操作
  (承認済みの unsandboxed コマンドなど) 向けの二重化として残す。

### なぜ Claude 専用キーが残るのか (whitelist に揃えた後も)

モデルを揃えても、次の 2 点は **機構の差**として残るため Copilot には渡さない:

| キー | Copilot に渡さない理由 |
| --- | --- |
| `claude_read_allow` / `claude_write_allow` | Copilot は同じ役割を `copilot_read_allow` / `copilot_write_allow` が担う。内容はほぼ同じだが、ホーム外 (`/usr` `/opt`) の扱いが違う (Claude は `denyRead` が `~/` 配下だけなので元から読める) ので別キーにしてある |
| `claude_write_deny` | Copilot は cwd の外に**そもそも書けない**ので、改竄防止の deny を足す意味が無い |

つまり「Claude 専用」は *方針の差ではなく実装の差*。両者の**実効ポリシーは
揃っている**必要がある。

> [!IMPORTANT]
> 運用方針は Copilot が緩め、Claude は制約のある環境（許可の最小化が求められる、など）でも
> 使えるよう厳し目。
> `claude_read_allow` を安易に広げると **Claude の方が緩くなり方針が逆転する**。
> 実測した Copilot の実効ポリシーには `$HOME` 配下の作業ディレクトリ許可は
> 無く、skill も `~/.agents/skills` と `~/.claude/skills` だけが出る。
> そのため `claude_read_allow` にも `~/src` のような他リポジトリや、
> AI CLI の設定ディレクトリ全体 (`~/.claude` 等) を入れない
> (`test_read_allow_does_not_open_other_repositories` 他で固定)。
> 作業中のプロジェクトは cwd として自動で読み書きが許可されるので不要。
> 別ディレクトリが要るときは `claude --add-dir <path>`、恒久的に必要なら
> `~/.config/agents/local.toml` を使う。

`~/.config` は丸ごと開けているため、その中の秘密 (`sops/age`,
`gh/hosts.yml`, `Bitwarden CLI`) は `deny` で個別に塞いでいる
(`test_secret_config_dirs_are_denied_even_though_config_is_allowed`)。

### なぜ広い名前マッチを deny に置かないか

Claude の Linux sandbox は **deny 対象の各パスに `/dev/null` を bind-mount
する**実装。そのため `~/**/*secret*` のような名前マッチを deny に書くと
展開結果の数だけ mount が必要になる。この環境の `$HOME` では deny 全体が
数千件に展開され、コマンド 1 回ごとの mount として実用に耐えなかった
([展開数の実測](../../research/agents/claude-deny-glob-expansion.md))。さらに deny 対象が
**symlink を経由すると bwrap のセットアップごと失敗**し、全 sandbox コマンドが
動かなくなる既知の不具合がある ([anthropics/claude-code#45451][cc-45451])。
whitelist なら deny は `~/` の 1 本で済み、どちらの問題も起きない。
この不変条件は `test_deny_has_no_broad_name_globs` で固定している。

[cc-45451]: https://github.com/anthropics/claude-code/issues/45451

### symlink の扱い

sandbox は **symlink で許可範囲を広げることも deny を回避することもできない**。
bwrap は mount namespace で隔離するため、許可されていないパスは sandbox 内に
存在せず、そこへ張った symlink を辿っても `ENOENT` になる。macOS の Seatbelt も
解決後のパスで判定する。Copilot も tool permission 層について
"The match resolves symlinks and `.`/`..` segments" と明記している。

→ 大きなデータセット等を使わせたい場合は、プロジェクト配下に symlink を張る
のではなく **実パス (`/data1` 等) を明示的に許可**すること。利便性のための
symlink は張ってもよいが、許可は実パスに与える必要がある。

sandbox は `sandbox.enabled = true` のみを設定し、`autoAllowBashIfSandboxed`
等の承認モードには触れない。既存の承認フロー (`permissions.defaultMode`) は
変えず、sandbox は純粋に追加の防御層として働く (副作用を最小化するため)。
