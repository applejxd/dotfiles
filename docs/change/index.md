# 探索・変更案件

これから実装すること、いま探索していることの記録。

[ドキュメント一覧へ戻る](../index.md)

## 目的

研究開発では、目的は決まっていても方法や仕様が定まっていないことが多い。
複数の手法を並行して試し、より良いものを選んで仕様を更新していく。

その過程で **「目的は共有されているが、複数候補と未解決事項が継続的に存在する状態」**
が生まれる。これは一時的な寄り道ではなく、恒常的に管理すべき対象になる。
候補の比較・未検証点・評価基準をここへ置き、現在の理解へ更新し続ける。

「何を観測したか」は [調査記録](../research/index.md)、
「なぜそう決めたか」は [ADR](../adr/index.md)、
「今どうなっているか」は [仕様・運用](../spec/index.md) が正本。

## 運用

- ファイル名は `NNNN-kebab-case.md`（4 桁ゼロ埋め。ADR とは別の番号空間）
- **目的ができた時点で作ってよい**。実装の合意を待たない
- **実装前の期待動作（受入条件）を先に書く**。実装後の説明にしない
- 新規作成時はこの索引の「活動中」へ 1 行追加する
- 状態は `Exploring` / `Planned` / `In progress` / `Done` / `Paused` / `Abandoned`
- `Done` は実装完了とは限らない。実現性の判断がついた場合など、
  **知見のみで終了してよい**
- **終了しても削除しない。** 状態と終了日を付けたうえで
  `closed/` へ移し、索引の区分も「活動中」から「終了」へ移す。
  研究開発では、当初の期待・変更した判定条件・試さなかった候補・
  実際の結果との差にも価値がある
- **`change/` 直下には取り組み中のものだけを置く。** ファイル一覧を見た
  だけで現在地が分かる状態を保つ（[ADR-0011](../adr/0011-close-change-records-into-subdirectory.md)）
- 終了した案件の先頭には
  「この文書は当時の記録。現在の仕様は `spec/...`」の注記を置く
- 終了した案件の「終了結果」には、**採用したもの / 撤回・見送りしたもの /
  反映先 / 移管した未完事項と移管先**をそろえる。本文の途中にある古い
  「現在地」や「次の調査」は消さず、時点を添えて終了結果へ案内する
- 番号は再利用しない。連続性は要求しない（終了で欠番が出るのは正常）
- テンプレートは `~/.claude/skills/sdd-docs/references/change-template.md`

## 活動中

| # | 目的 | 状態 | 最大の未解決点 | 次の確認 | 更新日 |
| --- | --- | --- | --- | --- | --- |
| [0006](0006-pi-harness-trial.md) | Pi / oh-my-pi を利便性の軸で試す | In progress | 段 2（常用）に着手。`enabledProviders = ["claude"]` の効果は常用の初回に判定する。使って決まった設定の回収（段 2.5）を計画へ追加 | 段 2 の冒頭で `/criticalthink`（chezmoi が配る唯一の Claude コマンド）がスラッシュコマンドに出るか | 2026-09-30 |
| [0007](0007-harness-profiles.md) | 境界をハーネス非依存にする（3 層プロファイル） | In progress | 段 3（汎用化）の動機が CHG-0006 の結論で弱まった。**段 2 は取りかかれる**。`ocs` のモジュール分割（2026-09-28）はハーネス層の切り出しではない | 段 2（共有ランタイムとハーネスの節分け） | 2026-09-28 |
| [0011](0011-agent-first-shell.md) | AI エージェントがシェルの主な利用者である前提へ整える | In progress | Claude Code へ git の環境変数を入れる方法が保留（`CLAUDE_ENV_FILE` と比較）。Windows は人が開いた対話シェルと本物の Copilot CLI での引き継ぎが未確認 | ocs の実機で deny の前段停止（pip 以外へ拡張済み）を確かめる | 2026-10-07 |
| [0012](0012-bash-hook-shared-parser.md) | bash 検査 hook のコマンド解析を 1 か所に集める | In progress | Windows 実機で未検証。B 群（`shlex.split` の規則）は保留 | Windows の PowerShell で `test/agents/` を回し、通れば閉じる | 2026-10-06 |
| [0017](0017-builtin-agent-restrictions.md) | 組み込みの `explore` / `plan` の制限が全体の設定に上書きされる問題を直し、`bypass` から起動する子を確認なしで動かせる範囲に整える | In progress | `bypass` の子に残る確認のうち、作業ツリーの外の読み取り以外（`production.env` などと shell 由来）は意図して残す。`plan` の shell の確認に保存した承認がどう効くか | 段 1〜8 完了（apply 済み、ADR-0015）。残りは未解決点 | 2026-10-08 |
| [0018](0018-opencode-policy-role-split.md) | OpenCode の権限を「共通の禁止」と「役割ごとの権限」に分けて生成する | Exploring | 全体の allow / ask をエージェント別へ移したとき、未分類のエージェントに基底の allow がむき出しにならないか | 段 2（全エージェントの棚卸し）。段 1 で policy が通常の起動で効くことを確かめた | 2026-10-08 |

