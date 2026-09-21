# OpenCode V2 plugin の相関と承認要求の可否（P0-1 / P0-2）

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 隔離環境（`XDG_CONFIG_HOME` / `XDG_DATA_HOME` を差し替え + `--standalone`）での実測。
> [CHG-0002](../change/0002-opencode-ask-by-default.md) の P0-1 / P0-2 を潰すための調査。

## 0. 本書の用途

[CHG-0002](../change/0002-opencode-ask-by-default.md) が抱えていた 2 つの不確実性に決着をつける。

| # | 減らしたい不確実性 |
| --- | --- |
| P0-1 | 並列実行時に cwd を `source.id` へ相関できるか |
| P0-2 | `execute.before` から `ask`（ユーザ確認）を出せるか |

## 1. 結論

| # | 結果 |
| --- | --- |
| **P0-1** | **解決。`shell.create.before` は不要だった。** `tool.execute.before` の `input.workdir` が cwd を持ち、`id` 付きなので相関に迷いがない |
| **P0-2** | **不可能。** plugin から承認要求を作る API が存在しない |

副産物として、**公式ドキュメントに載っている `ctx.permission.rules()` が
2.0.10 には存在しない**ことが判明した。

## 2. P0-1: 並列実行時の相関

### 実測

`background: true` で 3 つのシェル呼び出しを同一ターンで並列実行させ、
`workdir` に `a` / `b` / `c` を指定した。

```text
+   0ms  tool.before   {"id":"call_...cbd4", "cmd":"sleep 2; pwd", "wd":"a"}
+   1ms  tool.before   {"id":"call_...1b6c", "cmd":"sleep 2; pwd", "wd":"b"}
+   1ms  tool.before   {"id":"call_...df92", "cmd":"sleep 2; pwd", "wd":"c"}
+   1ms  shell.create  {"cmd":"sleep 2; pwd", "cwd":"a"}
+   2ms  shell.create  {"cmd":"sleep 2; pwd", "cwd":"b"}
+   2ms  shell.create  {"cmd":"sleep 2; pwd", "cwd":"c"}
+  46ms  perm          {"srcId":"call_...cbd4", "resources":["sleep 2","pwd"]}
+  48ms  perm          {"srcId":"call_...1b6c", "resources":["sleep 2","pwd"]}
+  49ms  perm          {"srcId":"call_...df92", "resources":["sleep 2","pwd"]}
```

イベントは**呼び出し単位ではなくフェーズ単位でまとまる**。
3 件の `tool.before` が出揃ってから `shell.create` が 3 件、
その後 `perm` が 3 件という順序になった。

したがって「直前に観測した `shell.create` の cwd を使う」という実装は
**誤った値を掴む**。`perm(a)` の時点で直近の `shell.create` は `c` である。

### 解決: `shell.create.before` を使わない

`tool.execute.before` の `input` に `workdir` が含まれていた。

```json
{"ev":"tool.before","id":"call_...cbd4","cmd":"sleep 2; pwd","wd":"a"}
```

`tool.execute.before` は `id` を持ち、`permission.evaluate` の `source.id` と
一致する（既に実測済み）。**cwd と id が同じイベントで手に入るので、
`shell.create.before` との突き合わせ自体が不要になる。**

`workdir` を指定しない場合も曖昧さは無い。

```json
{"ev":"tool.before","id":"call_...4311","cmd":"pwd","wd":null}
{"ev":"shell.create","cmd":"pwd","cwd":"/…/.tmp/p0/proj"}
```

`workdir` が `null` のとき、実際の cwd はセッションのディレクトリになった。
つまり次の規則で cwd が一意に決まる。

| `input.workdir` | 実際の cwd |
| --- | --- |
| 指定あり | その値 |
| `null` | セッションのディレクトリ（`ctx.location.directory`） |

### 設計上の含意

この解決は「コマンド内の `cd` を禁止する」という方針と**噛み合っている**。

`cd X && Y` を許すと、`Y` の実効 cwd は `input.workdir` からは分からない。
`cd` を deny して `workdir` へ誘導すれば、cwd は常に
`tool.execute.before` から id 付きで取れる。

つまり [CHG-0002](../change/0002-opencode-ask-by-default.md) 段階 2 の
`cd` 誘導は、確認回数を減らすだけでなく **cwd 相関を成立させる前提**でもある。

## 3. P0-2: plugin から承認要求を出せるか

### 実測: API 表面の列挙

`setup(ctx)` の中で `ctx` を再帰的に走査し、実際のメンバを書き出した。

```js
function surface(obj, depth = 0, path = "ctx") { /* Object.keys を再帰 */ }
writeFileSync(process.env.API_OUT, surface(ctx).join("\n"))
```

承認に関係しうるメンバは次だけだった。

```text
ctx.permission.hook   : function
ctx.permission.list   : function
ctx.permission.get    : function
ctx.permission.reply  : function
ctx.session.prompt    : function
```

`ctx.tool` も 4 つだけで、permission を結び付ける口は無い。

```text
ctx.tool.reload / list / transform / hook
```

`question` / `confirm` / `approve` / `request` に相当するメンバは
**第 2 階層まで走査して 1 件も存在しなかった**。

### 判定

`list` / `get` / `reply` は**既にある pending request を操作する** API であり、
新しい承認要求を**作る**手段ではない。`ctx.session.prompt` は
ユーザープロンプトの投入であって承認要求ではない。

したがって **plugin から `ask` を出すことはできない**。
`tool.execute.before` でできるのは「通す」か「例外で止める」の二択のままである。

### 副産物: `ctx.permission.rules()` が存在しない

公式の plugin ガイドには次の記載がある。

> Replace the session-scoped permission rules. They are evaluated after the
> agent's rules, and the last matching rule wins.
>
> ```ts
> await ctx.permission.rules({ sessionID, permissions: [...] })
> ```

しかし **2.0.10 の `ctx.permission` に `rules` は無い**。

```text
ctx.permission.hook / list / get / reply
```

これは [CHG-0002](../change/0002-opencode-ask-by-default.md) 段階 4 の候補
「session スコープの事前宣言」が**現時点では実装できない**ことを意味する。
ドキュメントが先行しているのか、別経路があるのかは**未確認**。

## 4. CHG-0002 への反映

| 項目 | 変更 |
| --- | --- |
| P0-1 | 決着。`shell.create.before` を使わない設計にする |
| P0-2 | 決着（否定）。カスタムツールは「無確認で実行して安全な設計にする」か「作らない」の二択 |
| 段階 2 | `cd` 誘導の位置づけを「確認削減」から「確認削減 + cwd 相関の前提」へ格上げ |
| 段階 4 | session rules 案は `ctx.permission.rules()` 不在のため**保留**に変更 |

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/build/plugins>（`ctx.permission.rules` の記載と実装の乖離）
- plugin から承認要求を作る公式手段が追加されるか（**未確認**）

[調査記録一覧へ戻る](index.md)
