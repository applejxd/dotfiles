# OpenCode V2 の出力フィルタと子エージェント（段階 2 の前提調査）

> **調査日: 2026-09-21 / 2026-09-22**
> **対象: `opencode v2.0.10`**
>
> [CHG-0002](../change/0002-opencode-ask-by-default.md) の調査項目
> P2-1 〜 P2-4。段階 2 の目的を「確認削減」から「自動実行で効く穴塞ぎ」へ
> 振り直したのに伴い、その成立条件を確かめた。

## 0. 結論

| # | 問い | 結果 |
| --- | --- | --- |
| P2-1 | `execute.after` で shell の出力を書き換えられるか | **できる** |
| P2-2 | 伏字化の対象はパスで判定するか内容で判定するか | **どちらも境界にならない** |
| P2-3 | `continue_loop_on_deny` の既定と効果 | `false` でもループは続いた |
| P2-4 | 子エージェントの権限と `primary_tools` | 権限は**親の部分集合ではなく共通の規則が当たる** |

**P2-1 は成立したが、P2-2 で評価基準 2 が満たせないことが分かった。**

## 1. P2-1: `execute.after` は shell の出力を書き換えられる

`grep` ツールでは[実証済み](opencode-permission-gaps.md)だったが、
`shell` でも成立する。

### イベントの形

```json
{"keys":["tool","sessionID","agent","messageID","id","input","status","result"],
 "result": {"output": "object", "content": "array(2)", "metadata": "object"}}
```

**本体は `result.content`** で、`[{type:"text", text}]` の配列。
`result.output` は文字列ではない（オブジェクト）。伏字化は
`content[].text` を書き換える。

```js
if (Array.isArray(r.content)) {
  for (const c of r.content) {
    if (c && typeof c.text === "string") c.text = c.text.replace(PATTERN, "[伏字]")
  }
}
```

### 難読化した形でも届く

カナリア文字列を含むファイルを 2 通りで読ませた。

| コマンド | モデルが受け取った内容 |
| --- | --- |
| `cat canary.txt` | `value=[伏字]` |
| `F=canary.txt; cat $F` | `value=[伏字]` |

**出力に対して働くので、コマンド文字列の難読化は効かない。**
実行前の文字列検査（クォート・変数で回避される）との決定的な違い。

> **実装上の罠**: 判定に `/…/g` 付きの正規表現で `.test()` を使わないこと。
> `lastIndex` が残るため交互に `false` を返し、伏字化が半分すり抜ける。
> 最初の実測はこれで誤った結論（「効かない」）を出しかけた。

## 2. P2-2: 符号化で内容照合はすり抜ける

同じカナリアを符号化・変換して読ませた。

| コマンド | 出力 | 伏字化 |
| --- | --- | --- |
| `base64 -w0 canary.txt` | `dXNlcj1kZW1vCnZhbHVlPUNBTkFSWS1NQVJLRVItMTIzNDUK` | **すり抜け** |
| `tr A-Z a-z < canary.txt` | `value=canary-marker-12345` | **すり抜け** |

モデルは出力から元の内容を復元して要約に書いた。

### 含意

2 つの手段はどちらも一方向にしか効かない。

| 手段 | 効く | すり抜ける |
| --- | --- | --- |
| 実行前のコマンド検査（パス基準） | 素直な `cat ~/.ssh/id_rsa` | クォート・変数・子プロセス |
| 実行後の出力検査（内容基準） | 難読化したコマンド | 符号化・変換した出力 |

**組み合わせても境界にはならない。** 迂回の費用を上げるだけ。

これは実装の粗さではなく、permission 層が shell の内側を見ないことに
由来する。本当の境界には OS レベルの隔離（sandbox）が要るが、
OpenCode V2 には無い。

### 妥当な位置づけ

**事故と素朴なプロンプトインジェクションに対する安全網**であって、
意図的な持ち出しへの防御ではない。評価基準 2 の「難読化した同等の形でも
遮断」は**達成できない**ので、基準の書き換えが要る。

