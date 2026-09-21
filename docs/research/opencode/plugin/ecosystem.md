# OpenCode プラグイン生態系の棚卸し

> **調査日: 2026-09-21**
> **対象: この環境に導入済みの `opencode v2.0.10`（V2）**
>
> 一次情報は npm レジストリ API、<https://opencode.ai/v2/docs/>、
> [awesome-opencode](https://github.com/awesome-opencode/awesome-opencode)（10.3k star）。
> 各パッケージの依存は `registry.npmjs.org` の生 JSON を読んで判定した。

## 0. 本書の用途

[OpenCode V2 の仕様](../v2-capabilities.md) が「OpenCode 単体で何ができるか」を
扱うのに対し、本書は **「第三者プラグインで補えるか」** を扱う。

具体的には、`check_bash.py` 相当の hook を OpenCode へ持ち込む手段として
[エージェント権限仕様](../../../spec/agent-permissions.md#opencode-v2-の扱い) が挙げた
3 つの選択肢のうち、「既製プラグインに乗る」が成立するかを判定する。

## 1. 結論の先出し

| 論点 | 判定 |
| --- | --- |
| V2 で動くサードパーティ製プラグインはあるか | **調べた範囲では 1 つも無い** |
| Claude Code の hook を OpenCode で動かす既製品はあるか | 3 つ存在するが **全て V1 専用** |
| oh-my-opencode（OmO）は使えるか | **使えない**。最新 beta も V1 |
| 結論 | **既製品に乗る道は現時点で無い**。hook が要るなら自作するしかない |

### ★V1 と V2 でプラグイン API が別パッケージ

取り違えると調査結果が逆になる。実際、本調査中に一度誤判定した
（`@opencode-ai/` が `@opencode` に部分一致したため）。

| npm パッケージ | 対応 | `latest`（2026-09-21） |
| --- | --- | --- |
| **`@opencode/plugin`** | **V2** | **2.0.11** |
| `@opencode-ai/plugin` | V1 | 1.18.31 |

[V2 の移行ガイド](https://opencode.ai/v2/docs/migrate-v1)が
「設定ファイルは互換、**意図的な破壊的変更はサーバ API と plugin API のみ**」と
明記しているとおり、**V1 プラグインの実装は V2 では動かない**。
この点は[OpenCode V2 の仕様 §10](../v2-capabilities.md) で既に
「plugin 実装は全面書き直し」と記録済みで、本調査はそれを生態系側から裏付けた。

## 2. 実測: 主要プラグインの API 世代

npm の人気順・awesome-opencode 掲載から 20 件を抽出し、依存を直接読んだ。

```console
curl -sS "https://registry.npmjs.org/<pkg>" |
  python3 -c '...dependencies / peerDependencies を表示...'
```

| パッケージ | latest | 世代 | 公開日 |
| --- | --- | --- | --- |
| `oh-my-opencode` | 4.19.4 | **V1** | 2026-08-01 |
| `oh-my-opencode`（beta） | 5.0.0-beta.80 | **V1** | 2026-09-20 |
| `oh-my-opencode-slim` | 2.2.22 | **V1** | 2026-09-19 |
| `opencode-claude-hooks` | 0.1.0 | **V1** | 2026-02-02 |
| `opencode-command-hooks` | 0.7.1 | **V1** | 2026-09-13 |
| `opencode-swarm` | 7.184.16 | **V1** | 2026-09-20 |
| `@tarquinen/opencode-dcp` | 3.2.0 | **V1** | 2026-09-20 |
| `@cortexkit/opencode-magic-context` | 0.42.6 | **V1** | 2026-09-19 |
| `opencode-supermemory` | 2.0.13 | **V1** | 2026-09-01 |
| `opencode-models-discovery` | 1.5.5 | **V1** | 2026-09-15 |
| `opencode-auto-resume` | 1.1.17 | **V1** | 2026-09-17 |
| `opencode-claude-auth` | 2.2.0 | **V1** | 2026-09-01 |
| `opencode-pty` | 0.4.0 | **V1** | 2026-09-18 |
| `@langfuse/opencode-observability-plugin` | 0.4.0 | **V1** | 2026-09-08 |
| `opencode-snip` | 1.6.1 | **V1** | 2026-04-10 |
| `opencode-websearch` | 0.6.0 | **V1** | 2026-05-07 |
| `@falentio/opencode-pstack` | 0.6.2 | **V1** | 2026-09-17 |
| `@prevalentware/opencode-goal-plugin` | 0.1.49 | **V1** | 2026-09-14 |
| `opencode-model-recommender` | 1.0.0-alpha.3 | **V1** | 2026-09-08 |
| `@plannotator/opencode` / `opencode-mtel` | — | 依存に plugin API 無し | — |

**`@opencode/plugin`（V2）に依存するパッケージは 1 件も見つからなかった。**

> 網羅性の限界: npm の `depends:` 検索は機能せず（全文検索へ落ちて 30 万件を返す）、
> 人気順 20 件の抽出にとどまる。**「V2 対応が存在しない」ことの証明ではない**が、
> 生態系の主要部分が V1 に留まっていることは言える。

V2 の 2.0.0 リリースが 2026-09-11 と新しいため、移行が始まっていないと推測される
（推測）。OmO は README で
「Multi-Harness Agent OS Refactor in Progress」と告知しているが、
2026-09-20 公開の beta も依存は `@opencode-ai/plugin 1.18.22` のままだった。

## 3. Claude Code hook 互換プラグイン（3 件）

このリポジトリにとって最も価値が高かったはずの分類。**3 件とも V1 専用**。

| プラグイン | 方式 | 状態 |
| --- | --- | --- |
| [romain325/opencode-hooks-plugin](https://github.com/romain325/opencode-hooks-plugin) | `.claude/settings.json` の `hooks` を読んで実行 | star 6 / commit 5 / WTFPL |
| [magarcia/opencode-claude-hooks](https://github.com/magarcia/opencode-claude-hooks) | 同上 | **1 版のみ**・2026-02-02 以降更新なし / MIT |
| [shanebishop1/opencode-command-hooks](https://github.com/shanebishop1/opencode-command-hooks) | 独自宣言形式でシェルコマンドを紐付け | 19 版・更新は活発 / MIT |

### romain325 版の仕様（最も本リポジトリに近い）

仮に V2 対応しても、**本リポジトリの hook 構成はそのままでは載らない**。

| Claude のイベント | このプラグインでの扱い | 本リポジトリへの影響 |
| --- | --- | --- |
| `PreToolUse` | 自動発火。exit 2 でブロック | `check_bash.py` / `check_file_read.py` / `redirect-tmp.py` は載る |
| `PostToolUse` | 自動発火 | `markdownlint.sh` / `format-file.sh` は載る（ただし `formatter` で代替済み） |
| `SessionStart` | セッション作成時に発火 | `checkpoint_restore` は matcher `compact` 前提なので **要確認** |
| `PreCompact` | **自動発火しない**。`/hook-precompact` という手動コマンド | `checkpoint_precompact` が**機能しない** |
| `PermissionRequest` | **非対応** | — |

つまり 8 個の hook のうち、**`checkpoint_precompact` は原理的に載らない**。

## 4. oh-my-opencode（OmO）

採用可否を個別に検討していたが、**V1 のため V2 環境では起動しない**。
以下は将来 V2 対応した場合に備えた記録。

| 項目 | 内容 |
| --- | --- |
| 構成 | 11 エージェント、54+ ライフサイクル hook（Team Mode で 61）、5 つの内蔵 MCP |
| 設定 | `~/.config/opencode/oh-my-openagent.json[c]`、プロジェクト側は `.opencode/` |
| インストール | `bunx oh-my-openagent install`（**bun 必須**、TUI 対話） |
| ライセンス | SUL-1.0（OSI 承認ではない） |
| テレメトリ | **既定 on**。`"telemetry": false` / `OMO_DISABLE_POSTHOG=1` で無効化 |
| 更新頻度 | 329 版。beta は連日公開 |

### 本リポジトリの設計との衝突点

| 衝突 | 内容 |
| --- | --- |
| `opencode.json` を書き換える | install が plugin エントリを追記する。chezmoi の生成物と領域が重なる |
| 設定キー名 | README の uninstall は `.plugin`（単数）、V2 公式ドキュメントは `plugins`（複数）。**未確認** |
| エージェントを 11 個追加 | エージェント別 permission を設計する場合、`build` / `general` 以外も対象になる |
| MCP を実行時注入 | Exa / context7 / grep_app は `opencode mcp list` に出ない。`[[mcp]]` の単一ソース管理の**外側**になる |
| edit ツールを置換 | Hashline（`LINE#ID` 方式）。`edit` permission の resource 解釈に影響しうる |

## 5. 生態系の全体像

awesome-opencode に約 130 件。分類すると本リポジトリに関係するのは一部に限られる。

| 分類 | 件数の目安 | 例 |
| --- | --- | --- |
| プロバイダ認証 | 多数 | Antigravity Auth、Gemini Auth、OpenAI Codex Auth、Kilo Gateway Auth |
| メモリ・文脈管理 | 多数 | Agent Memory、Honcho、Magic Context、Harness Memory、oc-mnemoria |
| エージェント統合 | 多数 | OmO、OmO Slim、CrewBee、Open Conclave、Swarm、hiai-opencode |
| 通知・可視化 | 多数 | Opencode Notify、ntfy.sh、TTS、Visualizer、Agent Tmux |
| トークン計測 | 多数 | Token Monitor、Tokenscope、Quota、Throughput |
| **安全・権限** | **少数** | CC Safety Net、Envsitter Guard、Semantic Anchors、Opencode Ignore、Log Sanitizer |
| **hook 互換** | **3 件** | §3 のとおり |

安全・権限の分類は **5 件程度**しか無く、いずれも npm 未公開（GitHub のみ）。
本リポジトリが `common.toml` + `lib/bashrules/` で実現している粒度に近いものは無い。

> 未検証: 安全系 5 件は npm に無いため、V1/V2 の判定をしていない。
> 必要になったら各リポジトリの `package.json` を直接読むこと。

## 6. 含意

1. **既製プラグインに乗る道は現時点で無い。** hook が要るなら
   `@opencode/plugin` 2.x に対して自作する
2. **OmO の hook 互換を検証する計画は無意味になった。** V1 なので起動しない
3. **検証対象は OpenCode 本体の plugin API そのもの**に絞られる。
   具体的には `ctx.permission.hook("evaluate")` が
   `check_bash.py` に必要な情報（cwd・生コマンド）を渡すか
4. 生態系が V1 に留まっている事実は、
   [OpenCode V2 の仕様 §11](../v2-capabilities.md)の
   「成熟度だけが見送り理由」という評価を補強する

## 再確認すべき情報源

移行が進めば判定が変わる。次を走らせて差分を取ること。

```console
# V2 plugin API の版
curl -sS https://registry.npmjs.org/@opencode%2Fplugin | jq -r '.["dist-tags"].latest'

# 主要プラグインが V2 へ移ったか (@opencode/plugin が現れるか)
curl -sS https://registry.npmjs.org/oh-my-opencode | jq -r '.versions[.["dist-tags"].beta].dependencies'
```

- <https://github.com/awesome-opencode/awesome-opencode>（一覧の更新）
- <https://opencode.ai/v2/docs/build/plugins/migrate-v1>（移行ガイド）
- [OmO の ROADMAP](https://github.com/code-yeongyu/oh-my-openagent/blob/HEAD/ROADMAP.md)（マルチハーネス対応の進捗）

[調査記録一覧へ戻る](../../index.md)
