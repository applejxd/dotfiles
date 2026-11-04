# mvdan-sh の構文木の実型（Plan の fixture）

`judge/plan.ts`（[Plan](../../spec/guard/pi-decide.md#解析結果-plan-g1a)）を作るときに、同梱の mvdan-sh（`harness/vendor/mvdan-sh`）の
構文木で実際に確かめた型と挙動。要約は `test/agents/golden/plan_ast_fixtures.json`（`test_pi_plan_literal.py` が照合。再生成は `UPDATE_PLAN_FIXTURES=1`）。

## 実型で分かったこと

- フィールドは `Reflect.ownKeys` でしか取れない（`for…in` と `Object.keys` は空）。
- `Lit.Value` は、引用外でも二重引用符内でも、バックスラッシュを残した原文のまま。`*`・`{a,b}`・`~/x`・`a=~` も `Lit`。
  literal の判定（表 L）は `Lit` かどうかでは決められず、plan.ts が行う。`\⏎` は解析器が除去する。
- `$'…'` は `SglQuoted{Dollar:true}`、`$"…"` は `DblQuoted{Dollar:true}`。復号せず unk（ansi-c・locale）にする。
- 単語の部品: `${x:-y}` は `ParamExp`、`$((…))`・`$[…]` は `ArithmExp`、`<(…)` は `ProcSubst`、`@(…)` は `ExtGlob`。
- `time` は `TimeClause`（`CallExpr` の語ではない）。`declare x` は `DeclClause` の `Assign{Naked}`。
- コメントは既定の解析器が捨てる。`KeepComments(true)` を付けた解析器で `Comment` ノードが取れる（`complex` の判定に要る）。
- 構文エラーの例外メッセージは `[object Object]`（読める文言にならない）。
- 位置（`Pos().Offset()`）は UTF-8 のバイト位置。文字数ではない。

## 境界を越える解釈の差（先に拒否する根拠）

- CR は空白として扱われる（実 bash と違う）。NUL は黙って落ちる。VT（`\v`）は語の文字になる。
  → 構文木に渡す前に、`\t` `\n` 以外の C0 を `ctl` で失敗にする。

## 演算子の番号（mvdan-sh 0.10.1。`test_pi_plan_literal.py` で固定）

| 種別 | 番号 |
| --- | --- |
| `BinaryCmd.Op` | `&&`=10、`\|\|`=11、`\|`=12、`\|&`=13 |
| Redirect の Op | `>`=54、`>>`=55、`<`=56、`<>`=57、`<&`=58、`>&`=59、`>\|`=60、`<<`=61、`<<-`=62、`<<<`=63、`&>`=64、`&>>`=65 |

版を上げたら、この表・試験・plan.ts の定数（`OP_AND` ほか）を同時に見直す。
