# mvdan-sh (同梱)

bash の確認画面で、コマンドを手順に解きほぐして見せるための構文解析器。**表示専用で、権限の判定には使わない。**
使い方と方針は [確認画面の手順の一覧](../../../../../../docs/spec/guard/pi-extensions.md#確認画面の手順の一覧)。

| 項目 | 値 |
| --- | --- |
| パッケージ | `mvdan-sh` 0.10.1（mvdan/sh の GopherJS 版） |
| 取得元 | <https://www.npmjs.com/package/mvdan-sh> |
| ファイル | `index.js`（1505122 バイト） |
| sha256 | `2b613c6ddf9ff8ba530e3d2e30a1c34a7b146abafa8408e18a9b8cdd771d0f2c` |
| ライセンス | BSD-3-Clause（`LICENSE`） |

## 更新の手順

- 版を固定して取り込み、上の版・バイト数・sha256 をこの表に書き直す。**期待値は `judge/syntax.ts` の `MVDAN_SHA256`・`MVDAN_BYTES` にもある。
  この表・TS の定数・`index.js` の三者が一致すること**（試験が固定する）。
- `index.js` は minified。pre-commit の整形で書き換えさせない（書き換わると sha256 が変わる）。
- 更新したら、`test/agents/test_pi_explain.py` で構文木の形（フィールド名）が変わっていないことを確かめる。
