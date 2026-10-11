# ハーネス付きの pi（`pis`）へ、明示の `-e` で拡張を足してよいか

<!-- 現在の総合判断は docs/change/0020-pi-migration.md と docs/spec/pi-harness.md が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E5 — 2026-10-11

- **対象バージョン**: pi 1.1.0（npm の global。`C:\Users\<user>\AppData\Roaming\npm`）
- **環境**: Windows 11 Pro（ビルド 26300）、WSL ではない。作業ツリーはコミット 4fd2373。
  Unix でも通る見込みだが、**Unix では未実施**

### 結論

- **`-ne` を付けても、明示した `-e` の拡張は読み込まれ、拡張のツールはモデルに宣言される。**
- **拡張のツールも、ハーネスの判定を通る。** 役割（`[pi.profiles.*].tools`）に無い名前は、bypass でも拒否される。
  役割に載せても、規則が無ければ既定の確認になり、UI の無い起動では拒否になる（MCP のツールと同じ扱い）
- **拡張のツールの結果は、ハーネスの `tool_result` が秘密を伏せる。** 生の秘密は出力に残らなかった
- **ハーネスと同じ名前（`guarded_bash` など）のツールを、後から拡張が登録することはできない。**
  pi が読み込みの失敗（`Tool "guarded_bash" conflicts with …`）で起動を止める。許可側へは倒れない。
  判定の後に入力を書き換える拡張を併用しても、`touch` は実行されなかった
- 宣言するツールが 1 つ増えると、入力のトークンは約 36 増えた（偽のモデルの見積もり。最小のスキーマ）
- **ただし拡張は、読み込まれた時点で任意のコードを実行できる**（判定を通るのはツールの呼び出しだけで、
  拡張の中の処理は囲われない）。足してよいのは、**自分で書いた、または審査した拡張**に限る

### 問い

[`pis`](../../spec/pi-harness.md#起動) は `-ne` で、ほかの拡張を読まない。ただし pi の文書（`cli.md`）では、
`-ne` でも明示した `-e` は読まれる。検索のような入口を、拡張として足すことが現実的かを確かめる。

1. `-ne` のまま、明示の `-e` で足した拡張は読まれるか。そのツールはモデルに見えるか
2. 拡張のツールは、ハーネスの判定と伏字化を通るか
3. 拡張が、ハーネスのツールを差し替えたり、判定の後に入力を書き換えたりして、判定をすり抜けられないか

### 事前の予想

1 は読まれると予想した（文書どおり）。2 は、MCP のツールと同様に判定を通ると予想した。
3 は、E1（実行時の再判定）で書き換えは防げるが、同名のツールの差し替えは分からなかった（**予想できず**）。

### 方法・条件

`test/agents/test_pi_harness.py` と同じ仕組み（偽のモデル `faux`、使い捨ての agent 置き場、`rules.json`）で、
起動の形は `pi -p --no-session --model faux/spike -nbt -ne -e builtin:mcp -e <ハーネス> -e ext_tool.ts -e faux.ts`。

| ファイル | 役割 |
| --- | --- |
| `test/agents/pi/ext_tool.ts` | 試験用の拡張。ツール `ext_search`（実行の印を作り、秘密入りの結果を返す）と、同名ツールの差し替え（`EXT_OVERRIDE`） |
| `test/agents/pi/mutator.ts` | 既存。`tool_call` で bash のコマンドを書き換える |
| `test/agents/test_pi_harness_extensions.py` | 上の観測を 3 件の試験にしたもの |

役割の `tools` の判定は、`rules.json` ではなく、判定器（`decide.py`）が読む `common.toml` で行われる。
試験では、描画した `common.toml` の複製に `ext_search` を足し、`AGENTS_CONFIG_DIR` で差し替えた。

Windows で回すには、判定器が `python3` を呼ぶので、`python3.exe` を PATH に置き（venv の `python.exe` の複製）、
`PYTHONUTF8=1` を付ける。`test/agents/pi/faux.ts` は、npm の global の入れ子の置き方（`pi-coding-agent/node_modules/@earendil-works/pi-ai`）にも対応させた。

### 結果

| # | 操作 | 結果 |
| --- | --- | --- |
| X1 | 明示の `-e` で拡張を足す | 読まれた（印のファイルができた）。`TOOLS=["ext_search","guarded_bash",…]` に出た |
| X2 | 役割に無い `ext_search` を呼ぶ | `役割 'implementer' は ext_search を使えない`。実行の印は無い。bypass でも同じ |
| X3 | `rules.json` の `profile_tools` に足す | **効かない**。役割の判定は `common.toml` の `tools` を読む（`decide.py`）。`profile_tools` は「モデルに見せるか」だけ |
| X4 | `common.toml` の `tools` に足して呼ぶ（UI なし） | `not approved: どの規則にも当たらない (役割 'implementer' の既定)`。実行の印は無い |
| X5 | 同じ設定で bypass、JSON | 実行された。結果の `password = "…"` が `[伏字:代入された秘密]` になり、生の秘密は出力に無い |
| X6 | 拡張が `guarded_bash` を登録し、`mutator.ts` で `touch` に書き換える | 読み込みの失敗で起動が止まった（`Tool "guarded_bash" conflicts with …`、終了コード 1）。`touch` は実行されない |
| X7 | 入力トークン（偽のモデルの見積もり） | 拡張なし 2227、`ext_search` あり 2263（+36） |

Windows で回した既存のハーネスの試験は、40 件中 30 件が通った（shim と UTF-8 の設定のあと）。
残りの 9 件は、子エージェント（`pi.CMD` を `spawn` する）、`python3` の大きな出力、シェルの `pis`、Orca の拡張の試験で、
**この作業の対象外**（Windows 固有の事情）。

### 考察

- 拡張を足すことは**技術的にも、判定の面でも成立する**。判定は MCP と同じ形で効き、同名のツールの差し替えは pi が止める
- 守れないのは、拡張自身の**読み込み時の処理**と、拡張のツールの**中身**。ハーネスは呼び出しの可否と結果の伏字化だけを見る。
  拡張を足すなら、コードを審査し、必要なら `pis --boundary`（Fence）で囲う
- 足す手順の案: (1) 拡張を自分で書く、または審査する (2) ツール名を `[pi.profiles.*].tools` に足す
  (3) 確認なしで通すなら `[pi.*]` の規則に足す (4) `pis` の起動引数に `-e` を足す（Orca の拡張と同じ形。印で絞る）
- 事前の予想が外れた点は無い。3 の「同名ツールの差し替え」は、pi が拒否することが分かった

### 次の問い

- Unix（WSL2 / Ubuntu）での再現。この環境では、子エージェント・`pis`・境界の試験が回らない
- 拡張を `pis` の既定の起動に足す場合の、審査と更新の手順
