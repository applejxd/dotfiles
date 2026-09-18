---
name: checkpoint
description: "コンテキスト圧縮を跨いで作業文脈を失わないよう、復帰用の記録を保存する。「checkpoint して」「引き継ぎを作って」「文脈を保存して」と言われたとき、逼迫を促されたとき、手動で圧縮する前に使う。"
allowed-tools: Read, Edit, Bash, Glob, Grep
---

# checkpoint スキル

**先に保存し、後から文書化する。** 記憶を失う前の保存を、判断の要る作業の後ろに置かない。

> `context: fork` を付けてはいけない。あれは会話の fork ではなく新規コンテキストの
> サブエージェントで、棚卸しに要る親の会話を見られない。

## 起動モードで実行範囲を決める

| 言われ方 | やること |
| --- | --- |
| 「checkpoint して」/ hook の促し | **A1 だけ** |
| 「引き継ぎを作って」/「文脈を保存して」 | A1 |
| 「現状を教えて」 | 読むだけ。書かない |

**子エージェントの中では何もしない。** 親の記録は親だけが書く。

## A1: 実行状態の保存

```bash
CP=~/.claude/skills/checkpoint/scripts/checkpoint.py
uv run --no-project python "$CP" paths --session "<セッションID>" --ensure-ignored
```

1. 上で保存先を解決する。**固定パスを自分で組み立てない**
   （保存先はセッション別。別セッションの記録を読む事故を防ぐ）
2. **要求境界を決める** — hook に促された場合は**その要求の境界を引き継ぐ**。
   取り直すと、要求時とスキル起動時がずれて永久に一致しない。
   促しが無い手動起動なら、この時点を境界にする
3. `references/checkpoint-template.md` の 6 節を埋める。
   `covered_through` に 2 の境界を書く
4. 書く:

   ```bash
   uv run --no-project python "$CP" write <checkpoint パス> --keep-prev <prev パス>
   ```

5. 通るまで直す:

   ```bash
   uv run --no-project python "$CP" lint <checkpoint パス> --structure
   ```

## 書くときの原則

復帰試験（段 3）で実測した、外すと復帰できなくなる点を含む。

- `## Evidence` は**実行したコマンドと結果**だけ。推測を書かない
- `## Next` は**次の 1 手**だけ。ただし「何を」で止めず**「どうやって」**まで書く
  （手順と合格条件が無いと、読み手は着手できない）
- **略語・独自の用語をそのまま使わない。** 展開するか `## Refs` で参照先を示す
- `## Refs` はパスに「何のために読むのか」を添える。**未作成なら「未作成」と書く**
- 文字数予算は **2000 文字**（意味内容のみ。機械節は別枠）。
  実測では 1098 文字で「引き継ぎに十分」と判定されたので、通常は半分ほどで収まる
- セッションを跨いで要る知識（候補の比較、未検証点、保留の理由）は、
  本来 `docs/` 側が正本。ここに閉じ込めたままにしない

## 参照

- 雛形: `~/.claude/skills/checkpoint/references/checkpoint-template.md`
- CLI: `~/.claude/skills/checkpoint/scripts/checkpoint.py`
