# 探索・変更案件

これから実装すること、いま探索していることの記録。

[ドキュメント一覧へ戻る](../index.md)

## 今の作業計画（活動中）

利用者が今の作業計画を追うための 1 枚（2026-11-11 時点。節目＝開始・方針の変更・完了・依頼のときだけ更新する。[ADR-0032](../adr/0032-docs-by-audience.md)）。

| 作業 | 何を | 今どこ | 次の一手 | あなたが決めること | 関連 |
| --- | --- | --- | --- | --- | --- |
| stock の pi への移行 | 自作基盤を凍結し、公式の pi＋人気の拡張へ | **完了**。stock が既定のプロファイル（2026-11-10）で、実機で使用中。権限の方針は「YOLO を切る前提の deny と強制 ask」で、全 deny に理由がある（ask には理由の仕組みが無い） | 1〜2 週間使い、足りない所を `friction-review` スキルでセッションのログから洗い出す | なし | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)・[拡張の評価](../research/agents/pi-stock-packages-evaluation-2026-11.md) |
| 検索 MCP（家の機向けの自作 1 件） | 検索を MCP サーバで提供する | 統合済み（本体・stock への登録・plan mode でも使える・スキル `web-search` の廃止と imozuru の書き換え）。実機での確認の記録は無い | 使いながら確認 | なし | [web-search 仕様](../spec/web-search.md) |
| 圧縮（コンパクト化）の方針 | 圧縮の要約を「続きの作業のための brief」にする | 決定・統合済み。70 万トークン（`reserveTokens` 30 万）で圧縮し、`pi-compaction` は要約の指示（brief）だけに使う。根拠: 過去セッションの集計で、長い文脈の劣化の兆候は見つからなかった。自作は足さない | 実機で確認（`/compaction-settings show`・1 回目の圧縮が brief になっているか） | なし | [圧縮の研究ノート](../research/agents/long-context-compaction-paper-2026-11.md) |
| 子エージェントの運用（`pi-subagents`） | 子の起動を常設の指示で授権し、数の上限を外し、役ごとにモデルと権限を決める | 実装・統合済み（2026-11-11）。`reviewer`・`oracle`・`evidence-auditor` は親と別系統の GPT 6.1 sol。作業ツリーの外は子でも即拒否。**常設の指示が実際に効くか（指示なしに子を起動するか）は未観察** | 1〜2 週間使い、起動すべき場面で起動するか・過剰でないかを見る | [ADR-0033](../adr/0033-delegate-subagents-by-standing-instruction.md)（Proposed）を Accepted にするか | [仕様](../spec/agent-config-generation.md)・[oracle のモデル](../research/agents/oracle-model-2026-11.md)・[子の権限の実測](../research/agents/subagent-permission-frontmatter-2026-11.md)・[運用ガイド](../../.agents/skills/feature-orchestration/references/pi-subagents.md) |
| away-shift（離席中の検証） | 親が監督し、専用 worktree の子へサイクルを任せる。利用者は離席と戻りの時刻を言うだけ | 再設計・実装済み（2026-11-10）。リハーサル 5 サイクルを通過し、確認（ask）は 0 件。**数時間規模の運転・子 1 回あたりのトークン・Windows/macOS は未測定** | 実際に離席する機会に 1 回回す | なし | [仕様](../spec/away-shift.md) |
| 検証の高速化 | 凍結したスタックの試験を `verify:all` から外す | 統合済み。`verify:all` は 12〜13 分から 1 分 55 秒（`verify:full` は省略なしの 12 分 29 秒） | `main` への統合前に `verify:full` | [ADR-0034](../adr/0034-skip-frozen-stack-tests-in-verify-all.md)（Proposed）を Accepted にするか | [開発の仕様](../spec/development.md) |
| skill の置き場と掃除 | 自作 skill を `~/.agents/skills` へ移し、stock の pi 向けに書き直す | 完了（置き場の移動・`~/.agents/skills` の読み取り許可・`reviewer` への書き直し・`feature-orchestration` を stock の運用を既定に・`github-operations` の承認を権限の確認に一本化） | なし | なし | [skill の frontmatter](../spec/skill-frontmatter.md) |
| docs の見直し（この変更） | 読み手別に整理する縮小版（D 案）を試作 | D 案の試作を統合し、使って確かめる段階（ADR-0032 は Proposed）。2026-11-11 に、直近 2 週間の作業の抜け（ADR-0033・0034、この表、仕様の細部）を補った | この 1 枚で今の作業計画が追えるか確かめる → 追えれば、`commit` スキルと `sdd-docs` の変更（共通のスキルを縮小。案件更新の自動呼び出しと索引の自動補完を外す） | 試用のあと、ADR-0032 を Accepted にするか | [ADR-0032](../adr/0032-docs-by-audience.md) |
| pi の sandbox（層 b）の見直し | GPU を通す sandbox（`pib`）を入れ、実機で使って見つかった問題を洗い出し、自作の境界を決める | `pib` を配備済み（2026-11-12）。問題の洗い出しは完了し、境界の案を CHG-0066 に記載。標準のキャッシュ領域を書き込み可にする変更は保留 | 脅威モデルと実行の入口の判断を受けて、案 X（`shellPath` で一元化）の実現性を試す | 守る対象（D1）・実行の入口（D2）・方針の置き場（D3）ほか（D4〜D8） | [CHG-0066](0066-pi-sandbox-boundary.md)・[ADR-0035](../adr/0035-pi-sandbox-gpu-runner.md) |

