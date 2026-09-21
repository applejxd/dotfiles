# OpenCode V2 の仕様（乗り換え再評価用）

> **調査日: 2026-09-20**
> **対象: `@opencode/cli` 2.0.10（V2）/ 比較対象 `opencode-ai` 1.18.31（V1）**
>
> 一次情報は <https://opencode.ai/v2/docs/> 以下と npm レジストリ。
> V1 のドキュメント（<https://opencode.ai/docs/>）は比較のためだけに参照し、
> 混同しないよう出典を分けてある。

## 0. 本書の用途

[ハーネス比較 §10](../agents/harness-comparison.md) で「OpenCode への一本化は
**V2 が落ち着くまで見送り**」と決めた。その再評価に要る材料をここに置く。
§10 を開き直すときは、まず本書の[再確認すべき情報源](#再確認すべき情報源)を
走らせて差分を取ること。

**この環境の前提**（判断が変わったら §10 も直す）:

- 自宅は GitHub Copilot 契約、業務は AWS Bedrock 経由が要件。**OpenCode は両方を
  公式サポートするので、1 本化が原理的に可能**
- OS レベル sandbox は必須ではない。評価軸は
  **「permission だけで必要な禁止を表現しきれるか」**

### ★パッケージ名を間違えないこと

3 つ存在し、取り違えやすい。本書の調査中に 2 回誤った。

| npm パッケージ | 中身 | `latest`（2026-09-20） |
| --- | --- | --- |
| **`@opencode/cli`** | **V2（本命）** | **2.0.10** |
| `opencode-ai` | V1 | 1.18.31 |
| `@opencode-ai/cli` | 別物 | `0.0.0-beta-17823` |

V2 の導入は `npm i -g @opencode/cli`、
`curl -fsSL https://opencode.ai/v2/install | bash`、
`brew install anomalyco/tap/opencode-v2`、AUR は `opencode-beta`。

## 1. 結論の先出し（この環境にとっての含意）

| 論点 | V2 の状況 | 判定 |
| --- | --- | --- |
| 1 本化できるか | Copilot 契約も Bedrock も公式サポート | **できる** |
| `check_bash.py` 相当を置けるか | `ctx.permission.hook("evaluate")` | **置ける**（後述の制約あり） |
| コマンド単位の allow/deny | `shell` の resource は引数を含むコマンド文字列 | **書ける** |
| 圧縮を跨ぐ文脈の引き継ぎ | `ctx.session.hook("context")` が毎モデル呼び出し直前に走る | **Claude / Copilot より強い** |
| skill 資産 | `.claude/skills` を compatibility ソースとして読む | **そのまま使える** |
| 設定ファイル | V1 の設定を**メモリ上で正規化して読む** | 移行は機械的 |
| plugin 実装 | **V1 の実装は一切動かない** | **全面書き直し** |
| 成熟度 | 2.0.0 が 2026-09-11、2.0.10 が 09-19。**8 日で 11 リリース** | **ここだけが見送り理由** |

## 2. config

- 形式は `opencode.json` / `opencode.jsonc`。`$schema` は
  `https://opencode.ai/config.json`
- 探索はカレントからファイルシステムルートまで。**遠い階層から近い階層の順に
  直下の `opencode.json(c)` をマージし、その後 `.opencode/` 配下を同順でマージ**

> OpenCode searches from the current directory to the filesystem root. It first
> merges direct `opencode.json(c)` files from the farthest directory to the
> closest, then merges files inside `.opencode` directories in the same order.
> This means every discovered `.opencode` config overrides every direct config.

つまり `.opencode/` 配下は常に直下設定に勝つ。リポジトリ単位の上書きはここへ置く。

環境変数: `OPENCODE_DISABLE_PROJECT_CONFIG=1`（プロジェクト `AGENTS.md` の探索だけを
無効化）、`OPENCODE_CLI_CONFIG_CONTENT`、`OPENCODE_LOG_LEVEL`、`OPENCODE_DB`。

出典: <https://opencode.ai/v2/docs/config/>

## 3. permission（最重要）

V1 の「ツール名をキーにしたマップ」から、**順序付きルール配列**へ全面的に変わった。

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "permissions": [
    { "action": "shell", "resource": "*",            "effect": "ask" },
    { "action": "shell", "resource": "git status *", "effect": "allow" },
    { "action": "shell", "resource": "git push *",   "effect": "deny" }
  ]
}
```

> V1 uses different field and action names. In V2, use `permissions`, `shell`,
> and `subagent` instead of `permission`, `bash`, and `task`.

### アクション一覧

| action | resource |
| --- | --- |
| `read` | Location 相対の内部パス、または正規化した絶対外部パス |
| `edit` | `edit` / `write` / `patch` の対象パス |
| `glob` | glob パターン |
| `grep` | **検索パスではなく正規表現そのもの** |
| `shell` | スキャナが生成したコマンド文字列。複合コマンドは複数生成しうる |
| `subagent` | エージェント ID |
| `skill` | スキル ID |
| `question` | `*` |
| `webfetch` | URL |
| `websearch` | クエリ |
| `external_directory` | 外部ディレクトリ境界。通常 `/*` で終わる |
| `<server>_<tool>` | `*`（MCP ツール。非対応文字は `_`） |
| `execute` | `*`（Code Mode の可否だけ。ネストしたツールは個別に判定） |

`doom_loop` と `lsp` は **V2 Core のアクションではない**（V1 にはあった）。
アクション名は文字列なので、プラグインが独自のアクションを足せる。

### マッチと優先順位

- `*` は `/` を含むゼロ文字以上、`?` は 1 文字。**全体一致**
- **最後にマッチしたルールが勝つ**。結合順は「低優先度の設定 → グローバル →
  エージェント」
- マッチが無ければ `ask`
- 1 操作が複数リソースに触れる場合、**1 つでも `deny` なら deny、次に `ask`**
- `shell` のパターンが `*` で終わると引数なしのコマンドにも一致する
  （`git status *` は `git status` にも当たる）
- `~` / `$HOME` は `external_directory` / `read` / `edit` でのみ展開。
  **`shell` の resource は生のコマンド文字列で展開されない**

### 既定ポリシー

全エージェント共通の基底:

```jsonc
[
  { "action": "*",                  "resource": "*",              "effect": "allow" },
  { "action": "external_directory", "resource": "*",              "effect": "ask" },
  { "action": "read",               "resource": "*.env",          "effect": "ask" },
  { "action": "read",               "resource": "*.env.*",        "effect": "ask" },
  { "action": "read",               "resource": "*.env.example",  "effect": "allow" }
]
```

`explore` は read / glob / grep / webfetch / websearch 以外を拒否、`title` と
`summary` は全拒否、`plan` は `~/.opencode/plan` 以外の編集を拒否。

**承認済みの保存パターンは project スコープの `allow` になるが、設定済みの `deny`
を上書きしない。**

### ★この環境にとっての注意

公式が明記している限界:

> `shell` runs with the host user's filesystem, process, and network authority.
> Directory inference from command text is best effort, so prefer a narrow shell
> allowlist instead of patterns intended to recognize every dangerous command.

「危険なコマンドを網羅的に検知するパターン」ではなく**狭い allowlist** を推奨して
いる。`check_bash.py` が積み上げてきた deny 中心の設計とは方針が逆なので、
移行時はここを設計し直すことになる。

出典: <https://opencode.ai/v2/docs/permissions/>

## 4. plugin / hook

### 形

```ts
import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "example",
  async setup(ctx) { /* ... */ },
})
```

配置は `.opencode/plugins/` と `~/.config/opencode/plugins/` を自動検出。
`opencode.json(c)` の `plugins` 配列で npm パッケージ・Git・ローカルパスも指定可。
`opencode plugin add/list/check/update/remove` で管理する。

### hook 一覧

| ドメイン | hook | できること |
| --- | --- | --- |
| session | `prompt` | 受理前にプロンプト本文・添付・skill・delivery を書き換え |
| session | `context` | **エージェントループの毎モデル呼び出し直前**に system / messages / tools / options を編集 |
| session | `compaction` | 要約対象の messages を受け取り、`result` を設定すればモデル呼び出しを省略して自前の要約を採用 |
| session | `generate` / `title` | 補助リクエスト用。`title` は `result` で置換可 |
| session | `model.request` / `http.request` / `http.response` | ヘッダ・生 HTTP |
| session | `retry` | リトライ可否と遅延の上書き |
| session | `experimental.ws.*` | WebSocket。**names or shapes may change** |
| permission | `evaluate` | 設定ルール評価後・実行前に `effect` と `message` を書き換え |
| shell | `create.before` | command / cwd / timeout / shell / env を編集 |
| tool | `execute.before` / `execute.after` | 入力と結果を編集 |

### permission hook の制約（重要）

```ts
interface PermissionEvaluation {
  readonly sessionID: string
  readonly agent?: string
  readonly action: string
  readonly resources: readonly string[]
  effect: "allow" | "ask" | "deny"
  message?: string
}
```

> Hooks run for `allow` and `ask` decisions.
> **An explicit configured `deny` is final and does not invoke the hook.**

つまり「設定で `deny`、hook で条件付きに緩める」ができない。本リポジトリが
Claude で踏んだ「静的 `ask` と hook の所有権が競合する」問題
（[ADR 0006](../../adr/0006-instructions-to-mechanisms.md) 周辺）と同種の制約なので、
**deny は hook 側に寄せる**設計になる。

### transform（hook とは別枠）

agent / provider / model / command / integration / mcp / reference / skill /
tool / vcs / websearch / worktree の各ドメインを、同期コールバックで編集できる。
読み取りのたびに全 transform を再生するため、冪等かつ安価に書く必要がある。

`ctx.permission.rules({ sessionID, permissions })` でセッションスコープの
ルールを差し替えることもできる（エージェントのルールの後に評価される）。

出典: <https://opencode.ai/v2/docs/build/plugins/>

## 5. agent / subagent

組み込みは `build`（primary、既定）、`plan`（primary、編集は `~/.opencode/plan`
のみ）、`general`（subagent、subagent 起動と question を拒否）、`explore`
（subagent、読み取り系以外を拒否）。隠しエージェントに `compaction` / `title` /
`summary`。**V2 に `scout` は無い**（V1 にはあった）。

カスタムは `.opencode/agents/<name>.md`（YAML frontmatter + 本文が system）か
JSONC の `agents.<id>`。主なフィールドは `description` / `mode` / `model` /
`system` / `permissions` / `steps` / `hidden` / `disabled`。

**subagent は親の権限のサブセットではなく、自分の権限を使う。**

> A custom subagent uses its own permissions, not a subset of its parent's
> permissions.

`request.headers` / `request.body` は**受理されるがモデルリクエストに送られない**
（未実装）。

出典: <https://opencode.ai/v2/docs/agents/>

## 6. skills

探索パスは 6 箇所。**`.claude/skills` と `~/.claude/skills` を compatibility
ソースとして読む**ので、本リポジトリの skill 資産はそのまま載る。

| スコープ | パス |
| --- | --- |
| グローバル | `~/.config/opencode/skills` |
| グローバル互換 | `~/.claude/skills`、`~/.agents/skills` |
| プロジェクト | `.opencode/skills` |
| プロジェクト互換 | `.claude/skills`、`.agents/skills` |

frontmatter は `name` / `description` / `slash` /
`metadata.opencode/slash` / `metadata.opencode/autoinvoke`。
`autoinvoke: false` はモデルの一覧から隠すだけで、ID 指定では読める。
HTTP カタログ（`index.json`）からの取得にも対応。

移植性のための推奨（ID 正規表現、1–64 文字、name とディレクトリ名の一致、
description の長さ）は **V2 では強制していない**。

出典: <https://opencode.ai/v2/docs/skills/>

## 7. MCP / commands / providers

- **MCP**: `mcp.servers.<name>`。V1 の平坦な `mcp.<name>` から変わり、
  `enabled` は `disabled` に反転、単一 `timeout` は `{startup, catalog, execution}`
  へ構造化
- **commands**: `commands` キー（V1 は `command`）。`.opencode/commands/` も検出
- **Copilot**: `/connect` → GitHub Copilot → デバイス OAuth。Copilot Chat の
  entitlement が要る
- **Bedrock**: AWS 既定の資格情報チェーン。`aws sso login --profile work` で
  SSO、`providers.amazon-bedrock.settings.profile` か `AWS_PROFILE` を指定。
  リージョンは `AWS_REGION` → `AWS_DEFAULT_REGION` → `us-east-1`。
  API キー方式は `AWS_BEARER_TOKEN_BEDROCK`、VPC は `settings.baseURL`

出典: <https://opencode.ai/v2/docs/mcp-servers/>、
<https://opencode.ai/v2/docs/providers/>、
<https://opencode.ai/v2/docs/cli/providers>

## 8. compaction

自動圧縮の発動条件:

```text
estimated tokens >= min(input limit - buffer,
                        context limit - max(output reserve, buffer))
