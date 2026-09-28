# AI CLI の sandbox (Claude Code / Copilot CLI)

Claude Code / Copilot CLI の sandbox 層 (`[sandbox]`) とネットワーク層、
マシン固有の許可の足し方をまとめる。
全体像は [AI CLI 統合 permission / hook 管理](agent-permissions.md)、
OpenCode の隔離起動 (`ocs`) は [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md)
が正本。

## sandbox 層 (`[sandbox]`)

> [!NOTE]
> `[sandbox]` が扱うのは**パスのポリシー**だけで、sandbox が起動できること自体は
> ホスト側の前提条件になる。Linux の bubblewrap backend は `bwrap` /
> `slirp4netns` / `unshare` / `nsenter` / `iptables` などを probe し、1 つでも
> 欠けると**起動を拒否して全ツールが失敗する**。症状と一覧は
> [Linux で sandbox がコマンドを 1 つも実行できない](troubleshooting-agents.md#linux-で-sandbox-がコマンドを-1-つも実行できない)
> を参照。

### なぜ既定が逆なのに揃えるのか

**既定は実際に逆向き**である。Claude は「read はほぼ全許可 + deny を引く」
ブラックリスト、Copilot は deny-by-default のホワイトリスト。
それでも揃えているのは次の理由による。

1. **Claude の既定が緩すぎる。** 公式が
   「この既定では `~/.aws/credentials` や `~/.ssh/` も読める」と明記している。
   何もしなければ Copilot より明確に緩くなり、
   「Copilot が家用で緩め、Claude が会社用で厳し目」という運用方針が逆転する
2. **ブラックリストは fail-open。** 列挙し忘れた秘密は黙って読める。
   ホワイトリストは fail-closed で、新しいツールが動かなくなる形で
   気付ける。**壊れ方が見える側**を選んでいる
3. **公式に支持された構成。** `denyRead: ["~/"]` + `allowRead` は
   Anthropic のドキュメントが例示している形で、回避策ではない

コストは `claude_read_allow` のパスを手で維持していること。
Copilot 側も `copilot_read_allow` で同じものを列挙する。以前は
`allowDevToolAccess` が自動で行っていたが、不具合のため切っている
([ADR-0008](../adr/0008-explicit-dev-tool-grants.md))。

> [!NOTE]
> 揃えているのは **filesystem だけ**。network は Copilot にドメイン単位の
> 制御が無く、`allowedUrls` も「プロンプトを省略する URL」であって制限では
> ないため、**実効ポリシーを揃えられない**。
> 層ごとの方式の違いは
> [sandbox機能の包括調査](../research/agents/sandbox-capabilities.md) を参照。

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

実測の状況:

- **Claude**: 設定の実測（2026-09-23、`~/.claude/settings.json`）では、
  `/mnt` `/tmp` 系への指定は無い。

  ```text
  Claude の denyRead に /mnt・/tmp 系: なし
  Claude の allowRead に /mnt・/tmp 系: なし
  ```

  sandbox 内から実際に読めるかは Claude では
  **未検証**。OpenCode 側では `srt` のころに実測で `/mnt/c/Users` まで読めることを確認して塞いだ
  （[CHG-0004](../change/closed/0004-opencode-sandbox.md)、
  [調査記録 21 節](../research/opencode/permission/sandbox-runtime.md)）。
  今の `ocs`（Fence）は読める場所を並べる形なので、`/mnt` は開けない限り見えない。
  **Claude には同じ対処を入れていない**
- **Copilot**: `copilot_*` の許可を足す前の `/sandbox policy`（2026-09-13）では、
  `/mnt` は `/mnt/wsl/resolv.conf` だけが read-only、一時領域は `$TMPDIR` だけが
  read-write で、`/tmp` `/var/tmp` `/dev/shm` は一覧に無かった
  （[既定の許可範囲の実測](../research/agents/copilot-sandbox-default-policy.md)）。
  このリポジトリでは `TMPDIR` をリポジトリ直下の `.tmp` に向けている。
  現在の設定（`allowDevToolAccess = false` と `copilot_*` の許可）での表示と、
  `TMPDIR` が `/tmp` のままのマシンでの扱いは**未検証**

未決の点と、決めるときの注意:

- 意図的に開けているのであれば、その旨をここに書いて確定させる
- 意図していないなら `[sandbox] deny` に `/mnt` `/tmp` `/var/tmp` `/dev/shm`
  を足す。**ただし `deny` は Copilot の `deniedPaths` にも流れる**ので、
  Claude と Copilot の両方への影響を確かめてから入れる
- `/tmp` を塞ぐと専用の空 tmpfs になり、ホストとのファイル受け渡しが切れる

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
| `[sandbox] shell_network_allow` | Claude・OpenCode の隔離起動 (`ocs`) | shell が実際に通信する先 (CDN 等) |
| `[sandbox] claude_network_strict` | Claude | 許可外ドメインを拒否する (v2.1.219+) |
| `[sandbox] copilot_read_allow` | Copilot | Copilot が読める場所 (whitelist の本体) |
| `[sandbox] copilot_write_allow` | Copilot | 同上の書き込み |
| `[sandbox] copilot_allow_dev_tool_access` | Copilot | 開発ツール自動許可 (開発ツールの置き場へ sandbox の読み書きの許可を自動で足す)。`false` 固定 |
| `[file] claude_read_allow` | Claude | `Read()` の allow |
| `[file] read_ask_globs` / `write_ask_globs` / `read_deny_globs` / `write_deny_globs` | Claude・OpenCode (Copilot は `read_deny_globs` のみ) | Claude の `Read()` / `Edit()`、OpenCode の `read` / `edit` の ask / deny。Copilot は `check_file_read.py` が view へ適用 |
| `[bash] allow` / `ask` / `deny` | Claude・Copilot | ただし粒度が違う |

**新しく足すキー**では、無印は「Claude と Copilot の両方に効く」を意味する。
**片方にしか渡らない設定を無印で足してはいけない。** `[sandbox]` の既存の
`seccomp_apply_path`（Claude のみ）と `shell_network_allow`（Claude と `ocs`）は
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
(`see docs/spec/agent-sandbox.md 「<見出し>」`) だけを残す。制約と短い理由は
この文書の該当節へ、**実測値**と**何が壊れたかの経過**は `docs/research/` へ書いて
該当節からリンクする ([コメントの書き分け](agent-config-generation.md#コメントの書き分け))。
`test/agents/test_generate_sandbox.py` に、そのパスが期待どおりの権限で
生成されることと、**write を与えていない**ことを固定する。

> [!IMPORTANT]
> **禁止 (deny) をこの手順で足さないこと。** CLI 固有キーは許可の補償専用で、
> 禁止を置くと片方だけ無防備になる。遮断は `[sandbox] deny` (Claude・Copilot 共通) か
> hook で行う。境界は [ADR-0007](../adr/0007-filesystem-guard-boundary.md)。

### Copilot が読み書きできる場所 (`copilot_read_allow` / `copilot_write_allow`)

Copilot の filesystem は deny-by-default なので、このリストが
**Copilot に見える範囲そのもの**になる。以前は `allowDevToolAccess` が
`PATH` 上のツールやキャッシュを自動で許可していたが、
**この自動付与は切ってある** ([ADR-0008](../adr/0008-explicit-dev-tool-grants.md))。

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
(実測は [開発ツール自動許可の実効権限](../research/agents/copilot-dev-tool-access-grants.md))。

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
RO。[実測](../research/agents/copilot-dev-tool-access-grants.md#3-path-上のディレクトリは-read-only))。

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
([実測](../research/agents/copilot-dev-tool-access-grants.md#4-mise-の-latest-symlink-が消える))。
`copilot_read_allow` が
`~/.local/share/mise/installs` ではなく **`~/.local` ごと** 許可しているのは
この理由による。

> [!NOTE]
> 「symlink が一律に消える」わけではない。消えるのは
> **bind-mount の対象になったパス自身**だけ。

### 機構の境界 (どこに書くか)

置き場所は **「誰が強制できるか」** で決める
([ADR-0007](../adr/0007-filesystem-guard-boundary.md))。

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
> 運用方針は Copilot が家用で緩め、Claude が会社用で厳し目。
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
([展開数の実測](../research/agents/claude-deny-glob-expansion.md))。さらに deny 対象が
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

## ネットワーク層 (`[web]` → `sandbox.network`)

ファイル層と違い、**ネットワークは Claude と Copilot で足並みを揃えられない**。

| | Claude | Copilot |
| --- | --- | --- |
| 粒度 | **ドメイン単位** (`allowedDomains` / `deniedDomains`) | **on/off のみ** (`allowOutbound` / `allowLocalNetwork`) |
| 強制方法 | sandbox 外のプロキシ。全サブプロセスに適用 | OS レベル |
| 許可外の扱い | **承認プロンプト** (既定) | 単純に不可 |

`common.toml` の `[web] allow_domains` (WebFetch 用のドキュメントサイト) と
`[sandbox] shell_network_allow` (shell が実際に通信する CDN 等) を合算したものが
Claude の `sandbox.network.allowedDomains` になり、`deny_domains` は
`deniedDomains` に反映される。2 つに分けているのは役割が違うため:
前者を増やすと WebFetch の自動承認が広がり、後者を増やすと shell の通信先が
広がる (`test_network_allow_is_disjoint_from_web_allow_domains` で混在を検出)。

なお Claude は `WebFetch(domain:...)` の許可ルールからも sandbox の allowlist を
組み立てるため前者は実質二重だが、permission 側の記法が変わっても sandbox の
許可が崩れないよう明示的に出している。

> [!WARNING]
> **sandbox に効く wildcard は先頭の `*.` と単独の `*` だけ**。
> `example.*` のように他の位置に置いた wildcard は `WebFetch` には効くが
> sandbox 側は無視するため、穴が開いたつもりで開いていない状態になる
> (`test_web_wildcards_are_sandbox_compatible` で固定)。

### ネットワークも whitelist にしてある (Claude のみ)

`[sandbox] claude_network_strict = true` から `sandbox.network.strictAllowlist` を
立てており、**許可外ドメインへの接続は拒否される** (Claude Code v2.1.219 以降が
必要)。これが無いと許可外は拒否ではなく**承認プロンプト**になる。

許可漏れがあっても即座に破綻はしない。sandbox 内で接続が失敗し、
「sandbox 外での再実行」を求める承認プロンプトに落ちるだけなので、
足りないドメインが判明したら `shell_network_allow` に追記すればよい。

**Copilot 側は outbound が全ドメイン許可のまま**で、これは変えられない
(ドメイン単位の設定が存在しないため)。`allowedUrls` は公式に
"URLs or domains allowed without prompting" とあるとおり**承認プロンプトの
省略リスト**であって通信制限ではなく、sandbox 内の `curl` は任意のホストへ
到達できる。結果としてネットワークは Claude (会社用・厳しめ) と
Copilot (家用・緩め) で非対称なままになるが、これは運用方針とは一致している。

### 資格情報を sandbox 側で落とす (`sandbox.credentials`)

Claude Code v2.1.187 以降では `sandbox.credentials` で、sandbox 内の
環境変数を unset する (`deny`) か、値を伏せたままツールを動かす (`mask`)
ことができる。`check_secret_env_echo` や `check_gh_token_exposure` の一部を
肩代わりできるが、`mask` は TLS 終端 (`network.tlsTerminate`) を要求し
プロキシに平文を見せることになるため、導入は別途検討する (現在は未使用)。

### WSL2 での抜け穴 (seccomp フィルタ)

WSL2 では Windows バイナリ (`cmd.exe`, `/mnt/c/...`) の起動が Unix domain
socket 経由になるため、**seccomp フィルタが無いと sandbox から脱出できる**
(公式: "the optional seccomp filter has to be installed to block the socket
in the first place")。未導入だと Claude は
`[Sandbox Linux] apply-seccomp binary not available - unix socket blocking
disabled.` を出す。

このリポジトリでは **mise で導入し、パスを settings.json で教える**方式を
取っている。`npm install -g` は `[bash] deny` で禁止しているため使わない。

- `home/dot_config/mise/config.toml.tmpl` の
  `"npm:@anthropic-ai/sandbox-runtime"` が本体を入れる。
- `common.toml` の `[sandbox] seccomp_apply_path` が導入先を指し、
  `generate.py` が `sandbox.seccomp.applyPath` を生成する。

> [!IMPORTANT]
> **mise に書くだけでは効かない。** Claude が `apply-seccomp` を自動検出するのは
> npm のグローバル領域だけである:
>
> - npm グローバル prefix (`npm -g config get prefix`) 配下の `lib/node_modules`
> - `/usr/lib` / `/usr/local/lib` / `/opt/homebrew/lib` の `node_modules`
>
> mise の `npm:` バックエンドはパッケージを
> `~/.local/share/mise/installs/npm-.../` へ**隔離**するため、上記のどこにも
> 現れない (実機で npm prefix 配下の `@anthropic-ai/` が空のままになることを
> 確認済み)。そこで公式が用意している代替手段
> 「copy `vendor/seccomp/*` from sandbox-runtime and set
> `sandbox.seccomp.bpfPath` and `applyPath` in settings.json」を使い、
> **コピーの代わりに mise の導入先を直接指している**。

`seccomp_apply_path` の `{arch}` は `generate.py` が `x64` / `arm64` に
置換する。バージョン更新に追従するよう mise の `latest` エイリアスを経由し、
**パスが実在するときだけ**設定を出力する (未導入のマシンや非対応
アーキテクチャでは設定が出ず、Claude は従来どおり自動検出に戻るだけ)。

導入後は `/sandbox` の Dependencies タブに不足が出ていないことを確認する。

> [!NOTE]
> **版は固定していない。** `sandbox-runtime` は research preview で、
> README が「API と設定フォーマットは変わりうる」と明記している。
> `latest` 経由で Claude に効く（OpenCode の `ocs` は Fence に替えた。
> [OpenCode 隔離起動のアーキテクチャ](opencode-sandbox.md#版の扱い)）。
> 更新時は「拒否すべきものが拒否される」ことを確かめる（deny・直接通信・
> Unix socket・cwd 違い・並行実行）。Claude 側は `applyPath` が実在しなくなると**設定が出力されず自動検出へ戻る**
> ため、seccomp が黙って無効化されうる。

### sandbox に移せないネットワーク系チェック

以下は「どのドメインに繋ぐか」では表現できないため hook に残す:

| チェック | 残す理由 |
| --- | --- |
| `check_reverse_shell` | `/dev/tcp`・`nc -e`・待ち受けソケット。ドメイン許可の話ではない |
| `check_pipe_to_shell` | `curl \| sh` は**許可済みドメイン**でも成立する |
| `check_curl_file_send` | 許可済みドメインへの外部送信は sandbox では止まらない |
| `check_pip_redirect` | uv に統一するという**ポリシー**であってセキュリティではない |
| `check_gh_api_*` | GitHub API の意味解釈が必要 |

逆に `check_http_dangerous_output` (`curl` でシェル起動ファイルを上書き) は
[残る非対称](#残る非対称) の Protected paths と `denyWrite` で**完全に冗長**になっている。

## このマシンだけで許可を足す (chezmoi 管理に影響を与えない)

データセット置き場 (`/data1`) や外部マウントなど、**このマシンでしか意味が
無いパス**を共有の `common.toml` に書きたくない場合の手段。共有設定を汚さず、
`chezmoi diff` にも出ない方法が CLI ごとに用意してある。

> [!IMPORTANT]
> `~/.claude/settings.json` の `sandbox` キーを直接編集しても無駄。
> `chezmoi apply` のたびに `generate.py` が丸ごと生成し直すため上書きされる。
> `~/.copilot/settings.json` も `deniedPaths` だけは同様に再生成される。

### 1. `~/.config/agents/local.toml` (両 CLI・マシン全体)

`generate.py` は起動時にこのファイルがあれば読み、**追記だけ**を共有設定へ
マージする。chezmoi の管理対象ではないので `chezmoi apply` でも消えず、
`chezmoi diff` にも現れない。

```toml
# ~/.config/agents/local.toml (chezmoi 管理外・このマシン専用)
[sandbox]
claude_read_allow   = ["/data1", "/data2"]   # データセットは read-only で十分
claude_write_allow  = ["/data1/outputs"]     # 書き出し先だけ read-write
copilot_read_allow  = ["/data1", "/data2"]   # Copilot にも要るなら両方書く
copilot_write_allow = ["/data1/outputs"]
deny                = ["/data1/private"]     # 許可した中の一部を塞ぐことも可能

# このマシンの「この案件でだけ」開きたいもの (Copilot)
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

- 反映させるには `chezmoi apply` を実行する (生成時に読まれる)。
- `[sandbox]` で追記できるのは `deny` / `claude_read_allow` /
  `claude_write_allow` / `claude_write_deny` / `copilot_read_allow` /
  `copilot_write_allow` のみ。**共有設定のエントリを消したり緩めたりはできない**
  (`sandbox.enabled = false` のようなキーは無視される)。
- `[[copilot.locations]]` で追記できるのは `path` / `approvals` /
  `allowed_directories`。同じ `path` が共有側にもあれば **union** される。
- **CLI 名の接頭辞を省略できない。** 無印の `read_allow` を書いても黙って
  無視されるため、`generate.py` が stderr に警告を出す。
- パスは実在している必要がある。存在しないパスは bwrap の bind-mount が
  失敗する要因になる。
- `AGENTS_LOCAL_CONFIG` 環境変数でファイルの場所を差し替えられる (テスト用)。
- `~/.config/agents` は `claude_write_deny` に入っているため、**sandbox 内の
  コマンドからは書けない**。エージェントがここに許可を書き足して自分の
  権限を広げることはできない。

### 2. `.claude/settings.local.json` (Claude・プロジェクト単位)

Claude の設定スコープは上から managed → `claude --settings` →
`.claude/settings.local.json` (project local) → `.claude/settings.json`
(shared project) → `~/.claude/settings.json` (user) の 5 段。
**`sandbox.filesystem` の配列はスコープをまたいでマージされる**
(上書きではなく結合) ので、project local に穴だけ書けばよい。
このファイルは Claude 自身が global gitignore に追加するためコミットされない。

```json
{ "sandbox": { "filesystem": { "allowRead": ["/data1"] } } }
```

user スコープに `settings.local.json` は**存在しない**。マシン全体に効かせたい
場合は 1 の `local.toml` を使うこと。

### 3. `[[copilot.locations]] allowed_directories` (Copilot・プロジェクト単位)

Copilot には **作業ディレクトリごと**の追加許可がある。`common.toml` に書くと
`~/.copilot/permissions-config.json` の `locations.<path>.allowed_directories`
へ展開され、そのプロジェクトで作業しているときだけ適用される。

```toml
[[copilot.locations]]
path = "~/src/some-project"
allowed_directories = ["/data1/some-project"]
```

location キーは **Git ルート** (リポジトリ外なら正規化した cwd)。
絶対パスのみで、公式仕様が「適用時に実在すること」を要求するため
`generate.py` が存在しないパスを落とす。**deny は書けない**
(`permissions-config.json` は deny / ask 非対応)。

案件固有のものは共有設定を汚さないよう、`common.toml` ではなく
chezmoi 管理外の `~/.config/agents/local.toml` に同じ書式で書く
(同じ `path` は union される)。

> [!IMPORTANT]
> **設定の実体はプロジェクトの外 (`~/.copilot/`) にある。**
> リポジトリの中に置いて共有することは**できない**。
> Copilot のリポジトリ設定が受け付けるキーは公式に列挙されており、
> `sandbox` も `permissions-config.json` の `locations` も含まれない。
> 許されているのは `deniedUrls` / `disabledMcpServers` のように
> **union で追加するだけ・削除できない** = 締める方向のキーに限られる。

### 4. 対話プロンプトで承認する (Copilot・プロジェクト単位・設定不要)

**実は一番手軽なのはこれ。** Copilot はディレクトリやツールの承認を
`~/.copilot/permissions-config.json` へ**自分で保存する**。公式に
「When you approve a tool or grant access to a directory for the current
location, the CLI records the decision here」とある。

> [!IMPORTANT]
> このファイルは CLI が書き込むため、`generate.py` は **location 単位で
> union** する (全置換しない)。以前は全置換していたため、
> **`chezmoi apply` のたびに対話承認が消えて同じプロンプトが再発する**
> 不具合があった。承認を取り消したいときは CLI を終了してから手で消す。

### 5. `/sandbox config` の TUI (Copilot・マシン全体)

Copilot の `readonlyPaths` / `readwritePaths` は、`generate.py` が既存の値に
`copilot_read_allow` / `copilot_write_allow` を**合算**して書く (既存分は消さない)。
そのため TUI で足した許可はそのまま残る (`chezmoi apply` でも消えない)。
`deniedPaths` だけは共有の `deny` で**置き換え**て再生成する。

### 6. 一時的に 1 セッションだけ

- Claude: `claude --settings '{"sandbox":{"filesystem":{"allowRead":["/data1"]}}}'`
- Copilot: `--add-dir` で作業ディレクトリを足す

> [!NOTE]
> どの方法でも **symlink は許可の手段にならない**。プロジェクト配下に
> `/data1` へのリンクを張っても、許可は実パスに与える必要がある
> ([symlink の扱い](#symlink-の扱い))。

### まとめ: どれを使うか

| 効かせたい範囲 | Claude | Copilot |
| --- | --- | --- |
| **このプロジェクトだけ (まず試す)** | プロンプトで「don't ask again」→ `.claude/settings.local.json` | **プロンプトで承認** → `permissions-config.json` に自動保存 |
| このプロジェクトだけ (共有したい) | `.claude/settings.json` **(リポジトリ内・コミット)** | **不可** |
| このプロジェクトだけ (設定で明示) | `.claude/settings.local.json` | `local.toml` の `[[copilot.locations]]` |
| このマシン全体 | `local.toml` の `[sandbox]` | 同左 |
| 全マシン (共有) | `common.toml` の `claude_*` | `common.toml` の `copilot_*` |
| 1 セッションだけ | `claude --settings` | `--add-dir` |

**まず対話プロンプトで承認すれば足りることが多い。** 設定ファイルを書く必要が
あるのは「無人実行で聞かれたくない」「複数マシンへ配りたい」場合に限られる。

リポジトリの中に許可を置けるのは Claude だけ。Copilot はプロジェクト単位の
スコープを持つが、設定ファイルの実体は常にリポジトリの外にある。

> [!WARNING]
> **Claude の `.claude/settings.json` はコミット対象の共有ファイル**で、
> 公式に「In a git repository, commit it so teammates get it」とある。
> `sandbox.filesystem` の配列はスコープをまたいで結合されるので、
> **信頼していないリポジトリを clone しただけで自分の sandbox が広がりうる**。
> 緩和は `--setting-sources` で project スコープを除外する (v2.1.246+) か、
> managed settings の `allowManagedReadPathsOnly`。
> Copilot はリポジトリ設定に `sandbox` を許していないためこの経路が無い。

## Copilot の sandbox は Claude と別物

Copilot の sandbox 設定は `~/.copilot/settings.json` の `sandbox` キーに入る。
スキーマは公式ドキュメントに記載が無く、実機で `/sandbox` の TUI を操作して
確認したもの (Copilot CLI 1.0.84-5):

```jsonc
"sandbox": {
  "enabled": true,
  "allowBypass": true,          // sandbox 外での実行を都度承認で許可
  "allowDevToolAccess": false,  // 自動許可。ADR-0008 により無効化
  "addCurrentWorkingDirectory": true,
  "sandboxMcpServers": true,
  "sandboxLspServers": true,
  "auth": { "git": true, "gh": true },
  "userPolicy": {
    "filesystem": {
      "readwritePaths": [], "readonlyPaths": [], "deniedPaths": []
    },
    "network": { "allowOutbound": true, "allowLocalNetwork": true }
  }
}
```

Claude との差で特に重要なもの:

- **既定のモデルが逆だった**。Claude の既定は「read 全許可 → deny を引く」
  ブラックリストだが、Copilot は **deny-by-default のホワイトリスト**
  (公式: "The sandbox is deny-by-default: unless a path is explicitly
  granted, a command cannot use it")。
  → このリポジトリでは Claude 側を `denyRead: ["~/"]` + `allowRead` で
  whitelist 化し、**両者のモデルを揃えてある**。
  → Copilot は cwd の外への書き込みがそもそもできないので、
  `claude_write_deny` (改竄防止) に相当する設定は**渡していない**。
- **`claude_read_allow` / `claude_write_allow` を Copilot に渡してはいけない**。
  Copilot 側は `copilot_read_allow` / `copilot_write_allow` が同じ役割を担う。
  内容はほぼ同じだが、ホーム外の扱いと write の範囲が違うため
  生成側が参照するキーを取り違えないことをテストで固定している
  (`test_copilot_sandbox_reads_only_the_copilot_keys`)。
- **ワイルドカード非対応・絶対パス限定** (公式ドキュメントに明記)。
  `deny` に書いた `~/**/.env` のようなパターンは Copilot 側では
  自動的に除外される (`build_copilot_sandbox` が `*` を含む要素を落とす)。
- **`deniedPaths` に read/write の区別が無い**。Claude の
  `denyWrite` 相当 (「改竄防止のため書き込みだけ止めたい」) を
  ここに書くと **read も止まり通常の開発作業が壊れる**:
  `~/.gitconfig` を入れると git が user 情報や include を読めず全 git 操作が
  失敗し、`~/.copilot/hooks` や `~/.config/agents` を入れると hook 自体が
  読めなくなる。よって共通の `deny` には
  **「純粋な秘密情報で、通常の開発で読む必要が無いもの」だけ**を置き、
  write のみ止めたいものは `claude_write_deny` (Claude 専用) に分ける
  (この不変条件は `test_copilot_deny_excludes_read_required_files` で固定)。
- `readonlyPaths` は Claude の `denyWrite` とは**別物**。前者は
  deny-by-default のホワイトリストへの「read 権限の付与」(足し算) で、
  後者は「write 権限の剥奪」(引き算)。ただし重なった場合は
  **より具体的なパスが勝ち、ユーザーが明示した規則は自動付与より優先される**
  ため、広い read/write 付与の内側を `readonlyPaths` で書き込み禁止にする
  使い方はできる (公式の例: `/project` は writable だが
  `/project/secrets` を read-only にするとそこだけ保護される)。
  リポジトリ内の秘密ディレクトリを守りたい場合はこれが使える。
- `~/.ssh` を denied にすると git over SSH は使えなくなるが、
  `auth.git` / `auth.gh` が GitHub 向けトークンを注入するため
  HTTPS 経由の `git` / `gh` は sandbox 内でも動作する。
- sandbox の適用範囲はプロセスによって強度が違う。shell コマンドや
  `grep`/`glob` (ripgrep) は **OS が強制**するが、CLI 内蔵の read/edit
  ツールは同じポリシーを**ソフトウェア的に自己チェックするだけ**
  (OS のバックストップが無い)。リモート MCP には適用されない。

`generate.py` が管理するのは `enabled`・`allowDevToolAccess`・
`userPolicy.filesystem` の 3 リスト。`network` / `allowBypass` / `auth`
といった挙動設定には触れない (家用の緩い運用を壊さないため)。
`readwritePaths` / `readonlyPaths` は `/sandbox config` の TUI から足した分と
`common.toml` の分を **union** する (生成側が手作業の追加を消さない)。

### 実測した既定の許可範囲 (WSL2, chezmoi リポジトリを cwd として `/sandbox policy`)

`copilot_*` の許可を足す前の Copilot が既定で何を許すかを、`/sandbox policy` で
見たもの。表示そのものは
[既定の許可範囲の実測](../research/agents/copilot-sandbox-default-policy.md) にある
(当時は `allowDevToolAccess = true`。現在は `false` で許可も足してあるので、
同じ表示にはならない)。
既定で許可されるのはシステム領域 (read-only)、`$TMPDIR`・cwd・セッション領域
(read-write)、`~/.copilot/logs` と skill 置き場 (read-only) だけだった。

ここから分かること:

- **`$HOME` 直下は一切許可されていない**。`~/.gitconfig` `~/.bashrc`
  `~/.ssh` などは設定を足さなくても既定で触れない。
  `~/.copilot` も `logs` だけが read-only で、`hooks` や `settings.json` は
  許可対象外 = **改竄不能**。
- したがって Copilot 側では `deny` の大半が多重防御 (冗長) であり、
  実際に効くのは `allowDevToolAccess` が拾う可能性のある
  `~/.npmrc` / `~/.pypirc` / `~/.config/gh/hosts.yml` あたり。ただし
  **cwd を `$HOME` にして起動すると home 全体が read-write になる**ため、
  その場合の保険として残してある
  (公式: "Rules that you configure are always kept" なので自動付与に勝つ)。
- `$TMPDIR` が read-write で許可される。このリポジトリでは zsh 側で
  `TMPDIR` をリポジトリ直下 `.tmp` に向けているため
  (`home/dot_zshenv` の `_tmpdir_repo_local_update`)、
  sandbox の一時領域もリポジトリ内に収まる。
- 設定変更は **セッション開始時に読まれる**。`chezmoi apply` 後は
  Copilot を起動し直さないと `/sandbox policy` に反映されない。
- **存在しないパスの deny ルールは黙って無効化される**。未作成の
  `~/.netrc` などは enforce されず、Notes 節に
  `does not exist; it is not enforced by the OS sandbox` と出る。
  → 後からファイルが作られても (例: `npm login` が `~/.npmrc` を作る)
  そのセッション中は deny が効かない。次のセッションからは効く。
  `$HOME` が既定で未許可であるため実害は小さいが、ルールが効いているか
  どうかは **Notes 節を必ず確認する**こと。
  後から作られると困るもの（`~/.local/state/opencode-sandbox`）は、
  chezmoi が apply で先に作っておく（[信頼の鎖](opencode-sandbox.md#信頼の鎖)）。
- `/sandbox policy` は cwd ごとに解決されるため、確認したいディレクトリで
  実行すること。

実効ポリシー (設定 + 自動付与 + 管理ポリシーの合成結果) は Copilot の
セッション内で `/sandbox policy` を実行すると確認できる。
拒否の発生を記録したい場合は **Denial capture** を有効にする。

`/tmp` の read/write を sandbox で全面遮断する案は、zsh 側で
リポジトリ直下 `.tmp` へ `TMPDIR` を向ける仕組みとセットで行う将来タスクで
あり、現時点では対象外 (`executable_redirect-tmp.py` が引き続き担当する)。