凍結した案件は「終了」へ移した（入口は [CHG-0065](closed/0065-agent-stack-freeze.md)）。停滞した案件はこの表に入れない（下の「活動中」「保留」に残る）。

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
- テンプレートは `~/.agents/skills/sdd-docs/references/change-template.md`

## 活動中

| # | 目的 | 状態 | 最大の未解決点 | 次の確認 | 更新日 |
| --- | --- | --- | --- | --- | --- |
| [0011](0011-agent-first-shell.md) | AI エージェントがシェルの主な利用者である前提へ整える | In progress | Claude Code へ git の環境変数を入れる方法が保留（`CLAUDE_ENV_FILE` と比較）。Windows は人が開いた対話シェルと本物の Copilot CLI での引き継ぎが未確認 | ocs の実機で deny の前段停止（pip 以外へ拡張済み）を確かめる | 2026-10-07 |
| [0021](0021-windows-admin-consolidation.md) | Windows の chezmoi セットアップを整え、管理者権限の作業を 1 回の UAC に集約する | In progress | UAC 承認を含む通し実行が未検証（クリーンな Windows 実機が要る）。Python Launcher と Orca の UAC の有無が未確認。管理者グループの利用者の `administrators_authorized_keys` が未対応 | クリーンな Windows で `chezmoi apply` を通し、UAC が 1 回だけ出ることを確かめる | 2026-10-10 |
| [0022](0022-windows11-settings-review.md) | Windows 11 の設定を見直し、古い設定の修正と体験の改善を入れる | In progress | 段 1・2・3・4・6・7・8 は完了（ウィジェットは自動化を見送り）。`gow` と WSL・WSL 3 は保留 | `gow` の履歴の再集計、WSL の取り組み | 2026-10-12 |
| [0042](0042-tmp-lifecycle.md) | `.tmp/` をセッションごとの置き場に分け、終わりに消す（取り込むものは残す） | In progress | 対話モードでの `quit`・`/new`・`/resume`・`/fork`・`reload` の実機の確認（実装は段 2・3・4・6 完了。未確認は、これだけ） | 実機で `.tmp/s/<ID>/` の作成・`quit` での削除・SIGKILL の後の回収を確かめ、問題なければ Done へ | 2026-10-27 |
| [0043](0043-model-catalog.md) | 子エージェントのモデルを、最新のカタログから、ユーザの指示で選べるようにする（effort は自由） | In progress | Bedrock のカタログの `verified`（pi から GPT-6.1 へのツール呼び出しが未確認。`enforce_verified = false`）。実効の段の表示は未実装 | Bedrock を使える環境で `mise run models:probe`。確認後に `verified`・`enforce_verified` を `true` へ | 2026-10-27 |
| [0047](0047-gitflow.md) | main 一本から gitflow（main / develop / feature）へ切り替える（feature の起票・クローズの AI 化は CHG-0050 で撤去。動機: コミット粒度・main の安定・並列開発） | In progress | ブランチモデルは運用中。起票・クローズは利用者のシェル、AI は feature の worktree の `pi` から `git_commit`。経緯の本文は撤去前の設計の記録 | 実機で、feature の worktree から `git_commit` が期待どおり動くかを確認 | 2026-10-31 |
| [0051](0051-verification-tiers.md) | 検査（verify / verify:all）を段階化し、安い検査を先に・重い検査を後にする（失敗の見つかる順序・並列度・印の記録を直す） | In progress | T0 / T1 / T2 の段階化、fail-fast、並列度の上限と nice、印の開始時記録を実装済み。故意の失敗で 23 秒で止まることを確認 | 印の段と義務の置き場の判断、`AGENTS.md` の縮約、`pi` を起動する試験の起動費用の削減 | 2026-10-31 |
| [0064](0064-dev-environment-isolation.md) | 開発単位の環境で隔離する（WSL は専用ディストロ、ネイティブ Ubuntu は Incus 系。ADR-0027 の P3。SLAM・推論・compose） | Paused | 方針を ADR-0027 に記録。WSL は専用ディストロを開発単位で切る（W1〜W3 は未着手）。**ネイティブ Ubuntu 側（N1〜N3）は保留し、ネイティブ機のセッションで継続**。Incus を使う既存の OSS（特に `isx`）があると分かり、自作より先に評価する | W1（利用者の実行）→ W2・W3 の設計。ネイティブ機: N1（T1〜T5）→ N2（isx の評価）→ N3 | 2026-11-06 |
| [0066](0066-pi-sandbox-boundary.md) | pi のツール単位 sandbox（層 b）の問題を洗い出し、自作の境界を決める（ADR-0035 の後続。キャッシュ領域の変更は保留） | Exploring | 守る対象（脅威モデル）と、実行の入口（拡張か `shellPath` か）の決定が、利用者の判断待ち | 判断 D1〜D8 を決める。案 X（`shellPath` で一元化）が実際に `bg_run`・`!`・子を包めるか試す | 2026-11-12 |

