# 文脈の引き継ぎ (checkpoint)

コンテキスト圧縮を跨いで、作業の経緯・決定・残作業を失わないための仕組み。

設計判断の理由は [ADR-0009](../adr/0009-save-before-documenting.md)、
両 CLI のイベント仕様は
[compaction 関連の hook 仕様](../research/compaction-hooks.md) を参照。

## 構成

強制の層を 3 つに分ける。**圧縮を跨いで生き残るのは指示ファイルだけ**なので、
恒久ルールはそこへ置く。

| 層 | 実体 | 役割 |
| --- | --- | --- |
| 指示ファイル | `home/dot_claude/CLAUDE.md` / `home/dot_copilot/copilot-instructions.md` | 恒久ルール。「文脈の引き継ぎ」節 |
| スキル | `home/dot_claude/skills/checkpoint/` | 手順・雛形の単一ソース |
| hook | `home/dot_config/agents/common.toml.tmpl` の `[[hooks]]` | 圧縮直前の記録と直後の復帰 |

## 保存先

**常にセッション別の名前**を使う。固定名を奪い合わないので、ロックも所有権の
交渉も要らない。

```text
<リポジトリルート>/.tmp/checkpoint-<sid8>.md        本体
<リポジトリルート>/.tmp/checkpoint-<sid8>.prev.md   直前の世代
<リポジトリルート>/.tmp/checkpoint-<sid8>.state.json 状態 (Tier 2 用、未実装)
```

- リポジトリルートは `git rev-parse --show-toplevel` で決める。
  **hook の `cwd` はサブディレクトリのことがある**ので `./` を前提にしない
- git の無視設定は `git rev-parse --git-path info/exclude` で解決する。
  **`.git` はファイルのこともある**（linked worktree / chezmoi の source state）
- `.gitignore` は共有ファイルなので書き換えない
- **セッション横断の削除をしない。** 件数や日数で消すと、稼働中の別セッションの
  記録まで消える。各セッションは自分の 3 ファイルだけを管理する

## 記録の形

見出しは 6 つを順序どおりに置く。雛形は
`~/.claude/skills/checkpoint/references/checkpoint-template.md`。

| 節 | 内容 |
| --- | --- |
| `## Goal` | 達成したら終わりと言える条件（3 行以内） |
| `## Constraints` | ユーザー指定の制約、却下済みの方針 |
| `## State` | 完了 / 未完 / 未解決の論点 |
| `## Evidence` | 実行したコマンドと結果（推測を書かない） |
| `## Next` | 次の 1 手。「何を」で止めず**「どうやって」**まで |
| `## Refs` | `docs/...` のパス + 読む理由。未作成なら「未作成」と明記 |

`<!-- machine: -->` より下は hook が上書きするので、人も AI も書かない。

**圧縮時刻（`snapshot_at`）は機械節にだけ置く。** hook はヘッダを触らない設計
なので、ヘッダに書くと誰も更新せず「未取得」に見え続ける。旧雛形の名残として
残っていた場合は `lint` が警告する。

**文字数予算は 2000 文字**（意味内容のみ。機械節は別枠）。復帰試験の実測では
1098 文字で「引き継ぎに十分」と判定された。

## 鮮度の判定

**`covered_through` を、その保存要求の固定境界と比べる。**

- **mtime では判定しない。** 圧縮直前の hook が機械節を書くと mtime が更新され、
  古い意味内容が「新鮮」に見えてしまう
- **「現在の会話地点」とも比べない。** 保存や検査そのもので境界が進み、正しく
  保存しても永久に一致しない
- 境界は要求が立った時点で 1 つだけ固定し、以降動かさない

## hook

| イベント | スクリプト | 動作 |
| --- | --- | --- |
| Claude `PreCompact` / Copilot `PreCompact` | `checkpoint_precompact.py` | 機械的事実だけを記録。**絶対にブロックしない** |
| Claude `SessionStart` matcher `compact` | `checkpoint_restore.py` | 自分の記録を stdout へ出す（**Claude 専用**） |

**Copilot も PascalCase で登録する。** camelCase だと入力に `hook_event_name` が
入らない（記録 E3）。

**ブロックしない理由**: 公式は、context-limit エラーからの回復として発火した
自動圧縮をブロックすると「元のエラーが表面化し、現在のリクエストが失敗する」と
明記している。機械記録のためにユーザーの作業を失わせるのは割に合わない。

**Copilot に復帰 hook が無い理由**: `preCompact` は通知専用で、`postCompact`
相当のイベントも存在しない。圧縮直後の自動注入は原理的にできず、指示ファイルに
頼る best-effort になる。

## 使い方

```bash
CP=~/.claude/skills/checkpoint/scripts/checkpoint.py

# 保存先を解決する（固定パスを自分で組み立てない）
uv run --no-project python "$CP" paths --session "<セッションID>" --ensure-ignored

# 書く
uv run --no-project python "$CP" write <checkpoint パス> --keep-prev <prev パス>

# 構造を検査する
uv run --no-project python "$CP" lint <checkpoint パス> --structure
```

hook が静かに失敗したときは `CHECKPOINT_HOOK_DEBUG=1` を立てると stderr に
理由が出る。

## 現在の状態と制限

- **スキルは手動起動でも使える。** 「checkpoint して」で A1（実行状態の保存）が走る
- **Copilot では圧縮直後の自動注入ができない**（イベントが存在しない）
- **Copilot では文脈使用率を推定できない。** `PostToolUse` の入力に
  `transcript_path` が無い（記録 E4）。閾値監視は現時点で見送り
- **実機での圧縮試験は未実施。** `chezmoi apply` と新しいセッションが要る
- **Windows 実機での検証は未実施**（source state は更新済み）

## 関連

- 設計理由: [ADR-0009](../adr/0009-save-before-documenting.md)
- docs の運用: [ADR-0010](../adr/0010-exploratory-spec-driven-docs.md)
- イベント仕様の実測: [compaction 関連の hook 仕様](../research/compaction-hooks.md)
- 進行中の案件: [CHG-0001](../change/0001-compaction-context-handover.md)

[仕様一覧へ戻る](index.md)
