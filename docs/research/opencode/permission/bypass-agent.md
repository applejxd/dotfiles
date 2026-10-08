# OpenCode V2 のカスタムエージェント（Bypass モード）とキーバインド

> **後続の観測**: 1 章の「キーバインドは V2 では不可」は `opencode.json` についての
> 観測。TUI のキーバインドは `cli.json` の `keybinds` で効く
> （2026-09-22、[キーバインド](../keybinds.md)）。5 章の「`e.effect === "allow"` なら
> 素通り」は、`cd x && git log` のように静的 allow を含む呼び出しまで誘導を
> 素通りさせたため、エージェント名で見分ける方式へ改めた
> （[hook の呼ばれ方 5 章](hook-order.md#5-evaluate-のイベントに-agent-が載る)）。
>
> **後続の観測（2026-10-03）**: `bypass` は「permission 層を丸ごと無効にする」ものでは
> なくなった。全 allow を外し、plugin が `ask` だけを `allow` に書き換える方式が
> 成立し（[実測](bypass-ask-upgrade.md)）、採用した
> （[ADR-0014](../../../adr/0014-bypass-as-ask-upgrade.md)）。以下の本文（特に 0・5 章の
> 「全 allow」「plugin を貫通する」「誘導を素通りする」）は決定当時のまま残している。
>
> **現行の仕様**: [キーバインド](../../../spec/agent-config-generation.md#キーバインド)、
> [plugin 層](../../../spec/agent-config-generation.md#plugin-層-guide-plugin)
>
> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 依頼元は次の 2 つ。どちらも V1 前提の情報だったため、V2 での可否を実測した。
>
> - Zenn「OpenCode が Ctrl+C で不意に終了するのを防ぐ設定方法」（2026-02-27）
> - `open-code.ai/ja/docs/modes`（脚注に「**非公式、参考用**」と明記）

## 0. 結論

| 依頼 | 結果 |
| --- | --- |
| キーバインド変更（`keybinds.app_exit`） | **V2 では不可。**設定から除去される |
| 全ツール許可の Bypass モード | **実装可。**ただし `mode` ではなく `agent` を使う |

## 1. キーバインドは V2 の設定に存在しない

### 実測: 設定に書いても消える

```json
{ "$schema": "https://opencode.ai/config.json",
  "keybinds": { "app_exit": "ctrl+d,<leader>q" } }
```

`opencode api config.get` が返した解決済みの設定:

```json
{"path":".../a/opencode.json","info":{"$schema":"https://opencode.ai/config.json"}}
```

**`keybinds` が丸ごと落ちている。** バイナリには V1 設定から `keybinds`
ノードを除去する JSON 操作コードが含まれており、移行時に捨てる実装に見える。

### 裏付け

- 公式 V2 ドキュメントに **keybinds のページが無い**
  （`/v2/docs/keybinds` は 404。ナビにも項目が無い）
- バイナリに `app_exit` という文字列が**存在しない**
  （`switch_mode` や `leader` は存在する）

V1 のキーバインド機構自体は残骸が残っているが、`app_exit` は V2 の
アクション名ではない。Zenn 記事は V1 向けで、そのまま適用しても効かない。

**未確認**: V2 が別経路（TUI の設定画面など）でキーバインドを持つか。

## 2. Bypass モードは `agent` で実装する

### `mode` は非推奨

`open-code.ai` の記事は `mode` を使う書き方だが、同ページ冒頭に
「モードは agent オプションで設定するようになりました。`mode` は非推奨」
と注記がある。設定スキーマでも `mode` は
`@deprecated Use 'agent' field instead.` になっている。

### 実測: 3 つの書き方を比較

`opencode api config.get` で正規化後の形を見た。

| 入力 | 正規化後 | 判定 |
| --- | --- | --- |
| `agent.bypass.permission = "allow"` | `agents.bypass.permissions = [{action:"*", resource:"*", effect:"allow"}]` | **正解** |
| `agent.bypass.permissions = [...]`（配列） | `agents.bypass.request.body.permissions` へ押し込まれる | 誤り |
| `keybinds` | 消える | — |

**`permission` に文字列 `"allow"` を置くと、OpenCode が
「全 action・全 resource を allow」へ展開する。** これがそのまま
「全ツール許可」になる。配列で書くと別の場所へ解釈されるので使わない。

### 実測: グローバルの deny を上書きできる

グローバル設定で `pip *` を deny している状態で確認した。

```console
$ opencode run --agent bypass 'Run one shell tool call: pip --version'
> bypass · claude-opus-5
$ pip --version
pip 26.0.1 from ...  (exit 0)
```

通常のエージェントでは `Permission denied: shell` になるコマンドが通る。

## 3. セキュリティ上の含意

**bypass は permission 層を丸ごと無効にする。** 影響は shell だけではない。

`{action:"*", resource:"*", effect:"allow"}` は `read` / `edit` にも当たるため、
次の保護が**すべて外れる**。

- `~/.ssh/**` / `*.pem` / `*secret*` などの read deny
- `~/.config/opencode/opencode.json` の write deny（自分の permission を
  書き換えられる状態になる）
- `.git/config` の write deny

つまり bypass 中は「エージェントがホスト権限で何でもできる」。
[段階 1 の設計](../../../change/closed/0002-opencode-ask-by-default.md)が前提にしている
防御は 1 つも残らない。

既定エージェントは変えていないので、**明示的に `--agent bypass` を
選んだときだけ**この状態になる。常用するものではない。

## 4. 実装

単一ソース（`common.toml`）から生成する。生成先は直接編集しない。

```toml
[opencode.agent.bypass]
description = "全ツールを無確認で実行する (permission を全て allow で上書き)"
permission = "allow"
```

`generate.py` に `merge_opencode_agents()` を追加した。`mcp` と同じ方針で、
**common.toml に無いエージェントは残す**（`/agents` などが同じファイルへ
書くため）。

使い方:

```bash
opencode run --agent bypass '<prompt>'
# TUI では Tab または switch_mode のキーバインドで切り替える
```

### モデルは bypass を起動できない（2026-09-22 実測）

**これは設計の土台なので必ず維持する。** `subagent` で起動しようとすると
拒否される。

```text
Agent bypass cannot run as a subagent
```

`mode` を指定していないため primary 扱いになっている。したがって bypass は
**人間だけが選べる操作**で、プロンプトインジェクションで自分から
境界を外すことはできない。

> **`mode = "all"` や `"subagent"` を足した瞬間に穴が開く。**
> モデルが自力で全保護を外せるようになるため、テストで固定する。
>
> 2026-09-29 から `mode = "primary"` を明示している。宣言しないと既存設定の `mode` が
> 残るため（[仕様](../../../spec/agent-config-generation.md#bypass-から呼べる子エージェント)）。

なお `subagent` action には permission 規則が **1 件も無く既定 allow**。
`general` / `explore` は自由に起動できるが、これらは**グローバルの
permission に従う**ので脱出経路にはならない（[出力フィルタと子エージェント](output-filter-and-subagents.md)）。

> **後続の判断（2026-09-29）**: 利用者が `agent.general.permission = "allow"` のように
> 全部 allow へ上書きすると、`mode` を書かなくても子として起動できるまま全部 allow になる。
> 生成側はこれも起動元を絞る対象に数える
> （[仕様](../../../spec/agent-config-generation.md#bypass-から呼べる子エージェント)）。
> 上書き後も `mode` が `subagent` のまま残ることは、実機のエージェント一覧では**未確認**
> （`opencode api agent.list --standalone` は組み込みを含めて空を返した）。
>
> **注記（2026-09-29）**: [ADR-0012](../../../adr/0012-ocs-boundary-for-accidents.md) の方針変更で、
> 生成側が利用者の上書き（組み込みの `general` / `explore` を含む）を数えて起動元を絞る処理は
> 取り下げた。数えるのは `common.toml` の宣言だけ。

## 5. plugin は bypass を貫通する（段階 2 の前提）

### 実測: `allow` でも `permission.evaluate` は発火する

config の `deny` は hook を呼ばずに前段で効く（[plugin API の実測](../plugin/api-probe.md)）。
`allow` も同じなら bypass 中は plugin が無力になるはずだが、**そうではない**。

`{shell, *, ask}` のみの config に bypass を足し、`ZAPTEST` を含む
コマンドを `deny` へ上書きする plugin を置いて比較した（どちらも `--auto`）。

| エージェント | `e.effect`（hook 到達時） | plugin の上書き | 結果 |
| --- | --- | --- | --- |
| 既定 | `ask` | `deny` へ | ブロック |
| `bypass` | **`allow`** | `deny` へ | **ブロック** |

```json
{"cmd":"echo ZAPTEST","effectBefore":"allow","effectAfter":"deny"}
```

つまり **permission 層を全 allow にしても plugin は止められる**。
bypass は「逃げ道」として不完全だった。

### 解決: 「すでに `allow` のものには触らない」

plugin にエージェント識別 API は要らない。**bypass が全て `allow` に
なること自体が信号になる。**

```js
if (e.effect === "allow") return   // bypass はここで素通りする
```

| エージェント | hook 到達時の `effect` | 誘導 hook |
| --- | --- | --- |
| 既定 | ほぼ全て `ask`（allow は 5 件だけ） | 効く |
| `bypass` | 全て `allow` | 素通り |

同じ plugin で両方を実測した。

```console
opencode run --auto            'echo ZAPTEST'   → Blocked（plugin が deny）
opencode run --auto --agent bypass 'echo ZAPTEST'   → ZAPTEST（exit 0）
```

誘導対象（`cd` / `echo` / `cat` / `find` など）は allow の 5 件と
重ならないので、この規約による取りこぼしは無い。

**制約**: config の `deny` は hook が発火しないため、plugin からは
緩められない。ただし bypass はエージェント側の permission が全て `allow`
なので、そもそも global の deny 規則に当たらない（`pip --version` で実測済み）。
plugin だけが上の規約で明示的に譲る形になる。

## 6. bypass からだけ呼べる子エージェント（2026-09-28）

- **対象バージョン**: `opencode v2.0.14`、モデル `github-copilot/claude-haiku-4.5`
- **方法**: 一時的な設定ディレクトリを `OPENCODE_CONFIG_DIR` で渡し、
  `mise run opencode:probe`（実 DB を汚さない）で `--agent` と `--auto` を付けて実行した

### 問い

`bypass` のセッションからだけ、全部 allow の子エージェントを起動できるようにできるか。

### 設定の書き方（`opencode api config.get --standalone` で正規化後を確認）

| 入力 | 正規化後の `agents.bypass-worker.permissions` |
| --- | --- |
| `agent.bypass-worker.permission = { "*": "allow", "task": "deny" }`（V1 のマップ） | `[{*, *, allow}, {subagent, *, deny}]` |
| `agents.bypass-worker.permissions = [...]`（V2 の配列） | 同じ |

V1 の `task` は V2 の `subagent` へ置き換わる。既存の `bypass` と同じ V1 の書き方で足りる。

### 結果

全体の `permissions` の最後に `{subagent, bypass-worker, deny}` を置いた設定で:

| 呼び出し元 | 結果 |
| --- | --- |
| `build`（`--auto`） | `Permission denied: subagent` |
| `bypass` | 起動でき、子が `WORKER_OK` と返した |
| `bypass` から起動した子（さらに `explore` を起動させた） | 子の側では `subagent` ツールが使えるツールの一覧に無かった |

手で書いた設定と、`generate.py` が生成した設定の両方で同じ結果だった。
エージェントの規則は全体の規則の後ろに付き、最後に一致した規則が勝つという
[公式の説明](https://opencode.ai/v2/docs/permissions/)どおり。

### 個別の allow は全体の deny を上書きする（2026-09-28）

- **対象バージョン**: `opencode v2.0.14`、モデル `github-copilot/claude-haiku-4.5`、`opencode_probe`（`--auto`）
- **方法**: 上の設定に、`build` の個別の `permission = { task = "allow" }` を足した

| guide plugin | 呼び出し元 | 結果 |
| --- | --- | --- |
| 無し（対照） | `build` | 起動でき、子が `WORKER_OK` と返した |
| 有り | `build` | `bypass-worker は bypass エージェントからだけ起動できます。` |
| 有り | `bypass` | 起動でき、子が `WORKER_OK` と返した |

全体の最後の `{subagent, bypass-worker, deny}` は、`build` の `{subagent, *, allow}` に
上書きされる（エージェントの規則が後ろに付くため）。plugin の `permission.evaluate` の
deny は、`subagent` の起動も止められる。

### 個別の規則の最後に置く書き方（2026-09-29）

- **対象バージョン**: `opencode v2.0.14`
- **方法**: `OPENCODE_CONFIG_DIR` に一時的な設定を置き、`opencode api config.get --standalone`
  の正規化後を見た。★Orca の端末では `OPENCODE_CONFIG` が実設定を指しているので、
  `env -u OPENCODE_CONFIG` で外してから比べる（外さないと実設定も結合される。
  [試験の隔離 7 章](../test-isolation.md#7-opencode_config_dir-は-global-config-を置き換えるupstream-の不具合)）

V1 のマップは**キーの順に**規則へ展開される。`task` と `subagent` はどちらも `subagent` に
なり、両方あれば両方が順に並ぶ。

| `agent.build` の入力 | 正規化後の `subagent` の規則（順） |
| --- | --- |
| `permission = { task = "allow" }` | `*` allow |
| `permission = { task = { "*" = "allow", "bypass-worker" = "deny" } }` | `*` allow → `bypass-worker` deny |
| `permission = { task = { "bypass-worker" = "deny", "*" = "allow" } }` | `bypass-worker` deny → `*` allow（**負ける**） |
| `permission = { task = "allow", subagent = { "bypass-worker" = "deny" } }` | `*` allow → `bypass-worker` deny |
| `permission = { task = "allow", subagent = "ask" }` | `*` allow → `*` ask |
| `permission = { subagent = "ask", "*" = "allow" }` | `subagent` の `*` ask → **全 action** の `*` allow |
| `permission = "ask"` | 全 action の `*` ask（`{ "*" = "ask" }` と同じ） |
| `tools = { task = true }` | `*` allow（`permission` とキーの順に関係なく**前**に並ぶ） |
| `permission = [ … ]`（配列） | エージェントごと消える |

設定ファイルの間・キーの間の結合も見た。

| 入力 | 正規化後 |
| --- | --- |
| `agent.build` と `agents.build`（V2）の両方 | `agents.build` が**丸ごと置き換える**（`agent.build` の `description` なども消える） |
| `agent.a` と `agents.b` | 両方残る |
| 全体の V1 `permission = { task = "allow" }` と V2 `permissions` | V1 の方が**前**に並ぶ |
| `agent.bypass.mode = "primary"` | そのまま `mode: "primary"` |

`generate.py` の出力（既存の `build` を上の形ごとに与えたもの）を同じ方法で読ませると、
どの形でも `subagent` の規則の最後が `bypass-worker` deny になり、既存の
`agent.bypass.mode = "all"` は `primary` に上書きされていた。

### plugin の起動元の検査と `rules.json` が壊れたとき（2026-09-29）

- **対象バージョン**: `opencode v2.0.14`、モデル `github-copilot/claude-haiku-4.5`、`opencode_probe`（`--auto`、
  `env -u OPENCODE_CONFIG`）
- **方法**: 子として `bypass-worker` を名指しで 1 回起動させた。モデルには一覧に無くても
  呼ぶよう指示した（個別の deny があると、`build` の起動できる子の一覧から `bypass-worker` が
  消え、モデルが呼ぼうとしない）

| 設定 | 呼び出し元 | 結果 |
| --- | --- | --- |
| `generate.py` の出力（plugin 無し、`build` に `task = "allow"`） | `build` | `Permission denied: subagent` |
| 同上 | `bypass` | 起動でき、`WORKER_OK` |
| 個別の deny を外し plugin 有り、`guide` に不正な正規表現 `(` | `build` | `bypass-worker は bypass エージェントからだけ起動できます。` |
| 同上 | `bypass` | 起動でき、`WORKER_OK` |
| 個別の deny を外し plugin 有り、`rules.json` が JSON でない | `build` | `rules.json を読めないため bypass-worker の起動を止めました。…` |
| 同上 | `bypass` | 同じ文言で止まる |
| 同上、plugin は修正前の `index.js`（対照） | `build` | 起動でき、`WORKER_OK`（plugin のロードに失敗して素通り） |

修正前の `index.js` は `rules.json` の読み込みをモジュールの先頭で行っていたので、
壊れていると plugin ごとロードに失敗し、起動元の検査も消えていた
（[plugin API の実測 6 章](../plugin/api-probe.md#6-失敗時の挙動最重要)の fail-open）。

この時点の `index.js` は、一覧が無いときも `general` / `explore` の起動だけは通していた。
全部 allow に上書きされていても見分けられないため、後に例外を外した
（[仕様](../../../spec/agent-config-generation.md#rulesjson-が使えないとき)）。

> **注記（2026-09-29）**: [ADR-0012](../../../adr/0012-ocs-boundary-for-accidents.md) の方針変更で、
> 一覧が読めないときに子エージェントの起動を全部 deny する処理は取り下げた。今は起動元を
> 検査せず、読み込み時に警告するだけ。上の表の「個別の deny」を生成側が差し込む処理も取り下げた。

### V2 の同名のエージェント（2026-09-29）

- **対象バージョン**: `opencode v2.0.14`
- **方法**: 上と同じく `env -u OPENCODE_CONFIG` と一時的な `OPENCODE_CONFIG_DIR` /
  `OPENCODE_DB` で `opencode api config.get --standalone` の正規化後を見た

V2 の `agents.<名前>` は同名の V1 の `agent.<名前>` を丸ごと置き換える（上の表）。
`agent.bypass = { mode = "primary", permission = "allow" }` と
`agents.bypass = { mode = "all", model = "x/y" }` を並べると、正規化後は
`agents.bypass = { mode: "all", model: {…} }` で、**`permissions` も消える**。

V1 の `permission` のキーと V2 の `action` の対応（キーの順に並ぶ。値がマップなら
そのキーが `resource` になる）:

| V1 のキー | V2 の `action` |
| --- | --- |
| `*` / `read` / `edit` / `webfetch` / `shell` / `subagent` | 同じ名前 |
| `bash` | `shell` |
| `task` | `subagent` |

- V2 の `agents.<名前>` の中に V1 の書き方の `permission` を置くと、黙って消える
- V2 の `model` は `"x/y"` の文字列が `{ providerID, model }` へ直る
- `description` / `mode` はそのまま残る

`generate.py` が既存の `agents.bypass = { mode = "all", model = "x/y", permissions = [* ask] }` と
`agents.bypass-worker = { steps = 3 }` に宣言を書いた出力を読ませると、正規化後は
`agents.bypass` が `mode: "primary"`・`permissions: [* allow]`・`model` を保ったまま、
`agents.bypass-worker` が `mode: "subagent"`・`permissions: [* allow, subagent * deny]`・
`steps: 3` になった。同じ出力で、全部 allow に上書きした V1 の `agent.general`（`mode` 無し）は
全体の `{subagent, general, deny}` と `build` の個別の deny の対象に入っていた。

> **注記（2026-09-29）**: [ADR-0012](../../../adr/0012-ocs-boundary-for-accidents.md) の方針変更で、
> 生成側の各エージェントへの deny の差し込み・V2 の `agents` への反映・一覧が読めないときの
> 全 deny は取り下げた。上の記録は取り下げる前の実装の実測として残す。

## 7. bypass の子の入れ替え（2026-09-30）

- **環境**: WSL2 Ubuntu / OpenCode v2.0.14 / `mise run opencode:probe`（`opencode run --standalone`、
  親のモデル `github-copilot/claude-opus-5`）
- **問い**: `bypass` から承認制の `general` / `fleet-worker` を外し、全部 allow の V2 エージェント
  `bypass-fleet-worker` を `bypass` だけから起動できるか。deny した子は一覧から消えるか

### 書き方ごとの拒否（最小の設定）

`bp1`〜`bp3`（primary）から `general` を起動させた。3 つとも `Permission denied: subagent`。

| 名前 | 書き方 |
| --- | --- |
| `bp1` | V1 `permission = { "*" = "allow", task = { "*" = "allow", general = "deny" } }` |
| `bp2` | V1 `permission = { "*" = "allow", subagent = { "*" = "allow", general = "deny" } }` |
| `bp3` | V2 `permissions = [{* * allow}, {subagent general deny}]` |

V2 の子 `pw`（`permissions = [{* * allow}, {subagent * deny}, {shell "git status" deny}]`、
全体に `{subagent pw deny}`）は、`bypass` から起動でき、`echo ok` は確認なしで成功、
`git status` は `Permission denied: shell`。`build` からの起動は `Permission denied: subagent`。

### 生成した設定での確認

作業ツリーの `common.toml` から `generate.py --target opencode-config` で作った
`opencode.json` を `OPENCODE_PROBE_CONFIG` に置いた。

| 親 | `subagent` ツールの一覧 | 起動の結果 |
| --- | --- | --- |
| `bypass` | `bypass-fleet-worker`・`bypass-worker`・`commit`・`explore`・`review` | `general` / `fleet-worker` は `Permission denied: subagent`。`bypass-fleet-worker` は起動でき、`git stash list` は `Permission denied: shell` |
| `build` | `commit`・`explore`・`fleet-worker`・`general`・`review` | `bypass-fleet-worker` は `Permission denied: subagent` |

**deny した子は一覧から消える。** 初回の試験で一覧に全部の子が載り、`bypass` の
入れ子の deny も効かなかったのは、Orca の端末が設定する `OPENCODE_CONFIG`
（実環境の `opencode.json`）が試験用の設定に重なり、`bypass` の `permission = "allow"` が
勝ったため。`opencode_probe.sh` は `OPENCODE_PROBE_CONFIG` を使うとき `OPENCODE_CONFIG` を外す。

## 再確認すべき情報源

- V2 にキーバインド設定の経路があるか（**未確認**）
- `agents` へ正規化される仕様がドキュメント化されているか（**未確認**）
- `permission: "allow"` 以外の文字列（`"ask"` / `"deny"`）の展開（**未検証**）

[調査記録一覧へ戻る](../../index.md)
