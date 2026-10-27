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
| [0011](0011-agent-first-shell.md) | AI エージェントがシェルの主な利用者である前提へ整える | In progress | Claude Code へ git の環境変数を入れる方法が保留（`CLAUDE_ENV_FILE` と比較）。Windows は人が開いた対話シェルと本物の Copilot CLI での引き継ぎが未確認 | ocs の実機で deny の前段停止（pip 以外へ拡張済み）を確かめる | 2026-10-07 |
| [0012](0012-bash-hook-shared-parser.md) | bash 検査 hook のコマンド解析を 1 か所に集める | In progress | Windows 実機で未検証。B 群（`shlex.split` の規則）は保留 | Windows の PowerShell で `test/agents/` を回し、通れば閉じる | 2026-10-06 |
| [0020](0020-pi-migration.md) | OpenCode のハーネスを pi へ移す（判定 API・ハーネス・配布・境界・ハーネス以外の機能・撤去） | In progress | 段 1〜5 は完了。Orca・Zed は素の `pi`、`pis` は利用者の起動用で優先度低（利用者の判断）。残りの段 6（OpenCode の撤去）は任意で保留。Windows は OpenCode を残すか未定 | 段 6 を進めるか判断する（OpenCode はもう使わないが急がない。`checkpoint` も一緒に消す。進めるなら Windows の扱いを先に決める） | 2026-10-21 |
| [0021](0021-windows-admin-consolidation.md) | Windows の chezmoi セットアップを整え、管理者権限の作業を 1 回の UAC に集約する | In progress | UAC 承認を含む通し実行が未検証（クリーンな Windows 実機が要る）。Python Launcher と Orca の UAC の有無が未確認。管理者グループの利用者の `administrators_authorized_keys` が未対応 | クリーンな Windows で `chezmoi apply` を通し、UAC が 1 回だけ出ることを確かめる | 2026-10-10 |
| [0022](0022-windows11-settings-review.md) | Windows 11 の設定を見直し、古い設定の修正と体験の改善を入れる | In progress | 段 1・2・3・4・6・7・8 は完了（ウィジェットは自動化を見送り）。`gow` と WSL・WSL 3 は保留 | `gow` の履歴の再集計、WSL の取り組み | 2026-10-12 |
| [0023](0023-guard-terminology.md) | 「ハーネス」の呼び方を整理し（ガード / フルガード / 簡易ガード / サンドボックス）、`pis` をサンドボックス既定にする | In progress | 段 3a・3b・3d・3f は完了、3c は実装済み（実機の試験で 3 つの不具合を直した。3c・3f の反映後の実機は未確認）。設計原則は [ADR-0018](../adr/0018-pis-sandbox-default-relax-only-when-proven.md)。共有 `~/.pi/agent`・認証プロキシ・Orca の状態表示が未決。段 3g の後半・段 4 は保留 | `chezmoi apply` 後に 3c・3f の実機を確認、事前検査の初回の所要時間 | 2026-10-15 |
| [0024](0024-diagnostics-feedback.md) | 編集直後の診断フィードバック (LSP・linter・型検査) を足す | Planned | どの言語・道具まで対応するか。型検査の実行の頻度。LSP の常駐とガード・サンドボックスの関係 | 段階案 A (post_edit の延長) の対象言語を決める | 2026-10-20 |
| [0025](0025-goal-autonomous-loop.md) | `/goal` の自律ループ (目標・計画・独立した完了の監査) を足す | Planned | 予算の既定値と停滞の検知。`agent_before_settle` で続行を複数回要求できるか。bypass との相互作用 | 段階案 A (todo のリマインドの延長) で複数回の続行を実測する | 2026-10-20 |
| [0027](0027-zed-pi-acp-with-pis.md) | Zed の pi-acp から `pis --no-sandbox`（フルガード）を使えるようにする | Exploring | Zed の `env` から `PI_ACP_PI_COMMAND`（ラッパーのパス）を渡して実際に起動できるか、起動の遅さ（約 4 秒以上）。ソースの読みでは `confirm` は Zed のダイアログになる | `npx` で pi-acp を取得し、`PI_ACP_PI_COMMAND` を付けて ACP を手で送る。または、ACP 経由ではなく、Zed の Terminal Threads で `pis` を直接起動して BEL で通知する候補 G を実機で確かめる（`notify` 拡張。完了・確認待ち・`ask` で青丸が出るか）。Orca のネイティブチャットは WSL で使えない | 2026-10-21 |
| [0030](0030-away-shift-on-pi.md) | `away-shift` を pi（フルガード）で、無人でも止まらずに動く形にする | Exploring | pi ではスキルのコマンドがすべて確認になり、無人だと最初の `init` で止まる。許可規則の追加（`away_guard.py` の閉じ込め・`sleep`）は境界の変更で、`write` が `.tmp` に限られない点は役割 `away` の検討（保留） | P1（文書と `preflight.py`）と P2（`away_guard.py` の閉じ込め・許可規則・上限つき `sleep`）は実装済み（最終レビューの修正も反映済み）。P3（役割 `away`）は保留 | 2026-10-22 |
| [0031](0031-delegate-nudge.md) | 親エージェントが委譲を忘れないよう、読み取り量に応じた注記（ナッジ）を出す | Exploring | 注記が効くか（先行例に効果の実測が無い）。出し方（`tool_result` の末尾へ足すか、`sendMessage` の steer で独立させるか）。帯の値 | `review` に設計案を見せてから N1（試作）。統計だけの版を先に入れる案 | 2026-10-22 |
| [0029](0029-worktree-isolation.md) | 子エージェントの実装作業を git worktree で分離し、検証を子の隔離環境で回せるようにする（CHG-0026・0028 の未完事項の移管先） | In progress | 隠離の前提（Fence 配下の子が linked worktree で動けるか、共有 `.git` や親の作業ツリーへ書けるか、スナップショットの往復。W0a・W0b で実測済み: 子は linked worktree で動け、兄弟・本体の作業ツリーへは書けないが、`update-ref` で共有 refs を書ける） | S5: 利用者の実機 `pis` での通し確認（手順書 `scripts/agents/s5_isolation.sh`）。W2 以降は未着手 | 2026-10-24 |
| [0032](0032-guard-url-false-positive.md) | 判定器と、検索・取得のスクリプトの検査が、URL を誤検出して調査を止めないようにする | In progress | 実機（`chezmoi apply` 後の `pis`）で、取れなかった記事が取れるか。許容した限界（`=` 直後の URL、URL 内の小文字のパスフレーズ） | CHG-0033 の段 P1 の再調査で実機の確認 | 2026-10-23 |
| [0033](0033-sandbox-build-value-assessment.md) | 自作したサンドボックスに価値があったかを、サンクコストを除いて、エビデンスで判定する | Exploring | nono をこの環境で試した実測が無い。コマンド内容を解析する既製品が本当に無いか。判定器の限界価値 | 暫定の判定は「部分的に置き換え（縮小）」。Python 版オラクルの撤去の案件化、nono の小さな試験 | 2026-10-24 |
| [Windows ネイティブ（PowerShell）で pi を、OS の境界つきで動かす](0034-windows-native-pi-boundary.md) | リポジトリが Windows 側で、Windows 起動前提のアプリも開発するので、Windows ネイティブで pi を境界つきで動かしたい（OpenShell・Docker Sandboxes は合わない） | Exploring | `srt` の Windows alpha で `pi` を包めるか。サーバ・アプリの起動と通信の制御が両立するか。Windows 実機が要る | 段 W1: Windows 実機で `srt` に `pi` を包む手順書を作り、利用者に実行してもらう | 2026-10-24 |
| [0035](0035-retire-python-judge-oracle.md) | 判定器の Python 版（オラクル）を撤去して、二重保守を解消する | Exploring | 「実機での観察」の定義（ADR-0017 に無い）。正解データを Python 版なしで保つ設計 | 段 R1: 撤去の条件を利用者と決める。段 R2: 凍結か書き出しかの設計を `review` へ | 2026-10-24 |
| [0036](0036-nono-trial-on-wsl2.md) | nono を WSL2 で小さく試し、境界の層（`ocs`）の置き換えの可否を測る | Exploring | WSL2 で nono がドメインの許可リストを標準では提供しない（現行の境界との差）。導入に利用者の許可が要る | 段 N1: 導入と `nono setup --check-only` の許可を尋ねる | 2026-10-24 |
| [0037](0037-pis-usability-and-telemetry.md) | `pis` の使い勝手を、他のプロジェクトで常用できる水準に上げ、運用の記録を取る（便益を測る前提） | Exploring | 通信を拒否リスト型に引き直す設計。認証情報を内側に置かないホスト側のブローカー（Envoy。設定 `[pis.broker]` で `pis` と同寿命。Copilot は実機で応答 OK）。境界つきのネット調査が通るか未検証 | 段 U7a: 利用者が `pis` を普段どおり使う（24 時間後の再読み込みの確認）。Envoy は `chezmoi apply` が導入。続けて段 U7b（Bedrock、制約のある環境の機） | 2026-10-24 |
| [0038](0038-guard-reclassification.md) | ガードを「防ぐ害」（UX・認証情報・外部送信・破壊・構造）で分類し直し、外部への送信・公開の穴を塞ぐ（`confirm` の新設） | In progress | 標準の `pis`（bypass オン）で、規則に載っていない外部書き込みと載っている ask が確認なしで通る。`confirm`（bypass 不可・内容つき・無反応は deny）の実装設計。分類は整理で、区分の on/off の仕組みは作らない | 段 G5: 実機の確認（利用者）。段 G6: C1 の棚卸し | 2026-10-24 |
| [0039](0039-bell-with-message.md) | 入力待ちの通知（BEL）に、メッセージを添える | Exploring | BEL は 1 バイトで本文を運べない。OSC 9 / 777 で本文を運べる可能性があるが、使っている端末（Zed・Orca）の対応は未確認。BEL は必ず残し、非対応の端末で表示を壊さない形を基本にする | 段 N1: 端末での確認（利用者） | 2026-10-26 |
| [0040](0040-pi-guard-by-settings.md) | pi のフルガードを設定で載せ、pis をサンドボックス専用に寄せる | Exploring | 素の pi（Unix）が settings.json だけでフルガード付きで起動する。作業先の信頼は既定の確認のまま、判定の外で動くもの（mcp.json・信頼した作業先の .pi/）は警告する。pis --no-sandbox は移行用に残す | Windows への展開（配備・子エージェント・MSYS のパス）、実機の確認 | 2026-10-26 |
| [0042](0042-tmp-lifecycle.md) | `.tmp/` をセッションごとの置き場に分け、終わりに消す（取り込むものは残す） | In progress | 対話モードでの `quit`・`/new`・`/resume`・`/fork`・`reload` の実機の確認（実装は段 2・3・4・6 完了。未確認は、これだけ） | 実機で `.tmp/s/<ID>/` の作成・`quit` での削除・SIGKILL の後の回収を確かめ、問題なければ Done へ | 2026-10-27 |
| [0043](0043-model-catalog.md) | 子エージェントのモデルを、最新のカタログから、ユーザの指示で選べるようにする（effort は自由） | In progress | Bedrock のカタログの `verified`（pi から GPT-6.1 へのツール呼び出しが未確認。`enforce_verified = false`）。実効の段の表示は未実装 | Bedrock を使える環境で `mise run models:probe`。確認後に `verified`・`enforce_verified` を `true` へ | 2026-10-27 |

