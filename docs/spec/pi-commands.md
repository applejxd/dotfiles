# pi のスラッシュコマンド（stock）の早見

stock の pi（既定。[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)）で、**いま実在する**スラッシュコマンドの早見。
凍結した自作ハーネス（custom）の早見は [pi / pis マニュアル](pi-manual.md)（凍結）。外部 CLI（Claude Code・Copilot CLI・OpenCode）のコマンドは、各公式の文書を見る。

- 確認の日と版: 2026-11-12。pi 1.5.0、package の版は `home/.chezmoitemplates/pi-stock-packages`。
- 実機で見るには、pi の入力欄で `/` を打つ（補完に出る）。
- **この表は試験で実物と突き合わせる**（`test/test_pi_commands_doc.py`。pi と package が入った機でだけ回る）。pi か package を更新して
  コマンドが増減すると試験が落ちるので、この表を直す。

## pi 本体の組み込み（24 件）

| コマンド | 内容 |
| --- | --- |
| `/settings` | 設定メニューを開く |
| `/model` | モデルを選ぶ（`<provider/model>`） |
| `/scoped-models` | `Ctrl+P` で巡回するモデルを、有効・無効にする |
| `/thinking` | 思考レベルを設定する |
| `/tree` | セッションの木を辿る（分岐の切り替え） |
| `/fork` | 前の利用者のメッセージから、新しい分岐を作る |
| `/clone` | 今の位置でセッションを複製する |
| `/new` | 新しいセッションを始める |
| `/resume` | 別のセッションを再開する |
| `/session` | セッションの情報と統計を見る |
| `/name` | セッションの表示名を付ける |
| `/compact` | 文脈を手動で圧縮する |
| `/reload` | キーバインド・拡張・skill・prompt・テーマ・文脈ファイルを再読み込みする |
| `/export` | セッションを書き出す（既定は HTML） |
| `/import` | JSONL のセッションを取り込む |
| `/share` | セッションを共有する |
| `/copy` | 直前のエージェントのメッセージを、クリップボードへコピーする |
| `/changelog` | 変更履歴を見る |
| `/hotkeys` | キーボードショートカットの一覧を見る |
| `/trust` | プロジェクトの信頼の判断を、次回以降のために保存する |
| `/login` | プロバイダの認証を設定する |
| `/logout` | 認証を外す |
| `/bug` | pi の開発者へ不具合を報告する |
| `/quit` | 終了する |

## pi 本体に同梱の拡張のコマンド

pi 本体が組み込みで読み込む拡張（`dist/extensions/`）が登録する。MCP の設定は [mcp-servers.md](mcp-servers.md)。

| コマンド | 内容 |
| --- | --- |
| `/mcp` | MCP サーバーの管理（サインイン・再接続・有効と無効・`exposure` の変更） |
| `/llama` | llama.cpp の router のモデルを管理する |

## package のコマンド