## 3. P2-3: `continue_loop_on_deny`

`experimental.continue_loop_on_deny: false` を明示しても、plugin の
`deny` 後にエージェントはループを続け、メッセージの代替案どおり
別のコマンドを実行して完了した（`--auto` 実行）。

```text
echo ZAPTEST → deny（「代わりに echo FALLBACK を実行してください」）
             → エージェントが echo FALLBACK を実行して報告
```

**`--auto` + plugin の deny では設定の有無で差が出ない。**
設定を入れる必要は無い。

**未検証**: `--auto` なしの自動拒否パス（以前 `Step interrupted` で
並列バッチごと落ちた経路）に効くかどうか。

## 4. P2-4: 子エージェントは共通の permission に従う

`subagent` ツールで子エージェントを起動させ、hook を観測した。

```json
{"where":"before",  "tool":"subagent","agent":"build",  "cmd":"Run touch command"}
{"where":"evaluate","action":"subagent","agent":"build","effect":"allow","res":["general"]}
{"where":"before",  "tool":"shell",   "agent":"general","cmd":"touch SUBAGENT_RAN.txt"}
{"where":"evaluate","action":"shell", "agent":"general","effect":"ask","res":["touch SUBAGENT_RAN.txt"]}
```

分かったことが 3 つある。

- **子エージェントの起動自体が permission の対象**。`action: "subagent"`、
  `resource` は起動する**エージェント名**（`general`）。名前単位で
  deny できる
- **hook は子エージェントの呼び出しにも発火し、`agent` に名前が入る**。
  誘導・伏字化は子エージェントにも等しく効く
- **グローバルの `{shell, *, ask}` が子エージェントにも当たった**。
  権限は親の部分集合ではなく、同じ規則が適用される

`bypass` のような緩いエージェントを子として起動された場合の扱いは
**未検証**（`subagent` の resource で名前を deny できるので、
そこで止めるのが素直）。

## 5. 段階 2 への影響

- 伏字化（`execute.after`）は**採用する**。安全網として費用が低く、
  確認回数を増やさない
- ただし**境界として宣伝しない**。評価基準 2 を「素直な形の事故を
  止められること」へ書き換える
- 子エージェントに個別の手当ては要らない。`subagent` の resource で
  起動できるエージェントを絞るのは別途検討する

## 6. `primary_tools` は効果を確認できていない

`experimental.primary_tools: ["shell"]`（primary エージェント限定にする
指定）を入れても、**子エージェントの `shell` 呼び出しは permission 判定まで
到達した**。ただし実行されたかは確認できていない。

この設定を入れた 2 回と、**外した対照の 1 回**のいずれも、子エージェントの
shell 判定の直後に `Error: Transport` で落ち、痕跡ファイルも作られなかった。

| 設定 | 到達点 | 痕跡 | 終了 |
| --- | --- | --- | --- |
| `primary_tools: ["shell"]` | `evaluate`（`ask`） | 無し | `Transport` |
| 設定なし（対照） | `evaluate`（`ask`） | 無し | `Transport` |

**`primary_tools` は原因ではない。** 子エージェントを起動する実行そのものが
隔離環境（`opencode_probe.sh`）で完走しない。probe は `OPENCODE_DB` を
差し替えるため、子セッションの生成まわりが影響を受けている可能性が高い
（[試験環境の隔離方法](opencode-test-isolation.md)）。

hook の観測（セクション 4）は判定までで成立しているので結論は変わらない。
`primary_tools` の意味は**未確認のまま**で、**頼らない**。

## 再確認すべき情報源

- `experimental.primary_tools` の意味（**効果を確認できず**。セクション 6）
- `--auto` なしの拒否パスに `continue_loop_on_deny` が効くか（**未検証**）
- `result.content` の構造が将来変わらないか（**未追跡**）

[調査記録一覧へ戻る](index.md)