## 保留

| # | 目的 | 保留理由 | 再開条件 | 更新日 |
| --- | --- | --- | --- | --- |
| [0007](0007-harness-profiles.md) | 境界をハーネス非依存にする（3 層プロファイル） | 段 5 の待ち先だった CHG-0006 は閉じた（第一サポートは pi）。段 2 の対象（`[opencode.sandbox]` の節分け）は OpenCode 撤去（CHG-0020 段 6）と競合する | 境界へ入れたいハーネスが 2 つ目になったとき。または OpenCode を撤去しないと決めたとき | 2026-10-25 |
| [0005](0005-agents-config-naming.md) | `common.toml` の命名を実態に合わせ、固有設定を分離する | 段階 A1 完了 / A3 消滅 / A4 保留（checkpoint の A1 / A2 とは別の、この案件の段階番号）。残る A2 は第一サポートが変われば対象も変わるため、先に動かすと手戻りになる | CHG-0020 の段 6 で OpenCode の節を撤去したあと（第一サポートが pi に決まった）。なお A2 の前提である ADR-0007 規則 3 との矛盾と、A1 で取り残した `[file]` 節のコメントは、それと独立に片付けられる | 2026-10-09 |
| [0016](0016-away-shift-opencode.md) | 深層学習ジョブの調査・再開を away-shift で任せる運用を決める（旧: OpenCode 向けの最適化。2026-10-25 に段 2 だけ残して書き直し） | 段 2 のみ残して保留。pi 対応は CHG-0030 が引き継いだ | 利用者が着手を指示したとき。前提: CHG-0030 の実機確認 | 2026-10-25 |
| [0026](0026-specialist-agents-with-skills.md) | 専門スキルを、専用の子エージェント (migrator・writer) に持たせる。`away-shift` は親のスキルのまま残す | 構想のみ。子の質問の中継 (ask-user 段 2) が未実装で、圧縮の修理を先にするため一旦保留 | 子の質問の中継が使える。圧縮の修理が済む。専門スキルの利用が増える。CHG-0029 の W1（worktree 隔離）が済む | 2026-10-22 |

