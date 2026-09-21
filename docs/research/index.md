# 調査記録

特定時点の実測、比較、アップストリーム調査を保存します。
現在の運用ルールは [仕様・運用](../spec/index.md)、採用した設計判断は
[ADR](../adr/index.md) を参照してください。

## 運用

- ファイル名は `kebab-case-topic.md`（連番なし）
- **1 記録 = 1 回の調査・試行。** 観測日と一次情報の URL を必ず書く
- 実測は**実行したコマンドと出力**を載せる。推測を書くときは「推測」と明示する
- **過去の記録を書き換えない。** 新しいパスは新しい記録として追加する。
  訂正は元の観測と区別して残す
- 陳腐化しても削除しない。「いつ時点か」が分かれば古い観測にも価値がある
- **現在の総合判断は [探索・変更案件](../change/index.md) の候補比較表が正本。**
  ここを全部読まないと現状が分からない状態にしない
- 大きくなったらディレクトリへ分割し、`YYYY-MM-DD-<pass>.md` を並べる
- テンプレートは `~/.claude/skills/checkpoint/references/research-template.md`

## 一覧

| 文書 | 内容 |
| --- | --- |
| [エージェントハーネス比較](agent-harness-comparison.md) | Claude Code / Copilot CLI / Codex CLIの機能・強制層・設定差分、OpenCodeへの乗り換え評価 |
| [OpenCode V2の仕様](opencode-v2-capabilities.md) | permission・plugin hook・skill・compaction・V1からの移行と未実装項目 |
| [OpenCodeプラグイン生態系の棚卸し](opencode-plugins.md) | 主要プラグインのV1/V2世代判定、Claude Code hook互換3件、oh-my-opencodeの衝突点 |
| [OpenCode V2 plugin APIの実測](opencode-plugin-api-probe.md) | permission hookの入力・deny実効性・ロード失敗時のfail-open、生コマンドとcwdの取得経路 |
| [OpenCode V2のpermission適用範囲の穴](opencode-permission-gaps.md) | grep/globがread denyを迂回する実測、カスタムツールのpermissionバイパス |
| [OpenCode V2 pluginの相関と承認要求の可否](opencode-plugin-correlation.md) | 並列実行時のcwd相関、plugin から ask を出せるかの実測、ctx.permission.rules の不在 |
| [OpenCode V2のshell allowの費用対効果とpluginゲート](opencode-shell-allow-and-plugin-gate.md) | 実履歴1,247セグメントでのallow被覆率、静的パターンのクォート/変数回避、ask→allow引き上げの実測 |
| [OpenCode V2のツール登録とコンテキストコスト](opencode-tool-context-cost.md) | ツール一覧の固定費、codemode true/false の差、ツール化の可否判断 |
| [OpenCode V2のaskと並列バッチ](opencode-ask-and-parallel-batch.md) | 承認待ちは並列を壊さない実測、拒否が中断の起点、permission.reply のスキーマ、askの実効がモードで変わる |
| [OpenCode V2の試験環境の隔離方法](opencode-test-isolation.md) | XDG_CONFIG_HOME が効かない実証、OPENCODE_CONFIG_DIR、Copilot モデルの引き方、過去記録への影響評価 |
| [compaction 関連の hook 仕様](compaction-hooks.md) | 圧縮の直前・直後に割り込める hook、Copilot の入力契約の実測 |
| [sandbox機能の包括調査](sandbox-capabilities.md) | Claude Code / Copilot CLIのsandbox全機能、採用状況、落とし穴 |
| [zenoとzsh-autosuggestionsの連携](zeno-autosuggestions-integration.md) | widget競合の原因、ロード順、回避策 |

[ドキュメント一覧へ戻る](../index.md)