```

既定は `buffer = 20000`、`keep.tokens = 15000`。

手動圧縮は**サーバ API** で行う。TUI のスラッシュコマンドは確認できなかった。

```bash
curl -X POST http://localhost:4096/api/session/ses_example/compact -d '{}'
```

**文脈使用率を直接返す API は V2 のドキュメントでは確認できず。**
Copilot CLI と同じ制約がここにもある（[compaction-hooks.md](../agents/compaction-hooks.md)
記録 E5 / E6）。

介入は `ctx.session.hook("compaction")` で、`result` を設定すればモデル呼び出しを
飛ばして自前の要約を採用できる。V1 の `experimental.session.compacting` から
**`experimental.` が外れている**。

出典: <https://opencode.ai/v2/docs/compaction/>

## 9. CLI

- 非対話: `opencode run "<prompt>"`。`--model` / `--continue` / `--format json`
  （NDJSON）/ `--file` / `--agent`
- **V1 の `--auto` に相当する CLI フラグは V2 のドキュメントに無い。**
  確認できたのは `cli.json` の `session.permissions: "prompt" | "autoaccept"`
- セッション: `opencode session list/delete/export/import`、`--continue`
- その他: `auth` / `models` / `mcp` / `plugin` / `stats` / `serve` / `pair` /
  `service` / `reload` / `api` / `acp` / `debug` / `upgrade`

出典: <https://opencode.ai/v2/docs/cli/commands/>、
<https://opencode.ai/v2/docs/cli/config/>

## 10. V1 → V2 の移行

**意図的な破壊的変更は 3 つだけ**と公式が明言している。

> V2 has three intentional breaking changes: Plugins use a new plugin API.
> The server API and clients have new contracts. Terminal client configuration
> moves from layered `tui.json(c)` files to one global `cli.json` file
> (auto migrated).

それ以外は互換維持が意図されており、**V1 の設定ファイルをそのまま読んでメモリ上で
正規化する**（ファイルは書き換えない）。したがって「更新したら設定が壊れる」型の
事故は、当初の想定より起きにくい。

主なリネーム:

| V1 | V2 |
| --- | --- |
| `permission`（マップ） | `permissions`（順序配列） |
| `bash` / `task` | `shell` / `subagent` |
| `agent` / `mode` | `agents`。`prompt`→`system`、`disable`→`disabled`、`maxSteps`→`steps` |
| `mcp.<name>` | `mcp.servers.<name>`、`enabled`→`disabled`（反転） |
| `compaction.preserve_recent_tokens` / `reserved` | `compaction.keep.tokens` / `buffer` |
| `command` / `reference` / `provider` | `commands` / `references` / `providers` |
| `autoshare`（bool） | `share`（enum） |

**受理されるが警告付きで無視される**もの: `logLevel`、`server`、
`compaction.tail_turns`、`compaction.prune`、experimental の `batch_tool` /
`openTelemetry` / `primary_tools` / `continue_loop_on_deny` ほか。

> Ignoring these fields is intentional and is not a compatibility regression.

**プラグインだけは別**である。

> V1 plugin implementations do not run in V2. Moving a file or renaming its
> config entry is not enough.

出典: <https://opencode.ai/v2/docs/migrate-v1/>、
<https://opencode.ai/v2/docs/build/plugins/migrate-v1>

## 11. 成熟度（唯一の見送り理由）

`@opencode/cli` の公開履歴（npm レジストリから直接取得）:

| バージョン | 公開 |
| --- | --- |
| 2.0.0 | 2026-09-11 |
| 2.0.5 | 2026-09-16 |
| 2.0.10 | 2026-09-19 |

**8 日で 11 リリース（約 1.4 回/日）。** dist-tags は
`latest: 2.0.10` / `beta: 0.0.0-beta-*` / `dev: 0.0.0-dev-*` で、
`latest` はセマンティックバージョンの安定チャンネル。
ただし `anomalyco/opencode` の Releases には V1 系（1.18.x）しか載っておらず、
V2 のリリースノートはミラーされていない。

### 自認されている未実装・機能後退

| 項目 | 状態 | 出典 |
| --- | --- | --- |
| `config.instructions` 配列 | 受理するがファイル / glob / URL を解決しない | `/v2/docs/instructions` |
| セッション共有 | 「not supported yet」 | `/v2/docs/sharing/` |
| **LSP** | 設定は受理するが**言語サーバを起動せず、LSP ツールも診断も出さない**。V1 からの機能後退 | `/v2/docs/migrate-v1/` |
| agent の `request.headers` / `request.body` | 保持するがモデルリクエストに送らない | `/v2/docs/agents/` |
| `username` | 受理するが会話に出ない | `/v2/docs/config/` |
| `experimental.portable_shell_scanner` | 実験的。解析不能コマンドは即エラー | `/v2/docs/permissions/` |
| `experimental.ws.*` フック | 「names or shapes may change」 | `/v2/docs/build/plugins/` |

## 12. 資産の移行可否

| 資産 | V2 での扱い |
| --- | --- |
| skill（`SKILL.md`） | **ほぼそのまま**。`.claude/skills` を読む |
| `AGENTS.md` | **そのまま**。ただし `CLAUDE.md` は読まれない |
| permission ルール | **書き直し**。ただし機械的（キー名 + マップ→配列） |
| MCP 設定 | **書き直し**。フィールド名のみ（`mcp.servers`、`disabled` 反転） |
| hook 実装（`check_bash.py` 等） | **全面書き直し**。Python の外部プロセスから TypeScript プラグインへ |
| `[sandbox] deny` | **対応物なし**。`external_directory` + `read`/`edit` の deny で代替 |
| `common.toml` からの生成という設計 | **維持できる**。V2 ターゲットを足す形 |

最も重い項目は hook である。現在 `bashrules/` に 3,410 行あり、これを
TypeScript プラグインへ移す必要がある。ただし V2 では
`ctx.permission.hook("evaluate")` が構造化された入出力を持つため、
exit code と stdout JSON の作法（[ADR 0004](../../adr/0004-hook-check-semantic-axis.md)）
に費やしていた労力は不要になる。

## 再確認すべき情報源

§10 を開き直すときは、この順で確認する。

```bash
npm view @opencode/cli time --json | tail -20   # リリース間隔が開いたか
```

| 優先 | 見るもの | 何を確認するか |
| --- | --- | --- |
| ★★★ | `npm view @opencode/cli time` | リリース頻度が 1.4 回/日 から落ちたか |
| ★★★ | <https://opencode.ai/v2/docs/instructions> | 「does not currently resolve」が消えたか |
| ★★☆ | <https://opencode.ai/v2/docs/migrate-v1/> | 「受理するが無視」の一覧が減ったか |
| ★★☆ | <https://opencode.ai/v2/docs/permissions/> | アクション一覧の増減、`deny` と hook の関係 |
| ★★☆ | <https://opencode.ai/v2/docs/build/plugins/> | `experimental.` が付いた hook の増減 |
| ★☆☆ | <https://opencode.ai/v2/docs/sharing/> | 「not supported yet」が消えたか |
| ★☆☆ | <https://github.com/anomalyco/opencode/releases> | V2 のリリースノートがミラーされたか |
