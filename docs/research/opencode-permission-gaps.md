# OpenCode V2 の permission 適用範囲の穴

> **調査日: 2026-09-21**
> **対象: `opencode v2.0.10`**
>
> 隔離環境（`XDG_CONFIG_HOME` / `XDG_DATA_HOME` を差し替え + `--standalone`）での実測。
> 実環境の `~/.config/opencode/` には触れていない。
>
> **訂正 (2026-09-21)**: 隔離手段の記述は誤り。OpenCode は config dir の
> 決定に `XDG_CONFIG_HOME` を使わない（`OPENCODE_CONFIG_DIR` が正しい）。
> **本記録の結論は有効**（permission をプロジェクト側に置いており、
> global config に依存していないため）。
> 詳細は [試験環境の隔離方法](opencode-test-isolation.md)。

## 0. 本書の用途

既定 `ask` へ移行する設計で、確認回数を減らす最大の手段が
**「シェル経由の読み取りを組み込みツールへ誘導する」**ことだった
（実測で 234 件／755 セグメント）。

その移行先である `read` / `grep` / `glob` が、
`read` の deny ルールと同じ保護を提供するかを確認した。

## 1. 結論

| 検証 | 結果 |
| --- | --- |
| `read` の deny は効くか | **効く** |
| 設定の `deny` は hook を呼ぶか | **呼ばない**（公式記載どおり実証） |
| `grep` は deny 対象の中身を返すか | **返す。保護なし** |
| `glob` は deny 対象を列挙するか | **する。保護なし** |
| `editor.add` のカスタムツールに permission は掛かるか | **掛からない。判定が一切走らない**（ただし `execute.before` でゲートを自作できる） |

**`cat` / `sed -n` → `read` の移行は安全。`grep -n` → `grep` の移行は保護を弱める。**

## 2. 検証環境

```console
proj/
  secret.txt     # CANARY_A1B2C3_LEAKED を含む
  normal.txt
  .opencode/opencode.json
  .opencode/plugins/probe.js
```

```jsonc
// .opencode/opencode.json
{
  "permissions": [
    { "action": "read", "resource": "*secret*", "effect": "deny" }
  ]
}
```

プローブは `permission.evaluate` と `tool.execute.before` を記録するだけで、
判定は変更していない。

## 3. 実測

### `read` は保護される（基準）

```text
結果: {"error":{"type":"permission.rejected","message":"Permission denied: read"}}
```

このときプローブの記録は **0 件**。
公式の「An explicit configured `deny` is final and does not invoke the hook」が
実証された。**静的 deny を置くと hook で代替案を返せない**ことを意味する。

### `grep` は中身を返す

```text
✱ Grep "CANARY" 1 match
/…/proj/secret.txt:
  Line 1: CANARY_A1B2C3_LEAKED
```

プローブの記録:

```json
{"ev":"tool","tool":"grep","input":{"pattern":"CANARY"}}
{"ev":"perm","action":"grep","resources":["CANARY"],"effect":"allow"}
```

`resources` は **検索正規表現のみ**で、検索先パスが入らない。
**ファイルごとの `read` 判定も走らない**（走れば `action:"read"` が記録される）。
結果として、`read` で deny したファイルの**中身が逐語的に返る**。

これは公式の action 一覧の記載と整合する。

> `grep` | Requested regular expression, **not the search path**

### `glob` は deny 対象を列挙する

```text
✱ Glob "*.txt" 2 matches
- /…/proj/normal.txt
- /…/proj/secret.txt
```

```json
{"ev":"perm","action":"glob","resources":["*.txt"],"effect":"allow"}
```

内容は返らないが、**存在とパスは漏れる**。

### カスタムツールは permission をバイパスする

`ctx.tool.transform` の `editor.add` で登録したツールを呼ばせた。

```json
{"ev":"tool","tool":"probe_ping"}
```

**`permission.evaluate` は 0 件。** `--auto` を外しても同じで、
確認プロンプトも出ずに実行された。

