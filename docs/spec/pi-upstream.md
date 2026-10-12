# pi の公式仕様と、実測で頼っている挙動の棚卸し

pi（earendil-works/pi）の挙動のうち、このリポジトリが頼っているものを、**公式の仕様に明示があるか**で分ける。
仕様の本文は pi の更新で変わるので、**明示があるものはここへ写さず、リンクだけを置いて都度読む**。
**明示が無いものは、実測したことをここに書き、試験で固定する**（公式を読んでも分からないため）。

- 対象のバージョン: **pi 1.1.0**（2026-10-11 時点。`pi --version`）
- 見出し: [A. 公式に明示がある（リンクだけ）](#a-公式に明示があるリンクだけ) / [B. 明示が無い（ここに書く）](#b-明示が無いここに書く) / [確認先](#確認先と更新時の手順) / [codemode の扱い](#codemode-の扱い)

## 確認先と更新時の手順

| 確認先 | 場所 |
| --- | --- |
| インストール済みの文書 | pi の npm パッケージの `docs/` ディレクトリ（Windows の npm global は `%APPDATA%\npm\node_modules\@earendil-works\pi-coding-agent\docs\`）。目次は `docs.json`、更新の記録は同じ階層の `CHANGELOG.md`。**入れている版に合う文書は、これ** |
| ソースと文書（上流） | <https://github.com/earendil-works/pi>（`packages/coding-agent/docs/`） |
| 利用者向けの文書 | <https://pi.dev>（Windows は <https://pi.dev/docs/windows>） |
| 版 | `pi --version`、`~/.pi/agent/install/releases/<版>/`（公式インストーラー） |

pi を更新したときの手順:

1. `CHANGELOG.md` の該当の節を読み、下の表の項目に触れる変更が無いかを見る
2. 表 A の文書の該当箇所を読み直す（リンク先の記述が変わっていないか）
3. **表 B の試験を回す**（Unix で `test/agents/test_pi_harness.py` と `test_pi_harness_extensions.py`。Windows でも一部は回る。[実測 E5](../research/agents/pi-extension-under-harness.md)）。落ちたら、挙動が変わった印なので、表 B と実測の記録を直す
4. 直したら、表の「確認した版」を更新する

## A. 公式に明示がある（リンクだけ）

仕様は pi の文書が正本。ここには、**何に頼っているか**と**どこを読むか**だけを書く（文書名は、pi の npm パッケージの `docs/` 配下のファイル）。

| 項目 | 公式の文書 | このリポジトリが頼っているところ |
| --- | --- | --- |
| `-ne` は発見・設定・組み込みの拡張を無効にし、明示した `-e` は読む | `cli.md`（`-e`、`-ne`） | `pis` の起動（`-nbt -ne -e builtin:mcp -e <ハーネス>`）、Orca の拡張を足す形、[外部の拡張の方針](pi-harness.md#拡張の方針) |
| 組み込みの拡張の名前（`builtin:mcp`・`builtin:llama.cpp`・`builtin:codemode`・`builtin:tool-search`） | `settings.md`（Built-in extensions） | `-e builtin:mcp` だけを戻す。`codemode` を足すときは `-e builtin:codemode` |
| ツールの選択（`-nbt`・`--tools`・`-xt`・`-nt`、`defaultTools`） | `cli.md`、`settings.md` | 組み込みのツールを外し、ハーネスの `guarded_*` だけにする |
| `codemode`（スクリプトの API・結果の形・オプション・`store`・`models`・上限） | `codemode.md`、`cli.md`（Enable codemode）、`settings.md`（`codemode.mode`・`codemode.inlineBudget`） | 検索の入口の比較（[入口の選び方](pi-harness.md#入口の選び方)）。今は使っていない |
| MCP の設定・`exposure`（`codemode` / `deferred` / `direct` / `hidden`）・ツール名 `mcp__<server>__<tool>`・`pi mcp add`・project trust | `mcp.md` | `[[mcp]]` の `exposure`（[仕様](agent-config-generation.md#mcp-サーバ)）、`mcp.json` を `pis` が拒む理由 |
| 拡張の API: `registerTool`、`registerMcpServer` | `extensions.md` | ハーネスのツールと MCP の登録 |
| `tool_call` は入力を書き換える・実行を止められる、`tool_result` は合成される、`tool_call` の失敗は fail-safe で止まる、`ctx.executeTool` の入れ子も `tool_call` / `tool_result` を通る | `extensions.md`（Events、Nested tool calls、Error handling） | 判定の方式（`tool_call` と `execute()` の二重の判定）、`codemode` の中の呼び出しが判定を通ること |
| 初期のプロンプトとツール集合を記録し、変更は次の要求の前に追記する | `extensions.md`（Prompt cache の節） | キャッシュ安定性の見込み（ツール定義を増やすと先頭側が変わる） |
| `ctx.hasUI`・`ctx.mode` | `extensions.md` | UI の無い起動での確認の扱い（ハーネス側の判断は表 B の 8） |
| `skills` の設定 | `settings.md`（`skills`）、`skills.md` | `[pi.settings] skills = ["~/.claude/skills"]` |
| `--print`・`--mode json` / `rpc` とイベント | `cli.md`、`json.md`、`rpc.md` | 試験（偽のモデル）、Zed・Orca の RPC |

## B. 明示が無い（ここに書く）

公式の文書では確かめられない挙動。**実測した版と根拠（記録・試験）**を付け、更新時に試験で確かめる。

| # | 挙動（実測） | 公式の記述 | 確認した版 | 根拠・固定する試験 | 対応 |
| --- | --- | --- | --- | --- | --- |
| 1 | 組み込みと**同じ名前**のツールを登録しても、`/reload` でハーネスが抜けると組み込みのツールが同じ名前で戻り、判定なしで動く。`-nbt` でも防げない | 無し | 1.1.0 | [E1](../research/agents/pi-harness-spike.md)、`test_reload_without_harness_leaves_no_tools` | ツールを組み込みに無い名前（`guarded_*`）で登録 |
| 2 | **`-nbt -ne -e builtin:mcp` では `codemode` と `tool_search` が宣言されない。** `exposure` が `codemode` / `deferred` の MCP のツールは `Tool … not found` で呼べない | **食い違う**: `cli.md` は「MCP の拡張が、サーバが要るときに有効にする」とするが、`-ne` では起きない | 1.1.0 | [E6](../research/agents/pi-extension-under-harness.md#記録-e6--2026-10-11)、`test_mcp_tool_without_exposure_is_unreachable_under_the_harness` | `[[mcp]]` の `exposure` を省略すると `direct`（+37 トークン）。`codemode` は `-e builtin:codemode`（+680） |
| 3 | 別の拡張が、ハーネスと**同じ名前のツール**を登録すると、読み込みの失敗（`Tool "x" conflicts with <パス>`）で**起動が止まる**（許可側へは倒れない） | 無し | 1.1.0 | [E5](../research/agents/pi-extension-under-harness.md)、`test_extension_cannot_replace_a_guarded_tool` | 差し替えはできない前提で、拡張を足す |
| 4 | `bash` のツールの結果の `details.truncation.content` に**生の出力**が入る（モデルへは送られないが、セッション・JSON・画面に残る） | `message-types.md` は `BashExecutionMessage`（`!` の直接実行）だけで、ツールの結果の `details` は無し | 1.1.0 | [E3](../research/agents/pi-harness-spike.md)、`test_bash_output_is_redacted_everywhere` | 伏字化を `execute()` の中で `details` まで掛ける |
| 5 | `codemode` の中で `Promise.all` などで並べた呼び出しでは、確認が重なり、先の確認が決着せず（TUI が `Working` のまま）止まる | 無し | 1.1.0 | E3 | ハーネスが確認を 1 件ずつ順に出す |
| 6 | 既定の圧縮は、別名のツールで読み書きしたファイルを拾わない（`readFiles` / `modifiedFiles` が空） | `compaction.md` は `fileOps` とフックを説明するが、別名のツールの扱いは無し | 1.1.0 | [E2](../research/agents/pi-harness-spike.md) | `session_before_compact` で `fileOps` へ足す |
| 7 | 設定と認証を**読むだけ**でも、隣に `.lock` を `mkdir` する。agent の置き場を読み取り専用にすると、設定は無視され、認証は失敗する | 無し | 1.1.0 | [E4](../research/agents/pi-harness-spike.md) | 境界用の agent の置き場を起動ごとに作る |
| 8 | UI の無い起動（`-p`）では、ハーネスの確認（ask）は拒否になる | `ctx.hasUI` は明示（表 A）。**拒否にする判断はハーネスの実装** | 1.1.0 | `test_decisions_reach_the_tools` | ハーネスの設計（公式の挙動ではない） |
| 9 | ツール定義の常駐トークン: 最小の MCP ツール 1 つで約 +37、`codemode` で約 +680（偽のモデルの見積もり） | 無し（`codemode.inlineBudget` の既定は宣言の説明に 3,000 トークンまで） | 1.1.0 | E6 | 入口の選択の目安 |
| 10 | 試験が使う `pi-ai/dist/providers/faux.js` の位置は、インストール方法で変わる（mise・公式インストーラーは兄弟、Windows の npm global は入れ子） | 内部のパスで、公開 API ではない | 1.1.0 | `test/agents/pi/faux.ts` が両方に対応 | パスが変わったら試験が落ちる |
| 11 | Windows の npm global の `pi` は `pi.CMD` で、子の pi を `spawn("pi")` する処理（子エージェント）と、その試験が動かない | 無し | 1.1.0 | Windows で `test_pi_harness.py` の 9 件が失敗 | `pis` は Unix 専用（既知） |

## codemode の扱い

- **スクリプトの API・結果の形・上限・有効化の方法は、公式に明示がある**ので、**ここには写さず、リンクだけ**にする（表 A）。読む先は
  `codemode.md`（スクリプト・グローバル・結果）、`cli.md`（有効化）、`mcp.md`（`exposure` との関係）、`settings.md`（`codemode.mode`・`codemode.inlineBudget`）
- **このリポジトリの条件での挙動は、公式に無いので、表 B に書いた**（2: `pis` では既定で使えない、9: 常駐の +680 トークン、5: 並列の確認が止まる）
- 今は使っていない（検索は skill + CLI、MCP は `direct`）。使うなら、まず表 B の 2・5・9 を読み、入口の選び方（[比較表](pi-harness.md#入口の選び方)）で他の入口と比べる

## 運用

- 新しく pi の挙動に頼るときは、**まず公式の文書を探す**。明示があれば表 A に 1 行（リンクと頼っている所）。無ければ、実測して表 B に書き、**試験で固定する**
- 表 B の項目が、公式の文書で明示されるようになったら、表 A へ移して、ここのノウハウは消す（リンクだけにする）
- 実測の経緯は [research/agents/](../research/index.md)（E1〜E6）、判定の設計は [pi のハーネス](pi-harness.md)
