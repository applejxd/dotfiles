# 配置済みの opencode.json に残るキーと、V1 / V2 のエージェント定義の併用

生成器が配置済みの `~/.config/opencode/opencode.json` に書くとき、宣言から外したキーが残るか。
同じ ID のエージェントを V1 の `agent` と V2 の `agents` の両方に書いたとき、OpenCode がどう
合成するか。[CHG-0018](../../change/0018-opencode-policy-role-split.md) の段 3。

## 記録 E1 — 2026-10-08

- **対象バージョン**: OpenCode v2.0.22
- **環境**: WSL2 (Ubuntu)、基準コミット d5f1e7c

### 問い

CHG-0018 の段 4（全体の規則をプロファイルと policy へ移し、`bypass` 系を V2 へ移す）を
当てたとき、また元に戻したとき、配置済みの `opencode.json` に古い値が残るか。残るなら、
手書きの定義を壊さずに消す方法は何か。

### 事前の予想

[CHG-0017](../../change/0017-builtin-agent-restrictions.md) の「実装・検証」で、宣言を消しても
配置済みのキーが残ることは分かっていた。V1 と V2 の併用は未知。

### 方法・条件

- `scripts/agents/generate.py` の書き出し処理を読んだ
- 公式の移行ガイド（<https://opencode.ai/v2/docs/migrate-v1>）を読んだ
- 最小の試験用の設定（同じ ID を V1 と V2 の両方に書いた版と、V2 だけの版）と、CHG-0018 の
  段 2 の試作に V1 の `bypass` 系を足した版を作り、別ポートのサーバの `/api/agent` と
  `opencode.log` を比べた
- 試作のスクリプト（`.tmp/opencode/chg0018/stage3/proto.py`）で、実際の設定の写しに手書きの
  ダミーのキーを足し、段 4 相当の宣言を当てた結果・元に戻した結果を、今の書き出し方と
  「所有の規則」（下の結果を参照）の 2 通りで比べた。判定は CHG-0018 の段 1 の評価器で比べた

### 結果

今の書き出し方（`generate.py`）:

| キー | 扱い | 段 4 で古い値が残るか |
| --- | --- | --- |
| `permissions` | 毎回丸ごと置き換え | 残らない |
| `experimental.policies` | `provider.use` の statement だけ差し替え、ほかは残す。書くのは `models` があるときだけ | 今の方式で `permission` の statement を足すと、apply のたびに重複して増えた（259 件 → 515 件）。元に戻しても 259 件残った |
| `agent`（V1） | 宣言した ID の宣言したキーだけ上書きし、ほかは残す | `agent.bypass` / `agent.bypass-worker` が丸ごと残った |
| `agents.<id>`（V2） | キー単位で上書き | 元に戻すと `build` / `general` / `compaction` / `bypass` / `bypass-worker` の定義が丸ごと残った |
| `ocs` の設定 | 起動のたびに `agent` / `agents` / `permissions` / `policies` などを置き換える | 残らない |

V1 と V2 の併用:

- 移行ガイドの記述: 「a valid native V2 value takes precedence regardless of JSON key order」、
  「it does not recursively infer formats inside individual agents」
- 同じ ID を両方に書くと、V2 だけの版と実効の定義が完全に一致した。V1 の `color` / `mode` /
  `description` / `permission` は、V2 側に無いキーでも捨てられた。JSON の中の順序を逆にしても
  同じ。V2 で `mode` を書かないと、自作の既定の `primary` になった
- `opencode.log` に ID ごとに `kind=conflict action="retained native value over legacy value"` が出た
- 段 2 の試作に V1 の `bypass` 系を足しても、14 エージェントの実効規則は変わらなかった
- V1 にしか書けないエージェントのキーは見つからなかった（キーバインドは `cli.json` にある）

元に戻したときに残った値の影響:

- 今の書き出し方で段 4 を当ててから元に戻すと、969 件の判定は今と同じだった。ただし残った
  policy が覆い隠しているだけで、残った policy だけを消すと `build` など 5 つで 307 件が deny から
  allow / ask に緩んだ（例: `.ssh/.env.example` の read が allow）

所有の規則（試作）:

- `permissions` は丸ごと置き換える
- `experimental.policies` は action が `permission` / `provider.use` の statement を生成器が持ち、
  ほかは残す
- 宣言した ID と既知の組み込み（`build` / `plan` / `general` / `explore` / `compaction` / `title` /
  `summary`）を管理する ID とする。管理する ID では、生成器が書けるキーのうち今回宣言して
  いないものを消し、宣言しているのと逆の形式（V1 / V2）のエントリは丸ごと消す。`model` など
  ほかのキーと、管理しない ID は残す

| 確認 | 結果 |
| --- | --- |
| 今の宣言で当てたとき | 今の書き出し方も所有の規則も、実際のファイルと完全に一致した |
| 段 4 を当てた結果と、空から作った段 4 の差 | 手書きのダミーのキーだけ |
| 段 4 を 2 回当てたとき | 変化なし |
| 段 4 の判定（969 件） | 段 2 の試作と全エージェントで差 0 |
| 所有の規則を先に入れ、段 4 だけを元に戻したとき | 段 4 を一度も当てなかった場合と JSON が完全に一致した |

### 考察

- V1 と V2 の併用で権限は広がらない。危ないのは逆で、V2 側に一部のキーだけ（例: `model`）の
  エントリがあると、V1 の権限・`mode`・説明が黙って消える
- 古い値が残ると、元に戻した後の判定が残った値に支えられる。部分的に片付けると緩む
- 所有の規則を段 4 より前の別のコミットに入れれば、段 4 を元に戻すだけで元の JSON に戻る
- 状態ファイルで前回の書き出しを覚える方式は、`chezmoi diff` でも生成が動くので外へ書く
  副作用を持てない。元に戻すと読む処理ごと消える

### 次の問い

- グローバルの V1 定義とプロジェクトの V2 定義のように、ファイルをまたいだ併用
- 所有の規則を `generate.py` に実装したときのテスト（2026-10-08 に
  `test/agents/test_generate_opencode_ownership.py` で固定した）
