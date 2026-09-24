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
- 増えたらサブディレクトリへ分ける。現在は対象（`agents/` / `opencode/` /
  `shell/`）で分け、`opencode/` はさらに主題（`permission/` / `plugin/`）で
  分けている
- テンプレートは `~/.config/opencode/skills/checkpoint/references/research-template.md`

## 一覧

### エージェント CLI 横断

| 文書 | 内容 |
| --- | --- |
| [エージェントハーネス比較](agents/harness-comparison.md) | Claude Code / Copilot CLI / Codex CLIの機能・強制層・設定差分、OpenCodeへの乗り換え評価 |
| [sandbox機能の包括調査](agents/sandbox-capabilities.md) | Claude Code / Copilot CLIのsandbox全機能、採用状況、落とし穴 |
| [compaction 関連の hook 仕様](agents/compaction-hooks.md) | 圧縮の直前・直後に割り込める hook、Copilot の入力契約の実測 |

### OpenCode 全般

| 文書 | 内容 |
| --- | --- |
| [OpenCode V2の仕様](opencode/v2-capabilities.md) | permission・plugin hook・skill・compaction・V1からの移行と未実装項目 |
| [OpenCode V2の試験環境の隔離方法](opencode/test-isolation.md) | XDG_CONFIG_HOME が効かない実証、OPENCODE_CONFIG_DIR、Copilot モデルの引き方、過去記録への影響評価 |
| [OpenCode V2のツール登録とコンテキストコスト](opencode/tool-context-cost.md) | ツール一覧の固定費、codemode true/false の差、ツール化の可否判断 |
| [OpenCode V2のaskと並列バッチ](opencode/ask-and-parallel-batch.md) | 承認待ちは並列を壊さない実測、拒否が中断の起点、permission.reply のスキーマ、askの実効がモードで変わる |
| [OpenCode V2のキーバインド](opencode/keybinds.md) | 未知の ID は黙って無視される実測、ID の実在確認法、ctrl+c を app.exit が握る件、キー送出検証が成立しない理由 |

### OpenCode の permission

| 文書 | 内容 |
| --- | --- |
| [permission適用範囲の穴](opencode/permission/gaps.md) | grep/globがread denyを迂回する実測、カスタムツールのバイパス、プロジェクト設定がグローバルに勝つ（policiesだけは勝てない・plugin/mcpは実行される）、read ツールは deny を守る |
| [設計を縛る制約の総覧](opencode/permission/constraints.md) | CHG-0002の判断の根拠を1枚にまとめたもの。制約13項目、境界が無いこと、sandboxを採用しない理由、誘導対象の選定計測 |
| [Anthropic Sandbox Runtime の適用可否](opencode/permission/sandbox-runtime.md) | srtは汎用で導入済み、denyReadは許可領域の内側にしか効かない、認証情報を落とすだけでgit push/ghが止まる、ドメイン制限とseccompの実測、chezmoi(snap)が動かない |
| [shell allowの費用対効果とpluginゲート](opencode/permission/shell-allow-and-plugin-gate.md) | 実履歴1,247セグメントでのallow被覆率、静的パターンのクォート/変数回避、ask→allow引き上げの実測 |
| [allowリスト監査](opencode/permission/allow-list-audit.md) | git diff/statusの任意コード実行、sed -n の危険性、リダイレクトが resource に残る実証、allowとaskの等価性 |
| [出力フィルタと子エージェント](opencode/permission/output-filter-and-subagents.md) | execute.afterでshell出力を伏字化できる実証、符号化ですり抜ける限界、continue_loop_on_deny、子エージェントも共通permissionに従う |
| [カスタムエージェント(Bypass)とキーバインド](opencode/permission/bypass-agent.md) | keybindsがV2で除去される実証、modeではなくagentで実装する、permission="allow"の展開、bypassが外す防御の範囲 |
| [sandboxはあるか](opencode/permission/sandbox.md) | 組み込みsandboxが無いことの確認、プロセスごと隔離の実証、常駐サービス経由の脱出、snapが動かない、採用しない判断の根拠 |
| [hookの呼ばれ方とactionの種類](opencode/permission/hook-order.md) | execute.beforeが評価より前に走る実測、external_directoryが別actionで立つ、誘導のdenyは確認を出さない、計装の手順 |
| [段階2配備後の被覆率](opencode/permission/stage2-coverage.md) | 実履歴1,031呼び出しでの実測、秘密へ触れた15件を3層が全件受け止める、誘導後も87%が確認、伏字化の誤爆0.3%、内容の形とパス判定は両方要る |

### OpenCode の plugin

| 文書 | 内容 |
| --- | --- |
| [plugin生態系の棚卸し](opencode/plugin/ecosystem.md) | 主要プラグインのV1/V2世代判定、Claude Code hook互換3件、oh-my-opencodeの衝突点 |
| [plugin APIの実測](opencode/plugin/api-probe.md) | permission hookの入力・deny実効性・ロード失敗時のfail-open、生コマンドとcwdの取得経路 |
| [pluginの相関と承認要求の可否](opencode/plugin/correlation.md) | 並列実行時のcwd相関、plugin から ask を出せるかの実測、ctx.permission.rules の不在 |
| [pluginのロード経路](opencode/plugin/loading.md) | 明示指定は絶対パスのディレクトリのみ、~が展開されない、失敗が無言、Orca overlayとの関係、Claude Codeとの仕組みの違い |
| [ask画面へ説明を出す](opencode/plugin/ask-description.md) | 権限ダイアログがmessageを読まない実証、TUI pluginのtoastなら出せる、app_bottomスロットが2.0.12に無い、安価モデルでの説明生成 |

### シェル

| 文書 | 内容 |
| --- | --- |
| [zenoとzsh-autosuggestionsの連携](shell/zeno-autosuggestions-integration.md) | widget競合の原因、ロード順、回避策 |

[ドキュメント一覧へ戻る](../index.md)
