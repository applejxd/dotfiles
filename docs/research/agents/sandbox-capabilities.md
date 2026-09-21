# Claude Code / Copilot CLI の sandbox 機能 (包括調査)

> **調査日時: 2026-09-14 22:00 JST**
> **検証バージョン: Claude Code 2.1.x 系ドキュメント / GitHub Copilot CLI 1.0.84-5**
>
> sandbox は両 CLI とも更新が激しく、公式ドキュメントの記載も追随中。
> 本書を参照する前に必ず[再確認すべき情報源](#10-再確認すべき情報源)を開き、
> 差分を反映してから使うこと。
>
> このリポジトリで実際に採用している設定は
> [エージェント権限仕様](../../spec/agent-permissions.md)、
> 判断の根拠は [ADR-0007](../../adr/0007-filesystem-guard-boundary.md) が正本。
> **本書は「何ができるか」の網羅**であり、「何を採用したか」ではない。

## 0. 本書の用途

`common.toml` に sandbox 設定を足す・見直すときの参照表。

これまで設定を触るたびに「知らなかった機能」が出てきた
(`copilot_read_allow` を作る契機になった uv の取りこぼし、
`permissionRequest` の後勝ちマージ、`allowed_directories` の存在など)。
場当たりの調査を繰り返さないよう、**両 CLI の sandbox が提供する面**を
一度洗い出しておく。

未採用の機能にも「なぜ使っていないか」を書く。次に検討するときの出発点になる。

## 1. 全体像

| 項目 | Claude Code | Copilot CLI |
| --- | --- | --- |
| 既定 | **無効** (`sandbox.enabled` 既定 `false`) | **無効**。`--experimental` か `/experimental on` が前提 |
| 有効化 | `/sandbox` → Mode タブ、または `sandbox.enabled` | `/sandbox enable` |
| 実装 (macOS) | Seatbelt | Seatbelt |
| 実装 (Linux/WSL2) | bubblewrap + socat | bubblewrap (Microsoft MXC backend) |
| Windows | **非対応** (WSL2 を使う) | Windows Insiders ビルドが必要 |
| 設定の置き場 | `settings.json` の `sandbox` キー (5 スコープ) | `~/.copilot/settings.json` の `sandbox` キー (**user のみ**) |
| filesystem | deny ベース (既定は read 全許可) → `denyRead: ["~/"]` で whitelist 化できる | **deny-by-default** の whitelist |
| network | ドメイン allowlist + proxy | on/off のみ (`allowOutbound` / `allowLocalNetwork`) + HTTP proxy |
| 対象 | **Bash とその子プロセスのみ** | bash / 組み込み file・web ツール / MCP / LSP |

最大の非対称は最終行。**Claude の sandbox は Bash しか包まない**。
Read / Edit / Write は permission 層で判断される。一方 Copilot は
組み込みツールも sandbox のポリシーで判定する
(ただし後者は OS 強制ではなくソフトウェアチェック、§4 参照)。

### 1.0 「Copilot は whitelist」はどこまで正しいか

**filesystem だけ**。層ごとに方式が違うので、まとめて whitelist と考えると
事故る。

| 層 | Copilot の方式 |
| --- | --- |
| sandbox の filesystem | **whitelist (deny-by-default)**。公式に "The sandbox is deny-by-default: unless a path is explicitly granted, a command cannot use it" |
| sandbox の network | **whitelist ではない**。`allowOutbound` が既定 `true` で、**全ドメインへ出られる**。ドメイン単位の制御が無い |
| `allowedUrls` | 制限ではなく **「プロンプトを省略する URL」**。ここに無いドメインを拒否する効果は無い (web fetch ツール層) |
| `permissions-config.json` | **allow 専用**。deny / ask を表現できないので、ゲートではなく「承認の保存先」 |

そのうえで filesystem の whitelist も、**自動付与がかなり広い**:

- cwd は read/write、Git リポジトリなら全体を read
- `PATH` 上のディレクトリを read-only (`GOPATH` / `JAVA_HOME` / `PYTHONPATH` も)
- パッケージマネージャのキャッシュ・レジストリ (多くは read-only、一部 read/write)
- macOS はシステム領域を read-only

つまり「明示しない限り触れない」のは**そのとおりだが、明示しなくても
触れる範囲が既定で広い**。実効ポリシーは `/sandbox policy` で確認する。

なお Claude の filesystem は**既定が deny ベース (read はほぼ全許可)**で、
`~/.aws/credentials` も `~/.ssh` も読める。このリポジトリは
`denyRead: ["~/"]` + `allowRead` で **Copilot と同じ whitelist 方式に
揃えている**。両者が同じ形に見えるのは、その明示的な設定の結果であって
既定ではない。

### 1.1 リポジトリ内の設定ファイルで許可を足せるか

結論から言うと **Claude は足せる / Copilot は足せない**。

| | Claude | Copilot |
| --- | --- | --- |
| リポジトリ内のファイルで sandbox の許可を足せるか | **○** | **×** |
| 該当ファイル | `.claude/settings.json` (共有・コミット対象) / `.claude/settings.local.json` (個人・gitignore) | — |
| 合成 | `sandbox.filesystem` の配列は**スコープをまたいで結合**される | — |
| リポジトリ設定が受け付けるキー | ほぼ全部 (下記の例外を除く) | 公式に**列挙**されており `sandbox` は含まれない |

Claude はリポジトリ側から `allowRead` / `allowWrite` / `denyRead` / `denyWrite`
のいずれも足せる。公式ドキュメントも「`.` がプロジェクトルートに解決されるのは
project 設定に置いたときだけ」として、**プロジェクトの `.claude/settings.json`
に置く例**を示している。

```json
{ "sandbox": { "filesystem": { "allowRead": ["/data1"] } } }
```

> [!WARNING]
> **`.claude/settings.json` はコミット対象の共有ファイル**で、公式に
> 「In a git repository, commit it so teammates get it」と書かれている。
> つまり **リポジトリを clone しただけで、自分の sandbox の許可が広がりうる**。
> 信頼していないリポジトリでは注意が要る。
>
> 緩和策は 2 つ。
>
> - `--setting-sources` (CLI) / `settingSources` (Agent SDK) で
>   project スコープを除外すると、その `sandbox.filesystem` エントリ、
>   `Edit` allow ルール、`Read` deny ルールが sandbox の構成から外れる
>   (v2.1.246+)
> - managed settings で `allowManagedReadPathsOnly` / `allowManagedDomainsOnly`
>   を立てると、managed のエントリだけが有効になる

ただし Claude でも **project 設定から書けないキー**がある。いずれも
「書けると防御が外れる」もの:

| キー | project 設定での扱い |
| --- | --- |
| `filesystem.disabled` | 無視 (user / managed / `--settings` のみ) |
| `network.strictAllowlist` | 無視 |
| `credentials` の `mask` エントリ | 無視 (`deny` は有効) |
| `network.tlsTerminate` | 無視 |
| `credentials.allowPlaintextInject` | 無視 |
| `credentials.awsPairs` / `sigv4` | 無視 |
| `allowAppleEvents` | 無視 |

Copilot 側は §3.3 のとおり、リポジトリ設定が受け付けるキーが公式に列挙されて
おり `sandbox` は含まれない。しかも許されているのは
`deniedUrls` / `disabledMcpServers` / `disabledSkills` のように
**union で追加のみ・削除不可** = 締める方向か、`respectGitignore` のような
tighten-only に限られる。**clone しただけで権限が広がらない設計**で、
この点は Claude より厳格。

Copilot でプロジェクト単位に開けたい場合は、sandbox ではなく
`permissions-config.json` の `allowed_directories` を使う (§3.4)。
ただし**ファイルの実体は `~/.copilot/` 側**なので、リポジトリに同梱して
共有することはできない。

## 2. Claude Code

### 2.1 filesystem

| キー | 内容 |
| --- | --- |
| `filesystem.allowWrite` | cwd + セッション temp 以外に書き込みを許す |
| `filesystem.denyWrite` | 書き込みを禁じる |
| `filesystem.denyRead` | 読み取りを禁じる |
| `filesystem.allowRead` | `denyRead` の内側に穴を開ける |
| `filesystem.disabled` | **filesystem 層だけを丸ごと無効化** (network 層は残る) |

- 既定の write は cwd + `--add-dir` + セッション temp。
- **既定の read は「ほぼ全部許可」**。`~/.aws/credentials` も `~/.ssh` も読める。
  これを締めるには `denyRead` か `credentials` を明示的に書く必要がある。
  → このリポジトリが `denyRead: ["~/"]` + `allowRead` で whitelist 化しているのは
  この既定を反転させるため。
- **重なったら「より具体的なパスが勝つ」**。広い allow の内側の deny は生き残る
  (`allowRead: ["~/"]` + `denyRead: ["~/**/.env"]` は期待どおり動く)。
- **配列はスコープをまたいで結合**される (上書きではない)。
  → プロジェクトの `.claude/settings.local.json` に穴だけ書ける。
- パス記法は `/` 絶対、`~/` home 相対、無印/`./` は
  **project 設定ならプロジェクトルート / user 設定なら `~/.claude` 基準**。
  permission の `Read()`/`Edit()` glob (`//path` が絶対) とは**別物**。

#### 未採用: `filesystem.disabled`

network だけ絞りたいとき用。公式が
「shell 起動ファイルや `$PATH` 上の実行ファイル、`~/.claude/settings.json` を
書き換えて自分の権限を広げられる」と明記しており、採用しない。
なお **project 設定からは立てられない** (user / managed / `--settings` のみ)。

### 2.2 Protected paths (設定で解除できない write 保護)

`allowWrite` でも `Edit` allow ルールでも**解除できない**保護。

- cwd とその**上位**: `.claude` の設定ファイル、`.claude/skills` `agents`
  `commands` `hooks`、`.mcp.json`、`.claude/workflows`、`.claude/scheduled_tasks.json`
- cwd のみ: `.bashrc` `.zshrc` 等の起動ファイル、`.gitconfig`、
  `.vscode` `.idea`、`.git` 内の `hooks` と `config`
- cwd を bare リポジトリに変えうるもの: 直下の `HEAD` `objects` `refs`
  (Linux/WSL2 では実行中に出現したものを**削除**する)
- `~/.claude` のほとんど、`~/.claude.json`、`.credentials.json`

→ このリポジトリの `claude_write_deny` はこれと重複する部分が多い。
**多重防御として残している**が、sandbox 外で動く操作向けの保険という位置付け。

### 2.3 credentials (未採用・要検討)

`sandbox.credentials` は**秘密情報専用のブロック**。`filesystem` とは別枠。

| mode | ファイル | 環境変数 |
| --- | --- | --- |
| `deny` | 読み取り禁止 (= `denyRead` と同じ) | sandbox 実行前に **unset** |
| `mask` | **sentinel に差し替えたコピー**を読ませ、proxy が egress で実物へ戻す (Linux/WSL2)。macOS は deny と同じ | 同左 |

`mask` が強力で、`gh` や `npm` を**動かしたまま**トークンを隠せる。

```json
{
  "sandbox": {
    "network": { "tlsTerminate": {}, "allowedDomains": ["*.github.com"] },
    "credentials": {
      "envVars": [
        { "name": "GH_TOKEN", "mode": "mask", "injectHosts": ["api.github.com"] }
      ]
    }
  }
}
```

補助フィールド: `extract` (正規表現の group 1 だけ差し替え。`DATABASE_URL` や
`.netrc` のような構造を持つ値向け)、`decode: "jwt"` (+ `maskClaims`)、
`onExtractNoMatch` (`warn` / `deny` / `error`)、AWS SigV4 の再署名
(`awsPairs` / `sigv4`)。

**本リポジトリは未採用。** 理由:

- `mask` は `network.tlsTerminate` が必須で、proxy が TLS を終端する。
  常時 MITM になるので影響範囲が大きい
- **env の `deny` は `filesystem.disabled` の影響を受けない**ので、
  秘密の環境変数を消す用途だけなら採用価値がある。現状は hook の
  `check_secret_env_echo` が「値が出力・送信される形」を止めているが、
  こちらは**変数そのものを消す**ので迂回耐性は上
- 検討する場合の入口: `GITHUB_TOKEN` / `GH_TOKEN` / `NPM_TOKEN` を
  `envVars` の `deny` に置く。`gh` は sandbox の auth が別途トークンを
  注入するため影響を実測すること

> 公式に「組み込みの credential deny list は無い」と明記されている。
> 書いたものしか守られない。

### 2.4 network

- **既定で許可ドメインはゼロ**。初回アクセス時にプロンプト (auto mode では分類器)。
- `allowedDomains` / `deniedDomains` に加え、**`WebFetch(domain:...)` の
  allow ルールも sandbox の allowlist に合流**する。
- `strictAllowlist: true` で許可外を**拒否**にできる (v2.1.219+)。
  立てないと許可外は拒否ではなく**承認プロンプト**。
  **project 設定に書いても無効**。
- wildcard は**先頭の `*.` と単独の `*` だけ**。`example.*` は WebFetch には
  効くが sandbox は無視する。
- IPv6 は `"[::1]"` のように**角括弧**で書く (v2.1.229+)。
  曖昧な綴りは deny では広く・allow では狭く解釈される。
  `claude doctor` が警告する。
- `httpProxyPort` / `socksProxyPort` で外部 proxy へ寄せられる。
- **既定では TLS を終端しない**。公式が
  「`github.com` のような広いドメインを許すと domain fronting で
  allowlist 外へ到達しうる」と明記。

### 2.5 実行制御

| キー | 既定 | 内容 |
| --- | --- | --- |
| `autoAllowBashIfSandboxed` | `true` | sandbox 内の bash を承認なしで実行 |
| `allowUnsandboxedCommands` | `true` | 失敗時に `dangerouslyDisableSandbox` で外に出る (TUI の「Strict sandbox mode」はこれの反転) |
| `failIfUnavailable` | `false` | 依存が無いとき**起動ごと失敗**させる。既定は警告してサンドボックス無しで続行 |
| `excludedCommands` | `[]` | sandbox の外で動かすコマンド |
| `allowUnixSockets` / `allowAllUnixSockets` | — | Unix ソケットの許可 |
| `allowAppleEvents` | `false` | macOS の Apple Events (`open` / `osascript`) |
| `enableWeakerNestedSandbox` | `false` | 非特権コンテナ内で動かす (`/proc` を bind-mount) |
| `enableWeakerNetworkIsolation` | `false` | MITM proxy + 独自 CA 用 |
| `seccomp.applyPath` | — | Unix ソケット遮断を足す任意フィルタ |

> [!WARNING]
> **`failIfUnavailable` の既定が `false`** なのは重要。
> bubblewrap が入っていない Linux では、警告だけ出して
> **sandbox 無しで普通に動いてしまう**。「有効にしたつもり」が
> 一番危ない。`/sandbox` の Dependencies タブで確認する。

`dangerouslyDisableSandbox` を毎回確認したいなら
`Bash(dangerouslyDisableSandbox:true)` を ask ルールに置く。

### 2.6 組織向け

- `allowManagedReadPathsOnly` / `allowManagedDomainsOnly`:
  配列キーは通常スコープ間で**結合**されるので開発者が広げられる。
  これを立てると managed の値だけが有効になる。
- `excludedCommands` には**同等のロックが無い**。公式が
  「開発者は常に追記できるので managed 側は狭く保て」と明記。

## 3. Copilot CLI

### 3.1 ポリシーの組み立て

**deny-by-default**。明示的に許可されない限り触れない。権限は 3 段階:
read/write、read-only、denied。

自動で付与されるもの:

| 種類 | 内容 |
| --- | --- |
| Include working directory | cwd を read/write。Git リポジトリなら `.git` も。リポジトリ全体は read |
| Allow dev tool access | `PATH` 上のディレクトリを read-only。`GOPATH` / `JAVA_HOME` / `PYTHONPATH` も。パッケージマネージャのキャッシュは「**多くは read-only、一部だけ read/write**」 |
| System / profile (macOS) | システム領域を read-only |

**重なりの解決**: より具体的なパスが勝つ。ただし
「自動付与は、それを包含するより広い read/write 付与に**道を譲る**」。
プロジェクト内の `.venv` が `PATH` に載っていても read-only にならないのはこのため。
**自分で書いたルールは常に保持される** ("Rules that you configure are always kept")。

> [!IMPORTANT]
> 「パッケージマネージャのキャッシュは多くが read-only」が実害を生んだ。
> **uv はこの選別から漏れており** `~/.cache/uv` が read-only、
> `~/.local/share/uv/python` は不可視で、`uv run` が一切通らなかった。
> さらに **システムヘッダも対象外**で、`/usr/lib/x86_64-linux-gnu` が
> 2864 件見えるのに `/usr/include` は ENOENT。cgo / C 拡張のビルドが
> `fatal error: stdlib.h` で落ちる (pre-commit の gitleaks hook が該当)。
> → `copilot_read_allow` / `copilot_write_allow` を新設して補償した。
> 同種の取りこぼしは他のツールでも起こりうる。
> **「PATH 上の実行ファイルと共有ライブラリは通るがヘッダは通らない」**
> のように、自動付与の粒度は直感と一致しない。

取りこぼしより深刻な問題がもう 1 つある。

> [!CAUTION]
> **自動付与はユーザ指定の read-write を上書きする。**
> `~/.cache/uv` を `readwritePaths` に入れても ro で bind され、
> `uv run` が EROFS のままだった。`/sandbox policy` は Read-write と
> 表示するため、**表示からは気付けない**。
>
> sandbox 実装 (`microsoft/mxc` の `normalize_filesystem_paths`) が同一パスの
> RO/RW 競合を「最も制限的な意図」= RO へ解決し、その解決が出所
> (ユーザ指定 / 自動発見) を区別しないことによる。
> 公開 issue は `github/copilot-cli#4846`。
>
> → このリポジトリでは `allowDevToolAccess` を **無効**にし、必要な範囲を
> `copilot_read_allow` / `copilot_write_allow` に明示している
> ([ADR-0008](../../adr/0008-explicit-dev-tool-grants.md))。
> 切ると同じ mount が `rw` に変わることを `findmnt` で確認済み。
>
> 権限を疑うときは表示ではなく mount を見ること:
> `findmnt -T <path> -o TARGET,SOURCE,OPTIONS`

### 3.2 設定キー

`~/.copilot/settings.json` の `sandbox` 以下:

| キー | 既定 | 内容 |
| --- | --- | --- |
| `enabled` | `false` | 有効化 |
| `allowBypass` | `true` | 個別コマンドの sandbox 脱出を要求できる |
| `allowDevToolAccess` | `true` | 開発ツールの自動許可。**当リポジトリでは `false`** (ADR-0008) |
| `sandboxMcpServers` | `true` | MCP サーバも sandbox 内で動かす |
| `sandboxLspServers` | `true` | LSP サーバも同様 |
| `auth.git` / `auth.gh` | `true` | 認証情報を注入して sandbox 内でも git / gh を通す |
| `allowKeychainAccess` | `false` | macOS のみ |
| `userPolicy.filesystem.readwritePaths` | `[]` | 追加の read/write |
| `userPolicy.filesystem.readonlyPaths` | `[]` | 追加の read-only |
| `userPolicy.filesystem.deniedPaths` | `[]` | 遮断 |
| `userPolicy.network.allowOutbound` | `true` | 外向き通信 |
| `userPolicy.network.allowLocalNetwork` | `true` | localhost / LAN |
| `network.proxy` | — | HTTP proxy (Linux/macOS は**協調的**、Windows は強制) |

パス指定は **絶対パスのみ・ワイルドカード非対応**。
**存在しないパスは黙って無効化**され、`/sandbox policy` の Notes に出る。

### 3.3 スコープ

| スコープ | 場所 | sandbox を書けるか |
| --- | --- | --- |
| MDM managed | — | ○ (各値が**下限**になり緩められない。`failIfUnavailable` は管理者専用) |
| User | `~/.copilot/settings.json` | ○ |
| Repository | `.github/copilot/settings.json` | **×** |
| Local | `.github/copilot/settings.local.json` | **×** |

リポジトリ設定が受け付けるキーは公式に列挙されており
(`companyAnnouncements` `contextTier` `deniedUrls` `disableAllHooks`
`disabledMcpServers` `disabledSkills` `effortLevel` `enabledPlugins`
`extraKnownMarketplaces` `hooks` `includeCoAuthoredBy` `mergeStrategy`
`model` `respectGitignore`)、**`sandbox` は含まれない**。
しかも許されているものは `deniedUrls` / `disabledMcpServers` のように
**union で追加のみ・削除不可** = 締める方向か、`respectGitignore` のような
tighten-only に限られる。クローンしただけで権限が広がらない設計。

### 3.4 プロジェクト単位の許可

sandbox ではなく `~/.copilot/permissions-config.json` の
`locations.<path>.allowed_directories` が担当する。

- キーは **Git ルート** (リポジトリ外なら正規化した cwd)。
  linked worktree は本体へ解決、submodule は自身の作業ディレクトリ
- 絶対パスのみ。**適用時に実在しないと弾かれる**
- **deny は書けない** (`permissions-config.json` は deny / ask 非対応)
- これは *path gate* の許可であって sandbox の許可ではない。
  sandbox 側で遮断されていれば開かない

### 3.5 Linux の依存

`network.enforcementMode = "firewall"` のとき、bubblewrap backend が probe する。

| 実行ファイル | パッケージ |
| --- | --- |
| `bwrap` | `bubblewrap` (0.5.0+、一部モードは 0.8+) |
| `slirp4netns` | `slirp4netns` |
| `unshare` / `nsenter` | `util-linux` |
| `iptables` / `ip6tables` + 各 restore | `iptables` |

**1 つでも欠けると起動を拒否**し、bash だけでなく ripgrep を使う
`grep` / `glob` まで全滅する。不足は 1 つずつしか報告されない。
加えて iptables は **nft バックエンド**が要り (legacy は `/run/xtables.lock` に
root が必要)、`nf_conntrack` 未ロードは `Invalid argument` としか出ない。

→ [トラブルシューティング](../../spec/troubleshooting.md) の項目 9 に対処を記載。

## 4. 何が sandbox の中で動くのか

| 対象 | Claude | Copilot |
| --- | --- | --- |
| bash / シェルコマンド | ○ (OS 強制) | ○ (OS 強制) |
| 組み込みの grep / glob | permission 層 | ○ (ripgrep を子プロセスとして起動) |
| 組み込みの file read / edit | **permission 層のみ** | **ソフトウェアチェック** (OS は関与しない) |
| MCP (ローカル) | — | ○ (`sandboxMcpServers`) |
| LSP | — | ○ (`sandboxLspServers`) |
| MCP (リモート) | × | × |
| サブエージェント | 呼ぶツール次第 | 呼ぶツール次第 |
| `!` シェルモードの手入力 | 原則 sandbox 外 | — |

> [!IMPORTANT]
> Copilot の組み込み file ツールは**ソフトウェアチェック**であり
> 「OS の backstop が無い」と公式に明記されている。
> つまり CLI 本体のバグでチェックを抜けると OS は止めてくれない。
> 一方 Claude の Read / Edit は sandbox を**通らず** permission 層だけで
> 判断される。どちらも「file ツールは OS 強制ではない」点は共通。

## 5. 実測で分かった挙動

このリポジトリで実測 (Copilot CLI 1.0.84-5, Linux):

| 観測 | 意味 |
| --- | --- |
| deny ディレクトリは `ls` が**成功して 0 件** | 空の tmpfs がマウントされる。`Path.exists()` は真を返すので**遮断の判定に使えない** |
| deny 配下のファイルは `ENOENT` | 中身は完全に隠れている |
| deny 指定の**ファイル**は `EACCES` | ファイルとディレクトリで errno が違う |
| 未許可のパスは `ENOENT` | 「存在しない」と区別できない (`~/.gitconfig` が消えて見える) |
| `~/.cache/uv` は `EROFS` | read-only 付与 |

**実効ポリシーの調べ方**: `exists()` ではなく
`os.listdir()` のエントリ数と errno で判定する。`/sandbox policy` が最も確実。

## 6. 共通の落とし穴

1. **既定が無効**。両 CLI とも自分で有効化する必要がある
2. **依存が無くても静かに素通り**する (Claude の `failIfUnavailable` 既定 `false`、
   Copilot は起動拒否なので気付ける)
3. **file ツールは OS 強制ではない**。§4 のとおり
4. **network の allowlist は TLS を見ていない**。広いドメインを許すと
   domain fronting で外へ出られる
5. **wildcard の対応がバラバラ**。Claude は `*.` と `*` のみ、Copilot は非対応
6. **パス記法が permission の glob と違う**。Claude の sandbox は
   `/tmp` が絶対、permission は `//tmp` が絶対
7. **存在しないパスの扱い**。Copilot は黙って無効化、
   Claude は bind-mount 失敗の要因になりうる
8. **symlink は許可の手段にならない**。実パスに許可が要る

## 7. このリポジトリの採用状況

| 機能 | 採用 | 備考 |
| --- | --- | --- |
| Claude `denyRead: ["~/"]` + `allowRead` | ○ | Copilot と同じ whitelist 方式に揃えるため |
| Claude `strictAllowlist` | ○ | `claude_network_strict = true` |
| Claude `credentials` (`deny` / `mask`) | **×** | §2.3。env の `deny` は検討価値あり |
| Claude `filesystem.disabled` | × | 権限昇格の経路になる |
| Claude `excludedCommands` | × | 必要になっていない |
| Claude `seccomp.applyPath` | ○ | mise 導入のため明示パス指定 |
| Copilot `deniedPaths` | ○ | 共有 `deny` から生成 |
| Copilot `readonly` / `readwritePaths` | ○ | uv の取りこぼし補償のみ |
| Copilot `allowed_directories` | 枠のみ | 案件固有のパスが要るときに使う |
| Copilot network proxy | × | — |

## 8. 次に検討する候補

1. **`sandbox.credentials.envVars` の `deny`** —
   `GITHUB_TOKEN` などを sandbox 内で unset する。hook の
   `check_secret_env_echo` より迂回耐性が高く、`filesystem.disabled` の
   影響も受けない。`gh` への影響を実測してから
2. **`failIfUnavailable: true`** — 「有効にしたつもりで素通り」を防ぐ。
   ただし依存が欠けた環境で Claude Code が起動しなくなる
3. **`copilot_read_allow` の棚卸し** — `allowDevToolAccess` を切ったので、
   新しいツールチェーンを入れたら追記が要る。不足は不可視 (ENOENT) で
   現れるので、動かないツールが出たら `/sandbox policy` と `findmnt` で確認する

## 9. 用語の対応表

| 概念 | Claude | Copilot |
| --- | --- | --- |
| 読み取り禁止 | `filesystem.denyRead` | `userPolicy.filesystem.deniedPaths` |
| 書き込み禁止 | `filesystem.denyWrite` | (cwd 外は既定で不可) |
| 読み取り許可 | `filesystem.allowRead` | `userPolicy.filesystem.readonlyPaths` |
| 書き込み許可 | `filesystem.allowWrite` | `userPolicy.filesystem.readwritePaths` |
| 追加の作業ディレクトリ | `--add-dir` / `permissions.additionalDirectories` | `--add-dir` / `allowed_directories` |
| ドメイン許可 | `network.allowedDomains` | (無し。`allowOutbound` の on/off) |
| 実効ポリシーの確認 | `/sandbox` の Config タブ | `/sandbox policy` |
| 脱出の可否 | `allowUnsandboxedCommands` | `allowBypass` |

## 10. 再確認すべき情報源

- Claude Code: [Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing)
- Claude Code: [Settings reference](https://code.claude.com/docs/en/settings-reference) の sandbox 節
- Claude Code: [Settings files and precedence](https://code.claude.com/docs/en/settings)
- Copilot CLI: [Understanding filesystem policies for local sandboxing](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/understanding-local-sandboxing)
- Copilot CLI: [Using local sandboxing](https://docs.github.com/en/copilot/how-tos/cloud-and-local-sandboxes/using-local-sandboxing)
- Copilot CLI: [Configuring local sandbox settings](https://docs.github.com/en/copilot/how-tos/cloud-and-local-sandboxes/configuring-local-sandbox-settings)
- Copilot CLI: [Configuration directory reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)
- Copilot CLI: [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
- Linux backend の実装: `microsoft/mxc` の
  `backends/bubblewrap/common/src/proxy_network.rs` (依存の probe とエラー文言)

[調査記録一覧へ戻る](../index.md)