> **含意**: プラグインが登録したツールは、**permission の網の外**にある。
> `verify` のようなツールを作れば「無確認で自動実行される」が、
> 同時に**ホスト権限での任意コード実行に一切のゲートが無い**ことも意味する。
> ゲートが要るならツールの `execute` 内に自前で実装するしかない。
>
> **訂正（同日の追加実測）**: 最後の一文は誤り。
> `tool.hook("execute.before")` が実質的なゲートとして機能する。
> [追補: カスタムツールはゲートを自作できる](#追補-カスタムツールはゲートを自作できる同日の追加実測)を参照。

## 4. 設計への影響

### 追補: `grep` / `glob` は hook で保護できる（同日の追加実測）

上記の「未確認」を解消した。**保護は自作できる。**

**入力スキーマ**（`session.hook("context")` から取得）

| ツール | パラメータ |
| --- | --- |
| `grep` | `pattern`, **`path`**, **`include`**, `literal`, `caseSensitive`, `limit` |
| `glob` | `pattern`, **`path`**, `hidden`, `limit` |

`path` の説明は「File or directory to search. **Defaults to the current working
directory.**」。つまり省略時はワークスペース全体が対象になる。

**`tool.execute.before` は検索先パスを持つ**

```json
{"ev":"tool","tool":"grep",
 "input":{"path":"/…/proj/sub","pattern":"CANARY"}}
```

`source.id` による相関も `shell` と同様に成立した。

```json
{"ev":"perm","action":"grep","resources":["CANARY"],
 "recovered":{"tool":"grep","input":{"path":"/…/proj/sub","pattern":"CANARY"}}}
```

保護の手段は 2 つある。

| 手段 | 実測 | 性質 |
| --- | --- | --- |
| A. `permission.hook("evaluate")` で deny | **成功**。`error.message` に理由が届いた | 検索そのものを止める |
| B. `tool.hook("execute.after")` で結果を書き換え | **成功**。秘密を含む行を伏字化できた | 検索は通し、出力だけ濾す |

B の実行例（`e.result` を書き換えた結果、エージェントには伏字だけが届いた）:

```text
grep の結果は以下でした:
[redacted by probe]
`CANARY` のファイルパス・行は返されませんでした。
```

> **注意**: B は**実行後の出力フィルタ**であって、アクセス自体は防いでいない。
> `grep` は読み取り専用なので許容できるが、副作用のあるツールには使えない。
> また実測では直列化した結果に正規表現をかけた粗い実装で、
> 実運用では結果の構造を解析して書き換える必要がある。

**結論**: `grep` / `find` の 51 件も移行できる。
A（事前拒否）は粗いが確実、B（出力濾過）は検索を通しつつ秘密だけ落とせる。
B の方が確認回数を増やさないので自動化には向く。

### 追補: カスタムツールはゲートを自作できる（同日の追加実測）

`editor.add` で登録したツールには `permission.evaluate` が発火しないが、
**`tool.hook("execute.before")` は発火する**。ここが実質的な permission 層になる。

副作用（マーカーファイルの生成）で「本当に実行されたか」を判定した。

| 実験 | 結果 |
| --- | --- |
| A. `execute.before` で例外を投げる | **実行が止まる** |
| B. `execute.before` で `e.input` を書き換える | **書き換えた値がツールへ渡る** |

A の観測は次のとおり。

```text
error.message: "[probe] execute.before から拒否を試みる"
マーカーファイル: 生成されず
プローブ記録: {"ev":"before"} のみ（"executed" が無い）
```

拒否理由がそのままエージェントへ届き、ツール本体は一度も走っていない。

B の観測は次のとおり。

```json
{"ev":"before",  "input":{"mode":"allowed"}}
{"ev":"executed","receivedInput":{"mode":"rewritten"}}
```

生成されたマーカーは `ran-rewritten.txt`、返り値は `ran with mode=rewritten`。
**引数の正規化・制約を hook 側で強制できる。**

| 欲しいこと | 手段 |
| --- | --- |
| 無条件実行を防ぐ | `execute.before` で条件判定 → 例外で拒否 |
| 引数を固定する | `execute.before` で `e.input` を上書き |
| 理由を伝える | 例外メッセージがそのまま届く |
| 失敗時の挙動 | **fail-closed**（例外 = 停止）。permission hook と同じ |

**残る制約が 2 つある。**

1. **「ユーザに確認を出す」手段が見つかっていない。** `execute.before` でできるのは
   通すか例外で止めるかの二択で、`ask` に相当する動作は**未確認**。
   したがってカスタムツールの設計は「条件を満たせば無確認で実行、
   満たさなければ拒否」になる
2. プラグインがロードに失敗すると `execute.before` ごと消えるが、
   **同時にツール自体も登録されない**ので、無ゲートのツールが残ることはない。
   この一点だけは安全側に働く

### 読み取り移行の規模（2 種類の数字を区別する）

ここで扱う数字は 2 つあり、**一致しない**。混同しないこと。

| 用語 | 意味 |
| --- | --- |
| **セグメント数** | シェル呼び出しを `&&` `;` パイプで分割した断片の数。「何回そのコマンドを打ったか」 |
| **確認減少数** | そのうち **既定 ask で確認プロンプトになる** ものの数。「移行すると何回の確認が消えるか」 |

両者がずれるのは、**一部のコマンドが静的 allow リストに載っていて、既に確認なしで通っている**ため。既に通っているものを組み込みツールへ移しても、確認は減らない。

測定時点は 2026-09-21、対象は実セッションのシェル呼び出しを分割した 1,005 セグメント。既定 ask にしたときの確認総数は 959 件（現行の allow 14 件を適用した場合）。

| 移行対象 | セグメント数 | 確認減少数 | ずれる理由 |
| --- | ---: | ---: | --- |
| `cd X && …` → `workdir` | 163 | **163** | 一致（`cd` は allow に無い） |
| 区切り用途の `echo` | 105 | **105** | 一致 |
| `cat`/`sed -n`/`head`/`tail`/`ls` → `read` | 213 | **205** | `wc` が allow にある分だけ減る |
| `grep`/`rg`/`find` → `grep`/`glob` | 70 | **39** | `grep -n` と `find` が **allow にあるので既に無確認** |
| `uv run` などの検証系 → `verify` | 57 | **57** | 一致 |
| 上記以外（その場限りのコマンド） | 397 | 390 | — |

合計すると、5 つの対策で **959 → 390 件**まで減る計算になる。

### 段階 1 の allow 整理で `grep` の効果が上がる

上表の `grep` 行だけ乖離が大きい（70 対 39）のは、現行 allow の
`grep -n` と `find` が効いているため。

このリポジトリは [CHG-0002](../change/0002-opencode-ask-by-default.md) の段階 1 で、
任意コード実行を含む 7 件（`find` / `gcc` / `g++` / `cmake -S` / `cmake --build` /
`uv sync` / `mise run`）を allow から落とす予定である。**落とすと `find` が
ask に変わるため、`grep`/`glob` への移行で減る確認は 39 → 70 件に増える。**

| allow の状態 | 確認総数 | `grep`/`glob` 移行の効果 |
| --- | ---: | ---: |
| 現行（14 件） | 959 | −39 |
| 段階 1 後（6 件） | 990 | **−70** |

allow を絞ると確認総数は 959 → 990 と増えるが、
**その増分は「任意コード実行が無確認で通っていた分」**であり、
本来 ask であるべきものが可視化されただけである。

> **サンプルの注意**: 測定元は `~/.local/share/opencode/opencode.db` で、
> 作業を続けるたびに増える。**件数は測定時点でしか意味を持たない。**
> また調査セッション由来のため `python3 -c` による分析コマンドが多い偏りがある。
> 比率の傾向を見る用途に限ること。

### `grep` / `glob` へ移すときの保護

`grep` / `glob` を使わせるときの保護は、`tool.execute.before` で
`path` / `include` を退避し、`source.id` で相関して判断する。
事前拒否（A）と出力濾過（B）のどちらも実測で成立している。

### 静的 deny と hook は排他になる

`deny` は hook を呼ばないため、次は両立しない。

- 静的 `deny` で確実に止める
- hook で代替案メッセージを返して誘導する

誘導したいなら **既定 `ask` のままにして hook が `deny` へ変える**構成にする。
この場合、プラグインのロード失敗時は `ask` に縮退する（安全側）。

## 再確認すべき情報源

- <https://opencode.ai/v2/docs/permissions>（action 一覧と resource の定義）
- <https://opencode.ai/v2/docs/tools>（`grep` / `glob` の入力スキーマ）
- カスタムツールに permission を掛ける**公式**手段の有無（**未確認**。
  `execute.before` によるゲートは実測で成立しているが、公式の想定用途かは不明）
- `execute.before` から `ask`（ユーザ確認）を出す手段があるか（**未確認**）

[調査記録一覧へ戻る](index.md)