## 終了

| # | 目的 | 結果 | 終了日 | 現行仕様 / ADR |
| --- | --- | --- | --- | --- |
| [0041](closed/0041-commit-auto-in-bypass.md) | コミットを bypass のとき確認なしで実行できるようにする（確認の場を push 前へ移す） | 見送り（設計は `review` 10 ラウンドで収束したが、各リポジトリに pre-push のスタブを配備し pre-commit の shim に依存する副作用が、確認の省略に見合わないとして、実装せず閉じた。実測は文書に残した） | 2026-10-27 | [guarded_action](../spec/guard/pi-extensions.md#guarded_action承認つきの外部操作) |
| [0006](closed/0006-pi-harness-trial.md) | Pi / oh-my-pi を利便性の軸で試し、第一サポートを選べる状態を作る | 採用（導入・skills・設定の取り込みまで。第一サポートは別案件で pi に決まり、段 2 以降は `omp` を使っていないので実施せず閉じた） | 2026-10-25 | [omp の設定](../spec/cli-management.md#oh-my-piompの設定)、[ADR-0017](../adr/0017-pi-only-and-ts-judge.md) |
| [0017](closed/0017-builtin-agent-restrictions.md) | 組み込みの `explore` / `plan` の制限が全体の設定に上書きされる問題を直し、`bypass` から起動する子を確認なしで動かせる範囲に整える | 採用（段 0〜8 完了。OpenCode の実機での確認は、OpenCode を使っていないので確認せず閉じた） | 2026-10-25 | [子エージェント](../spec/opencode-config-generation.md#子エージェント)、[ADR-0015](../adr/0015-bypass-child-external-read.md) |
| [0028](closed/0028-verification-speed-and-delegation.md) | 全件の検証を速くし、調査・実装・レビューを子エージェントへ任せる運用を整える | 採用（並列化 `worksteal` で直列 643.67 秒→ 96.25 秒、`verify.py` と Linux の CI、委譲の指示、完了通知の追跡、`todo` の `blocked` と必須化、判定器の穴 3 種の修正。CI の初回結果・`HOME` 隔離・通知の症状の原因は ToDo、`verifier` 役と完了時の自動検証は CHG-0029、`todo` の階層化は CHG-0025 へ移管） | 2026-10-22 | [検証の方針と選択実行](../spec/development.md#検証の方針と選択実行) / [pi のガード](../spec/guard/pi-guard.md) |
| [0002](closed/0002-opencode-ask-by-default.md) | OpenCode の permission を既定 ask にし、秘密への経路を機構で塞ぐ | 採用（段階 0〜3。4a / 4b は見送り、6 は決着。段階 5 の `verify` ツールは pi へ移行するので CHG-0020 へ移管） | 2026-10-09 | [agent-config-generation](../spec/opencode-config-generation.md#既定は-ask) |
| [0019](closed/0019-pi-harness-port-evaluation.md) | OpenCode のハーネスを pi で作り直す価値があるかを判断する | 採用（移行する。構成はツールを自分で持つハーネス。試作で BLOCKER と段 4 の項目がすべて合格。移行は CHG-0020） | 2026-10-09 | [CHG-0020](0020-pi-migration.md) / [試作の記録](../research/agents/pi-harness-spike.md) |
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
