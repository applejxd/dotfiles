# 探索・変更案件

これから実装すること、いま探索していることの記録。

[ドキュメント一覧へ戻る](../index.md)

## 今の作業計画（活動中）

利用者が今の作業計画を追うための 1 枚（2026-11-12 時点。節目＝開始・方針の変更・完了・依頼のときだけ更新する。[ADR-0032](../adr/0032-docs-by-audience.md)）。

| 作業 | 何を | 今どこ | 次の一手 | あなたが決めること | 関連 |
| --- | --- | --- | --- | --- | --- |
| 旧ハーネスの撤去 | 旧 custom プロファイルと pi 以外のハーネス（PR ビューア・kcage・台帳を含む）を撤去し、試験を 1.4 万件から約 1,600 件へ | **完了**（`develop` に統合済み。2026-11-12。タグは origin に push 済み。凍結した未統合の枝 13 本は削除し、ローカルのバンドルへ退避） | `main` への統合と、各機での `chezmoi apply`。後続: 死んだコード（`PIS_FETCH_VIA_PROXY`）の撤去・残った試験の重複の洗い出し | `main` へ統合する時期 | [ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md) |
| stock の pi への移行 | 自作基盤を凍結し、公式の pi＋人気の拡張へ | **完了**。stock が既定のプロファイル（2026-11-10）で、実機で使用中。権限の方針は「YOLO を切る前提の deny と強制 ask」で、全 deny に理由がある（ask には理由の仕組みが無い） | 1〜2 週間使い、足りない所を `friction-review` スキルでセッションのログから洗い出す | なし | [CHG-0065](closed/0065-agent-stack-freeze.md)・ADR-0030・[拡張の評価](../research/agents/pi-stock-packages-evaluation-2026-11.md) |
| 検索 MCP（家の機向けの自作 1 件） | 検索を MCP サーバで提供する | 統合済み（本体・stock への登録・plan mode でも使える・スキル `web-search` の廃止と imozuru の書き換え）。実機での確認の記録は無い | 使いながら確認 | なし | [web-search 仕様](../spec/web-search.md) |
| 圧縮（コンパクト化）の方針 | 圧縮の要約を「続きの作業のための brief」にする | 決定・統合済み。70 万トークン（`reserveTokens` 30 万）で圧縮し、`pi-compaction` は要約の指示（brief）だけに使う。根拠: 過去セッションの集計で、長い文脈の劣化の兆候は見つからなかった。自作は足さない | 実機で確認（`/compaction-settings show`・1 回目の圧縮が brief になっているか） | なし | [圧縮の研究ノート](../research/agents/long-context-compaction-paper-2026-11.md) |
| 子エージェントの運用（`pi-subagents`） | 子の起動を常設の指示で授権し、数の上限を外し、役ごとにモデルと権限を決める | 実装・統合済み（2026-11-11）。`reviewer`・`oracle`・`evidence-auditor` は親と別系統の GPT 6.1 sol。作業ツリーの外は子でも即拒否。**常設の指示が実際に効くか（指示なしに子を起動するか）は未観察** | 1〜2 週間使い、起動すべき場面で起動するか・過剰でないかを見る | [ADR-0033](../adr/0033-delegate-subagents-by-standing-instruction.md)（Proposed）を Accepted にするか | [仕様](../spec/agent-config-generation.md)・oracle のモデル・[子の権限の実測](../research/agents/subagent-permission-frontmatter-2026-11.md)・[運用ガイド](../../.agents/skills/feature-orchestration/references/pi-subagents.md) |
| away-shift（離席中の検証） | 親が監督し、専用 worktree の子へサイクルを任せる。利用者は離席と戻りの時刻を言うだけ | 再設計・実装済み（2026-11-10）。リハーサル 5 サイクルを通過し、確認（ask）は 0 件。**数時間規模の運転・子 1 回あたりのトークン・Windows/macOS は未測定** | 実際に離席する機会に 1 回回す | なし | [仕様](../spec/away-shift.md) |
| skill の置き場と掃除 | 自作 skill を `~/.agents/skills` へ移し、stock の pi 向けに書き直す | 完了（置き場の移動・`~/.agents/skills` の読み取り許可・`reviewer` への書き直し・`feature-orchestration` を stock の運用を既定に・`github-operations` の承認を権限の確認に一本化） | なし | なし | [skill の frontmatter](../spec/skill-frontmatter.md) |
| docs の見直し（この変更） | 読み手別に整理する縮小版（D 案）を試作 | D 案の試作を統合し、使って確かめる段階（ADR-0032 は Proposed）。2026-11-11 に、直近 2 週間の作業の抜け（ADR-0033・0034、この表、仕様の細部）を補った | この 1 枚で今の作業計画が追えるか確かめる → 追えれば、`commit` スキルと `sdd-docs` の変更（共通のスキルを縮小。案件更新の自動呼び出しと索引の自動補完を外す） | 試用のあと、ADR-0032 を Accepted にするか | [ADR-0032](../adr/0032-docs-by-audience.md) |
| pi の sandbox（層 b）の見直し | GPU を通す sandbox（`pib`）を、拡張なしの `shellPath` の囲いへ作り替える（bash・`bg_run`・`!`・子の bash を同じ囲いで包む。許可リスト型） | 決定（ADR-0036）と実装を feature に入れた（2026-11-12。未統合）。試験 153 件と実機の自己確認（GPU を含む）は PASS。pi を通した実測も通った | 統合の指示を受けて統合し、`chezmoi update` で配備して `pib` を使い始める。TUI の `!` と、YOLO を切ったときの確認を実機で確かめる | 統合の指示。守る対象（ADR-0036 の 6）の確認 | [CHG-0066](0066-pi-sandbox-boundary.md)・[ADR-0035](../adr/0035-pi-sandbox-gpu-runner.md) |