どれも `home/.chezmoitemplates/pi-stock-packages` の package が登録する（仕事用の機だけが入れる `pi-mcp-adapter` は対象外）。設定とツールの扱いは
[agent-config-generation.md](agent-config-generation.md#追加の-4-つの-packagebackgroundplan-modegoalrewind)・
[permission-system の設定](agent-config-generation.md#permission-system-の設定stock)。

| package | コマンド | 内容 |
| --- | --- | --- |
| `pi-subagents` | `/run` | 子エージェント 1 つを workflow として実行する（`/run <agent> [task] [--bg] [--fork]`） |
| | `/subagents` | 子の管理（メタデータ・モデル・思考レベル・prompt の確認と更新） |
| | `/subagents-fleet` | 稼働中の子の一覧（**fleet**）と inspector を開く。子の一覧・文字起こし・steer・停止 |
| | `/subagents-steer`・`/subagents-stop`・`/subagents-detach` | 動いている子へ指示する・止める・前景の子を切り離す |
| | `/subagents-doctor`・`/subagents-guide` | 診断を見る・同梱の手引きを見る |
| | `/subagents-models`・`/subagents-profiles`・`/subagents-load-profile`・`/subagents-generate-profiles`・`/subagents-check-profile`・`/subagents-refresh-provider-models` | モデルの割り当て・プロファイルの一覧・読み込み・生成・確認・カタログの更新 |
| | `/subagents-refine`・`/subagents-watchdog`・`/subagent-cost` | 子の改善案の生成・watchdog の表示と切り替え・親と子の費用 |
| | `/prompt-workflow` | prompt template を、pi-subagents の workflow として実行する |
| `pi-background` | `/bg` | 背景ジョブの直近の出力を見る |
| `@narumitw/pi-plan-mode` | `/plan` | 計画モード（読み取り専用で計画を作り、承認してから実装する） |
| `@narumitw/pi-goal` | `/goal` | 目的を、完了まで自走で続ける（`/goal [--tokens 100k] <目的>`） |
| `@narumitw/pi-btw` | `/btw` | 本体の会話に足さず、別のスレッドで質問する |
| `pi-show-token-rate` | `/token-rate` | ステータス行の TPS・TTFT を出す・隠す |
| `@ayulab/pi-rewind` | `/rewind`・`/checkpoint` | 作業ツリーを前のスナップショットへ戻す・スナップショットの保管先を管理する |
| `@thgilciffart/pi-compaction` | `/compaction-settings` | 圧縮の設定メニューを開く（`show` で有効な方針を見る） |
| `@gotgenes/pi-permission-system` | `/permission-system` | 確認（YOLO など）の切り替え・設定 |
| `@juicesharp/rpiv-todo` | `/todos` | 今のブランチの todo を、状態ごとに見る |
| `cc-safety-net` | `/cc-safety-net` | CC Safety Net の操作（ブロックの説明・規則・統合・診断） |

## package が同梱する prompt template

`pi-subagents` の `prompts/`。子エージェントを使う定型の進め方で、呼ぶと取りまとめ役の指示になる。

| コマンド | 内容 |
| --- | --- |
| `/council` | 助言役を集めた会議（親が仲介）を開き、決定のメモを書く |
| `/gather-context-and-clarify` | 子に文脈を集めさせてから、確認の質問をする |
| `/parallel-research` | 子を並列に動かして調べる |
| `/parallel-review` | 子を並列に動かしてレビューする |
| `/parallel-cleanup` | 子を並列に動かして掃除の観点でレビューする |
| `/review-loop` | レビューと修正を、指摘が無くなるまで繰り返す |

## このリポジトリが配る prompt template

`home/dot_pi/agent/prompts/`（元データは `home/dot_config/agents/common.toml.tmpl` の `[pi.stock_commands.*]`・`[pi.commands.*]`。仕組みは
[プロンプトテンプレート](agent-config-generation.md#プロンプトテンプレートfleetstepback)）。Windows には配らない。

| コマンド | 内容 |
| --- | --- |
| `/fleet <依頼>` | 依頼を並列に動かせる作業に分け、`subagent` ツールで worker を同時に起動して進める。書き手ごとに専用の枝と worktree を作り、完了した順に統合用の枝へ取り込む。作業間の境界は契約で先に決めて見込みで進め、検査は 3 段（全体は最後に 1 回）で背景へ出す。目的は利用者の待ち時間の短縮 |
| `/stepback [質問]` | 質問（省略時は直前の質問と回答）を一段抽象化した問いに先に答えてから、答え直す |

## stock には無いコマンド

凍結した自作ハーネス（`pis`・フルガード）だけが登録するコマンド。stock の pi には**存在しない**（これを前提にした古い説明は、凍結の注記を付けて残してある）。

| コマンド | 凍結した基盤での内容 | stock での代わり |
| --- | --- | --- |
| `/agents`・`/agent` | 子の一覧と、子の直接の起動 | `/subagents-fleet`、`subagent` ツール |
| `/bypass` | ask を確認なしで通す | `/permission-system` の YOLO |
| `/orchestrate` | 親を計画・判断・委譲に絞る | 無し（`/fleet`・`/plan`） |
| `/pending` | 承認が取れず退避したコミットの一覧・表示・破棄（承認の経路は撤去済み） | 無し |
| `/board`・`/worktrees`・`/work` | 盤面・隔離 worktree の掃除・作業台帳 | 無し |
| `/delegate-stats` | 直近の発言ごとの、読み取り量と委譲の件数（記録のみ） | 無し（費用は `/subagent-cost`） |

`/goal`・`/plan`・`/btw`・`/todos` は、凍結した自作版（`/goal` と作業台帳・自作の `plan` など）と**同名で別物**。stock は上の package 版。