## 保留

| # | 目的 | 保留理由 | 再開条件 | 更新日 |
| --- | --- | --- | --- | --- |
| [0005](0005-agents-config-naming.md) | `common.toml` の命名を実態に合わせ、固有設定を分離する | 段階 A1 完了 / A3 消滅 / A4 保留（checkpoint の A1 / A2 とは別の、この案件の段階番号）。残る A2 は第一サポートが変われば対象も変わるため、先に動かすと手戻りになる | CHG-0020 の段 6 で OpenCode の節を撤去したあと（第一サポートが pi に決まった）。なお A2 の前提である ADR-0007 規則 3 との矛盾と、A1 で取り残した `[file]` 節のコメントは、それと独立に片付けられる | 2026-10-09 |
| [0016](0016-away-shift-opencode.md) | 深層学習ジョブの調査・再開を away-shift で任せる運用を決める（旧: OpenCode 向けの最適化。2026-10-25 に段 2 だけ残して書き直し） | 段 2 のみ残して保留。pi 対応は CHG-0030 が引き継いだ | 利用者が着手を指示したとき。前提: CHG-0030 の実機確認 | 2026-10-25 |

## 終了

| # | 目的 | 結果 | 終了日 | 現行仕様 / ADR |
| --- | --- | --- | --- | --- |
| [0012](closed/0012-bash-hook-shared-parser.md) | bash 検査 hook のコマンド解析を 1 か所に集める | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0020](closed/0020-pi-migration.md) | OpenCode のハーネスを pi へ移す（判定 API・ハーネス・配布・境界・ハーネス以外の機能・撤去） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0023](closed/0023-guard-terminology.md) | 「ハーネス」の呼び方を整理し（ガード / フルガード / 簡易ガード / サンドボックス）、`pis` をサンドボックス既定にする | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0024](closed/0024-diagnostics-feedback.md) | 編集直後の診断フィードバック (LSP・linter・型検査) を足す | 凍結で打ち切り（元の状態: Planned。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0025](closed/0025-goal-autonomous-loop.md) | `/goal` の自律ループ (目標・計画・独立した完了の監査) を足す | 凍結で打ち切り（元の状態: Planned。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0027](closed/0027-zed-pi-acp-with-pis.md) | Zed の pi-acp から `pis --no-sandbox`（フルガード）を使えるようにする | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0030](closed/0030-away-shift-on-pi.md) | `away-shift` を pi（フルガード）で、無人でも止まらずに動く形にする | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0031](closed/0031-delegate-nudge.md) | 親エージェントが委譲を忘れないよう、読み取り量に応じた注記（ナッジ）を出す | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0029](closed/0029-worktree-isolation.md) | 子エージェントの実装作業を git worktree で分離し、検証を子の隔離環境で回せるようにする（CHG-0026・0028 の未完事項の移管先） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0032](closed/0032-guard-url-false-positive.md) | 判定器と、検索・取得のスクリプトの検査が、URL を誤検出して調査を止めないようにする | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0033](closed/0033-sandbox-build-value-assessment.md) | 自作したサンドボックスに価値があったかを、サンクコストを除いて、エビデンスで判定する | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [Windows ネイティブ（PowerShell）で pi を、OS の境界つきで動かす](closed/0034-windows-native-pi-boundary.md) | リポジトリが Windows 側で、Windows 起動前提のアプリも開発するので、Windows ネイティブで pi を境界つきで動かしたい（OpenShell・Docker Sandboxes は合わない） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0035](closed/0035-retire-python-judge-oracle.md) | 判定器の Python 版（オラクル）を撤去して、二重保守を解消する | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0036](closed/0036-nono-trial-on-wsl2.md) | nono を WSL2 で小さく試し、境界の層（`ocs`）の置き換えの可否を測る | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0037](closed/0037-pis-usability-and-telemetry.md) | `pis` の使い勝手を、他のプロジェクトで常用できる水準に上げ、運用の記録を取る（便益を測る前提） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0038](closed/0038-guard-reclassification.md) | ガードを「防ぐ害」（UX・認証情報・外部送信・破壊・構造）で分類し直し、外部への送信・公開の穴を塞ぐ（`confirm` の新設） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0039](closed/0039-bell-with-message.md) | 入力待ちの通知（BEL）に、メッセージを添える | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0040](closed/0040-pi-guard-by-settings.md) | pi のフルガードを設定で載せ、pis をサンドボックス専用に寄せる | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0044](closed/0044-plan-agent.md) | 強いモデル（`deep`）で計画し、既定のモデルで管理・実行する。`plan` 役の子と、`/plan`（計画モード）のモデル切り替え（`opusplan` 型） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0045](closed/0045-orchestrator-parent.md) | 親をオーケストレーターに寄せる。親は対話・判断・委譲・承認に専念し、実作業は子へ。スキルを、対話の段と実行の段（子へ渡す）に分ける「委譲の型」を整える | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0046](closed/0046-guarded-action-timeout.md) | 承認つきの操作（`guarded_action`）の確認が時間切れのとき、親が止まらず、内容を退避して作業を続ける（CHG-0041 の「確認の時間切れ問題」の移管先） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0050](closed/0050-slim-guarded-action.md) | pi のフルガードの `guarded_action` を、承認つきの commit と gh 投稿に縮める（運用規約はコードで強制せず指示にする） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0052](closed/0052-friction-tool-errors.md) | 利用者の摩擦の実測にもとづき、ツールのエラー（特に `guarded_edit`）を減らす（誘導の 3 層への再分類は見送り） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0053](closed/0053-worktree-integration-gate.md) | feature はローカルで自由にし、保護ブランチへの統合で確認・監査する（確認をコミットごとから統合へ寄せる） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0054](closed/0054-containment-and-async-approval.md) | 封じ込めを主にして確認（ask）層をなくし、非同期の承認で多数のエージェントを束ねる（常用の bypass と方針を一致させる） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0056](closed/0056-orchestrator.md) | 並列実装を配車・関門・承認パケット・標的レビューで自動化し、利用者を本質的な承認（統合・境界を越える副作用・設計の分岐・担当外の変更）に集中させる | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0057](closed/0057-per-project-integrate.md) | フルガードの統合まわり（自由区の接頭辞・統合先・統合元の接頭辞）を、リポジトリ内の `.agents/config/pi.json` でプロジェクトごとに変えられるようにする（保護ブランチは全体設定のまま。読むのは HEAD のコミット済みの内容だけ） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0060](closed/0060-local-pr-viewer.md) | GitHub をリモートに持たない開発向けに、PR 風のローカルのレビュー画面（Web）を作る（構成 C: 別アプリ + git の ref + 薄い pi 拡張。承認はアプリで閉じ、実行は窓口の pi。遠隔は tailnet が保証し、ペアリングは pi セッション側から） | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0062](closed/0062-pr-hub-simplify.md) | PR の管理・統合を、人が操作するアプリへ移す（統合は押下でアプリが同期実行。保留・受信箱を撤去。pi は押下契機の `pis -p` と通常のコーディングに絞り、最終的にオーケストレーションもアプリとマネージャー役へ） | 凍結で打ち切り（元の状態: In progress。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0065](closed/0065-agent-stack-freeze.md) | エージェント基盤の全面凍結と、公式既定の pi への切り替え（記録と再開の手引き） | 完了（凍結の記録。再開の入口。凍結の作業が終わった） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0026](closed/0026-specialist-agents-with-skills.md) | スキルを役割（子エージェント）へ割り当てる。まず移行の調査役（`migration-analyst`）に、移行スキルの重い読み物と影響の洗い出しを任せ、実行・対話は親に残す | 凍結で打ち切り（元の状態: Exploring。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0007](closed/0007-harness-profiles.md) | 境界をハーネス非依存にする（3 層プロファイル） | 凍結で打ち切り（元の状態: Paused。再開は CHG-0065 から） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md) |
| [0063](closed/0063-git-push-action.md) | git push の承認つき action（`git_push`）を `guarded_action` に足す | 取り下げ（5 回の独立 review で毎回別の穴。push は手動のまま。再開時の論点を記録） | 2026-11-05 | [CHG-0050](closed/0050-slim-guarded-action.md)、[CHG-0053](closed/0053-worktree-integration-gate.md) |
| [0061](closed/0061-pr-inbox.md) | PR ビューアと pi の間に、非同期のメッセージ・キュー（pi 内の受信箱）を入れる | 見送り（S2 まで実装したが、配備せず撤去。方針は CHG-0062 に置き換え。S0 の実験記録は研究として残す） | 2026-11-03 | [CHG-0062](closed/0062-pr-hub-simplify.md)、[調査記録](../research/agents/pi-message-queue-experiments.md) |
| [0058](closed/0058-batch-approval.md) | 保留の承認を、見ずに承認することなく少ない操作でできるようにする（巡回・一括承認） | 見送り（巡回まで実装したが、保留ごと撤去。一括は作らなかった） | 2026-11-03 | [CHG-0062](closed/0062-pr-hub-simplify.md)、[ADR-0024](../adr/0024-human-press-merges-in-app.md) |
| [0055](closed/0055-async-approval.md) | 承認つきの操作を、確認が取れなくても失わず、利用者が後から承認して実行できるようにする（非同期承認の実装） | 見送り（実装したが、保留と `/pending approve` を CHG-0062 の段 A5 で撤去。旧形式の退避の list・show・drop だけ残る） | 2026-11-03 | [CHG-0062](closed/0062-pr-hub-simplify.md)、[ADR-0024](../adr/0024-human-press-merges-in-app.md) |
| [0059](closed/0059-child-context.md) | 親と子で文脈（AGENTS.md）を分ける（子に必要な規則だけを渡す） | 採用（実装は完了。既定は従来どおり `inherit`。パイロット 36 実行で抜粋でも規約遵守は同じ、prompt は約 3〜4 割減。既定の切り替えと本評価は利用者が見送り） | 2026-11-02 | [子エージェント](../spec/guard/pi-subagents.md#子の文脈-agentsmd-の抜粋-chg-0059) |
| [0049](closed/0049-gitflow-convention-guard.md) | gitflow-lite の規約（develop / main を直接編集しない）を、pi のガードで強制する | 見送り（実装まで進めたが撤去。規約はコードで強制せず指示で運用する） | 2026-10-31 | [CHG-0050](closed/0050-slim-guarded-action.md)、[ADR-0021](../adr/0021-conventions-as-instructions-slim-guarded-action.md) |
| [0048](closed/0048-ansible-system-layer.md) | sudo を使う Linux のシステム層（apt・`/etc`・サービス）を Ansible に移すと保守しやすくなるかを、実際に移して測って決める | 見送り（Docker での試作で、行数が減らず回避策が増え、まっさらな環境の `--check` が予測にならなかった。残す改善はキープアライブの Linux への共有） | 2026-10-29 | [実測](../research/chezmoi/ansible-trial-121.md) |
| [0041](closed/0041-commit-auto-in-bypass.md) | コミットを bypass のとき確認なしで実行できるようにする（確認の場を push 前へ移す） | 見送り（設計は `review` 10 ラウンドで収束したが、各リポジトリに pre-push のスタブを配備し pre-commit の shim に依存する副作用が、確認の省略に見合わないとして、実装せず閉じた。実測は文書に残した） | 2026-10-27 | [guarded_action](../spec/guard/pi-extensions.md#guarded_action承認つきの外部操作) |
| [0006](closed/0006-pi-harness-trial.md) | Pi / oh-my-pi を利便性の軸で試し、第一サポートを選べる状態を作る | 採用（導入・skills・設定の取り込みまで。第一サポートは別案件で pi に決まり、段 2 以降は `omp` を使っていないので実施せず閉じた） | 2026-10-25 | [omp の設定](../spec/cli-management.md#oh-my-piompの設定)、[ADR-0017](../adr/0017-pi-only-and-ts-judge.md) |
| [0017](closed/0017-builtin-agent-restrictions.md) | 組み込みの `explore` / `plan` の制限が全体の設定に上書きされる問題を直し、`bypass` から起動する子を確認なしで動かせる範囲に整える | 採用（段 0〜8 完了。OpenCode の実機での確認は、OpenCode を使っていないので確認せず閉じた） | 2026-10-25 | [子エージェント](../spec/opencode-config-generation.md#子エージェント)、[ADR-0015](../adr/0015-bypass-child-external-read.md) |
| [0028](closed/0028-verification-speed-and-delegation.md) | 全件の検証を速くし、調査・実装・レビューを子エージェントへ任せる運用を整える | 採用（並列化 `worksteal` で直列 643.67 秒→ 96.25 秒、`verify.py` と Linux の CI、委譲の指示、完了通知の追跡、`todo` の `blocked` と必須化、判定器の穴 3 種の修正。CI の初回結果・`HOME` 隔離・通知の症状の原因は ToDo、`verifier` 役と完了時の自動検証は CHG-0029、`todo` の階層化は CHG-0025 へ移管） | 2026-10-22 | [検証の方針と選択実行](../spec/development.md#検証の方針と選択実行) / [pi のガード](../spec/guard/pi-guard.md) |
| [0002](closed/0002-opencode-ask-by-default.md) | OpenCode の permission を既定 ask にし、秘密への経路を機構で塞ぐ | 採用（段階 0〜3。4a / 4b は見送り、6 は決着。段階 5 の `verify` ツールは pi へ移行するので CHG-0020 へ移管） | 2026-10-09 | [agent-config-generation](../spec/opencode-config-generation.md#既定は-ask) |
| [0019](closed/0019-pi-harness-port-evaluation.md) | OpenCode のハーネスを pi で作り直す価値があるかを判断する | 採用（移行する。構成はツールを自分で持つハーネス。試作で BLOCKER と段 4 の項目がすべて合格。移行は CHG-0020） | 2026-10-09 | [CHG-0020](closed/0020-pi-migration.md) / [試作の記録](../research/agents/pi-harness-spike.md) |
| [0018](closed/0018-opencode-policy-role-split.md) | OpenCode の権限を「共通の禁止」と「役割ごとの権限」に分けて生成する | 一部採用（所有の規則 P のみ。S と段 5 は pi への移行で見送り、プロファイルの設計は CHG-0020 へ） | 2026-10-09 | [agent-config-generation](../spec/opencode-config-generation.md#配置済みの設定の所有) |
| [0015](closed/0015-commit-planner-with-chat-approval.md) | 計画役の子にメッセージ案を作らせ、承認は会話で行う | 採用・配備済み（`--auto` と利用者の TUI で、全文を示して承認を待ち、承認後にコミットした） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0014](closed/0014-deterministic-commit-runner.md) | コミットの表示と実行を決定的なスクリプトに任せる | 見送り（`--auto` では通ったが、利用者の TUI で照合が止まった。部品の多さに見合わないとして取り下げ、親が commit スキルでコミットする形に戻した） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0013](closed/0013-commit-agent-as-planner.md) | commit エージェントを計画役にし、コミットは親が行う | 一部採用（隔離起動でも `git commit` を確認・`git -c … commit` の停止・確認画面の連結形の表示は残した。計画役の `commit` エージェントは廃止） | 2026-10-07 | [コミットの確認](../spec/agent-config-generation.md#コミットの確認) |
| [0008](closed/0008-raspi-branching.md) | Raspberry Pi（64bit / ヘッドレス）を導入対象に加える | 採用・適用済み（実機 3 周目で apply が 45 秒で完走。判定は `.chezmoitemplates/is-raspi` で `chezmoi update` だけで効く。`[data] is_raspi` の方式は撤回） | 2026-09-26 | [プロジェクト構造](../spec/platform-raspberry-pi.md#raspberry-pi) |
| [0010](closed/0010-ocs-agents.md) | `ocs` の中でも `common.toml` のエージェントとコマンドを使う | 採用・配備済み（隔離版の設定にエージェントとコマンドを出した。Fence 化からの差分もレビューループで直した） | 2026-09-29 | [opencode-sandbox](../spec/sandbox/opencode-sandbox.md) / [ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) |
| [0009](closed/0009-ocs-simplify-for-accidents.md) | `ocs` をうっかりの防止に必要な分まで簡素にする（ADR-0012） | 採用・配備済み（境界を Fence に替え、履歴を通常の起動と共有し、承認と起動時の検査をやめた。段 6 は未起票で移管） | 2026-09-29 | [opencode-sandbox](../spec/sandbox/opencode-sandbox.md) / [ADR-0012](../adr/0012-ocs-boundary-for-accidents.md) |
| [0001](closed/0001-compaction-context-handover.md) | compaction を跨いで作業文脈を失わない | 採用・適用済み（圧縮要約そのものを checkpoint にした。Claude / Copilot の hook は撤去） | 2026-09-25 | [checkpoint](../spec/checkpoint.md) / [ADR-0009](../adr/0009-save-before-documenting.md) |
| [0004](closed/0004-opencode-sandbox.md) | OpenCode の保護を OS のアクセス制御へ移す（Ubuntu / WSL のみ） | 採用・適用済み（通常起動と併用。既定を `ocs` にする案は撤回） | 2026-09-24 | [opencode-sandbox](../spec/sandbox/opencode-sandbox.md) |
| [0003](closed/0003-ask-command-description.md) | 確認画面で長いコマンドを判断可能にする | 採用・適用済み | 2026-09-22 | [agent-config-generation](../spec/opencode-config-generation.md#確認画面に出るコマンドの説明) |