凍結した案件は「終了」へ移した（入口は [CHG-0065](closed/0065-agent-stack-freeze.md)。凍結した基盤は 2026-11-12 に撤去した）。停滞した案件はこの表に入れない（下の「活動中」「保留」に残る）。

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
| [0021](0021-windows-admin-consolidation.md) | Windows の chezmoi セットアップを整え、管理者権限の作業を 1 回の UAC に集約する | In progress | UAC 承認を含む通し実行が未検証（クリーンな Windows 実機が要る）。Python Launcher と Orca の UAC の有無が未確認。管理者グループの利用者の `administrators_authorized_keys` が未対応 | クリーンな Windows で `chezmoi apply` を通し、UAC が 1 回だけ出ることを確かめる | 2026-10-10 |
| [0022](0022-windows11-settings-review.md) | Windows 11 の設定を見直し、古い設定の修正と体験の改善を入れる | In progress | 段 1・2・3・4・6・7・8 は完了（ウィジェットは自動化を見送り）。`gow` と WSL・WSL 3 は保留 | `gow` の履歴の再集計、WSL の取り組み | 2026-10-12 |
| [0047](0047-gitflow.md) | main 一本から gitflow（main / develop / feature）へ切り替える（feature の起票・クローズの AI 化は CHG-0050 で撤去。動機: コミット粒度・main の安定・並列開発） | In progress | ブランチモデルは運用中。起票・クローズは利用者のシェル、AI は feature の worktree の `pi` から `git_commit`。経緯の本文は撤去前の設計の記録 | 実機で、feature の worktree から `git_commit` が期待どおり動くかを確認 | 2026-10-31 |
| [0051](0051-verification-tiers.md) | 検査（verify / verify:all）を段階化し、安い検査を先に・重い検査を後にする（失敗の見つかる順序・並列度・印の記録を直す） | In progress | T0 / T1 / T2 の段階化、fail-fast、並列度の上限と nice、印の開始時記録を実装済み。故意の失敗で 23 秒で止まることを確認 | 印の段と義務の置き場の判断、`AGENTS.md` の縮約、`pi` を起動する試験の起動費用の削減 | 2026-10-31 |
| [0066](0066-pi-sandbox-boundary.md) | pi のコマンド実行を包む囲いの問題を洗い出し、境界を決めて実装する（ADR-0036。拡張を外し、`shellPath` の囲いにした） | In progress | 実装は feature に入れた（未統合）。TUI の `!` と、YOLO を切ったときの確認の実機の試験は未実施 | 統合の指示を受けて統合し、配備して使い始める | 2026-11-12 |

## 保留

| # | 目的 | 保留理由 | 再開条件 | 更新日 |
| --- | --- | --- | --- | --- |

## 終了

| # | 目的 | 結果 | 終了日 | 現行仕様 / ADR |
| --- | --- | --- | --- | --- |
| [0065](closed/0065-agent-stack-freeze.md) | エージェント基盤の全面凍結と、公式既定の pi への切り替え（記録と再開の手引き） | 完了（凍結の記録。再開の入口。凍結の作業が終わった） | 2026-11-09 | [CHG-0065](closed/0065-agent-stack-freeze.md)・ADR-0030 |
| [0048](closed/0048-ansible-system-layer.md) | sudo を使う Linux のシステム層（apt・`/etc`・サービス）を Ansible に移すと保守しやすくなるかを、実際に移して測って決める | 見送り（Docker での試作で、行数が減らず回避策が増え、まっさらな環境の `--check` が予測にならなかった。残す改善はキープアライブの Linux への共有） | 2026-10-29 | [実測](../research/chezmoi/ansible-trial-121.md) |
| [0028](closed/0028-verification-speed-and-delegation.md) | 全件の検証を速くし、調査・実装・レビューを子エージェントへ任せる運用を整える | 採用（並列化 `worksteal` で直列 643.67 秒→ 96.25 秒、`verify.py` と Linux の CI、委譲の指示、完了通知の追跡、`todo` の `blocked` と必須化、判定器の穴 3 種の修正。CI の初回結果・`HOME` 隔離・通知の症状の原因は ToDo、`verifier` 役と完了時の自動検証は CHG-0029、`todo` の階層化は CHG-0025 へ移管） | 2026-10-22 | [検証の方針と選択実行](../spec/development.md#検証の方針と選択実行) / pi のガード |
| [0008](closed/0008-raspi-branching.md) | Raspberry Pi（64bit / ヘッドレス）を導入対象に加える | 採用・適用済み（実機 3 周目で apply が 45 秒で完走。判定は `.chezmoitemplates/is-raspi` で `chezmoi update` だけで効く。`[data] is_raspi` の方式は撤回） | 2026-09-26 | [プロジェクト構造](../spec/platform-raspberry-pi.md#raspberry-pi) |