## 保留

| # | 目的 | 保留理由 | 再開条件 | 更新日 |
| --- | --- | --- | --- | --- |
| [0002](0002-opencode-ask-by-default.md) | OpenCode の permission を既定 ask にし、秘密への経路を機構で塞ぐ | 段階 0〜3 は完了、4a / 4b は見送り、6 は決着。残る段階 5（`verify` ツール）が第一サポートの決定待ち。段階 3 までは適用済みで動いている | CHG-0006 が第一サポートを決めたとき（「決めない」と決めた場合も含む） | 2026-10-07 |
| [0005](0005-agents-config-naming.md) | `common.toml` の命名を実態に合わせ、固有設定を分離する | 段階 A1 完了 / A3 消滅 / A4 保留（checkpoint の A1 / A2 とは別の、この案件の段階番号）。残る A2 は第一サポートが変われば対象も変わるため、先に動かすと手戻りになる | 同上。なお A2 の前提である ADR-0007 規則 3 との矛盾と、A1 で取り残した `[file]` 節のコメントは、CHG-0006 と独立に片付けられる | 2026-09-28 |
| [0016](0016-away-shift-opencode.md) | away-shift を OpenCode 向けに最適化し、運用（深層学習ジョブの調査・再開、会社 PC での利用）を見直す | 着手前。applejxd 限定の棚卸しを先に進めるため積んだ | 利用者が着手を指示したとき | 2026-10-08 |

## 終了

| # | 目的 | 結果 | 終了日 | 現行仕様 / ADR |
| --- | --- | --- | --- | --- |
| [0015](closed/0015-commit-planner-with-chat-approval.md) | 計画役の子にメッセージ案を作らせ、承認は会話で行う | 採用・配備済み（`--auto` と利用者の TUI で、全文を示して承認を待ち、承認後にコミットした） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0014](closed/0014-deterministic-commit-runner.md) | コミットの表示と実行を決定的なスクリプトに任せる | 見送り（`--auto` では通ったが、利用者の TUI で照合が止まった。部品の多さに見合わないとして取り下げ、親が commit スキルでコミットする形に戻した） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0013](closed/0013-commit-agent-as-planner.md) | commit エージェントを計画役にし、コミットは親が行う | 一部採用（隔離起動でも `git commit` を確認・`git -c … commit` の停止・確認画面の連結形の表示は残した。計画役の `commit` エージェントは廃止） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0008](closed/0008-raspi-branching.md) | Raspberry Pi（64bit / ヘッドレス）を導入対象に加える | 採用・適用済み（実機 3 周目で apply が 45 秒で完走。判定は `.chezmoitemplates/is-raspi` で `chezmoi update` だけで効く。`[data] is_raspi` の方式は撤回） | 2026-09-26 | [プロジェクト構造](../spec/structure.md#raspberry-pi) |
| [0010](closed/0010-ocs-agents.md) | `ocs` の中でも `common.toml` のエージェントとコマンドを使う | 採用・配備済み（隔離版の設定にエージェントとコマンドを出した。Fence 化からの差分もレビューループで直した） | 2026-09-29 | [opencode-sandbox](../spec/opencode-sandbox.md) / [ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) |
| [0009](closed/0009-ocs-simplify-for-accidents.md) | `ocs` をうっかりの防止に必要な分まで簡素にする（ADR-0012） | 採用・配備済み（境界を Fence に替え、履歴を通常の起動と共有し、承認と起動時の検査をやめた。段 6 は未起票で移管） | 2026-09-29 | [opencode-sandbox](../spec/opencode-sandbox.md) / [ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) |
| [0001](closed/0001-compaction-context-handover.md) | compaction を跨いで作業文脈を失わない | 採用・適用済み（圧縮要約そのものを checkpoint にした。Claude / Copilot の hook は撤去） | 2026-09-25 | [checkpoint](../spec/checkpoint.md) / [ADR-0009](../adr/0009-save-before-documenting.md) |
| [0004](closed/0004-opencode-sandbox.md) | OpenCode の保護を OS のアクセス制御へ移す（Ubuntu / WSL のみ） | 採用・適用済み（通常起動と併用。既定を `ocs` にする案は撤回） | 2026-09-24 | [opencode-sandbox](../spec/opencode-sandbox.md) |
| [0003](closed/0003-ask-command-description.md) | 確認画面で長いコマンドを判断可能にする | 採用・適用済み | 2026-09-22 | [agent-config-generation](../spec/agent-config-generation.md#確認画面に出るコマンドの説明) |
