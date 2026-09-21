# OpenCode V2 の ask と並列バッチ、permission.reply の実測（P1-4）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 隔離環境（`XDG_CONFIG_HOME` / `XDG_DATA_HOME` を差し替え + `--standalone`）
> での実測。実環境の `~/.config/opencode/` は無傷。
> [CHG-0002](../change/0002-opencode-ask-by-default.md) の P1-4 を潰すための調査。

## 0. 本書の用途

[allow の費用対効果と plugin ゲート](opencode-shell-allow-and-plugin-gate.md)
で、並列バッチ内の 1 件が `ask` に落ちるとステップ全体が中断する現象を
観測した。対話モードでも同じかが未確認だったため、原因を切り分ける。

## 1. 結論

**前提が誤っていた。`ask` は並列バッチを壊さない。壊すのは「拒否」である。**

| 事象 | 並列バッチへの影響 |
| --- | --- |
| 承認待ち（保留） | **無害。** 兄弟は待たされずに実行され、保留分も後から解決する |
| 承認 | 無害 |
| **拒否** | **ステップ全体が中断**し、兄弟の呼び出しも巻き添えで止まる |

副産物として `ctx.permission.reply()` のスキーマと `ctx.event.subscribe()` の
形を確定した。これにより **TTY 無しで「人が承認した」状態を作れる**。

## 2. ask は並列を壊さない

### 方法

`permission.evaluate` の hook を async にして、特定のコマンドだけ 4 秒
待たせた。「人が悩んでいる」状態の代用である。

```js
await ctx.permission.hook("evaluate", async (e) => {
  if (e.action !== "shell") return
  if (e.resources.join(" ").includes("SLOW")) await sleep(4000)
  e.effect = "allow"
})
```

同一ターンで 3 件の shell を並列に出させた。

### 結果

```text
+ 4183ms  allow       echo ONE
+ 4185ms  slow-start  echo SLOW
+ 4187ms  allow       echo THREE
+ 8186ms  slow-end    echo SLOW
+ 8186ms  allow       echo SLOW
```

```text
Call 1 (echo ONE):   ONE,   exit 0
Call 2 (echo SLOW):  SLOW,  exit 0
Call 3 (echo THREE): THREE, exit 0
```

**3 件とも成功した。** `ONE` と `THREE` は `SLOW` の解決を待たずに実行され、
`SLOW` も 4 秒後に通った。判定の遅延は兄弟をブロックも中断もしない。

## 3. 巻き添えの原因は拒否

`ctx.event.subscribe()` で観測したイベント列。

```text
permission.asked
permission.replied
session.tool.failed
session.step.failed
session.execution.interrupted
```

`session.execution.interrupted` が、前回観測した `Step interrupted` の実体。
**拒否（`permission.replied`）が起点**で、そこから step の失敗を経て
実行全体が中断している。

対話モードでも拒否すれば同じ経路を通ると考えられる（**推測**）。ただし
それは期待動作であり、設計上のリスクではない。

## 4. `ctx.permission.reply()` のスキーマ

公式ドキュメントに記載が見当たらないため、`SchemaError` が欠けているキー名を
1 つずつ返す性質を使って段階的に特定した。

```js
// permission.asked の data から取る
// { id: "per_…", sessionID: "ses_…", action, resources, save, source }

await ctx.permission.reply({
  sessionID,          // 必須
  requestID,          // 必須。per_… （permissionID ではない）
  decision: "once",   // 必須。response ではない
})
```

到達した誤りの列は次のとおり。

| 渡した引数 | エラー |
| --- | --- |
| `{}` | `Missing key at ["sessionID"]` |
| `{sessionID}` | `Missing key at ["requestID"]` |
| `{sessionID, permissionID, response}` | `Missing key at ["requestID"]` |
| `{sessionID, requestID}` | `Missing key at ["decision"]` |
| `{sessionID, requestID, decision:"once"}` | 受理 |

`ctx.event.subscribe()` は引数を取らず **async iterator** を返す。
コールバックを渡す形ではない。

```js
for await (const e of ctx.event.subscribe()) {
  if (e.type === "permission.asked") { /* e.data */ }
}
```

`permission.asked` / `permission.replied` を含め、`session.tool.called` や
`session.execution.interrupted` など多数のイベントが流れる。

### P0-2 への補足

[相関と承認要求の可否](opencode-plugin-correlation.md)で
「plugin から承認要求を**作る** API は無い」と結論した。これは有効なまま
だが、**既にある要求に答えることはできる**という補足が付く。

ただし `opencode run` では組み込みの auto-reject が先に走るため、
plugin の `reply` は実運用では競り負ける。テスト用途に限られる。

## 5. 設計への含意: 「曖昧なら ask」は対話専用

`ask` の行方は実行モードで変わる。

| 実行 | `ask` の行方 | 並列バッチ |
| --- | --- | --- |
| 対話 | ユーザが答える | 承認なら無傷 |
| `opencode run --auto` | **自動承認** | 無傷 |
| `opencode run`（`--auto` なし） | **自動拒否** | **全滅** |

`--auto` のヘルプは「Auto-approve permissions that are not explicitly denied」。
つまり**自動実行では plugin の `deny` だけが効き、`ask` は素通りする**。

これは CHG-0002 段階 2 の `find` 選別器の 3 分岐目
（`$` やバッククォートを含むなら `ask` へ落とす）に直撃する。

| 文脈 | 3 分岐目の実効 |
| --- | --- |
| 対話利用 | 意図どおり。ユーザに判断が出る |
| `--auto` の自動実行 | **自動承認される。**安全弁にならない |
| `--auto` なしの自動実行 | バッチごと落ちる |

**自動実行で確実に止めたいものは `deny` に倒す必要がある。**
Copilot の hook の `ask` が自動承認されるバグ（github/copilot-cli#3590）と
同じ構図が、OpenCode では仕様として存在する。

## 6. CHG-0002 への反映

| 項目 | 内容 |
| --- | --- |
| P1-4 | 決着。`ask` は並列を壊さない。壊すのは拒否で、これは期待動作 |
| 段階 2 | `find` 選別器の 3 分岐目に「対話専用」の注記を付ける |
| 段階 2 | 自動実行で止めたいものは `ask` ではなく `deny` に倒す |

## 再確認すべき情報源

- 対話モードでの拒否が同じ経路を通るか（**推測のまま**。実機で未確認）
- `ctx.permission.reply()` の `decision` に `once` 以外の値があるか
  （`always` / `reject` は未検証）
- <https://opencode.ai/v2/docs/build/plugins>（`permission.reply` の記載追加）

[調査記録一覧へ戻る](index.md)
