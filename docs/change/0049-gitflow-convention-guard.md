# CHG-0049: gitflow-lite の規約（develop / main を直接編集しない）を、pi のガードで強制する

- **状態**: In progress
- **更新日**: 2026-10-30
- **基準**: コミット 6da89822 以降（[CHG-0047](0047-gitflow.md) の実装の後）

## 背景

AI が develop のまま実装を始めた。通常の `git worktree add` で作った worktree は、`gitflow_feature_finish` の自動片付けの対象外で残骸になり、`git worktree remove` は bash では deny なので、AI が消せなかった。
CHG-0047 は、素の git のブランチ操作を共通の規則では deny にしない方針（リポジトリごとにモデルが違うため）で、指示（`commit` スキルなど）に頼っていた。指示だけでは守られなかった。

## 目的と非目的

**目的**: gitflow-lite のリポジトリで、AI が develop / main の作業ツリーを**直接編集・コミットしない**ようにする。判定の外側に追加の制限層を足す。

**非目的**: bash の中の書き込み・外部スクリプトの強制。Python 版（Claude / OpenCode）への複製（[ADR-0017](../adr/0017-pi-only-and-ts-judge.md)）。`decide.ts`・`common.toml.tmpl`・正解データの変更。

## 実施計画

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1a | 基盤: git の状態の収集（`gitstate.ts`）、純関数の gate、`tighten`、`identifyModel` | 実装済（実機は未検証） |
| 1b | `edit` / `write` の制限と `git_commit` の拒否。実行直前の取り直し | 実装済（実機は未検証） |
| 1c | 素の git による直接のブランチ・worktree の作成（`worktree add`・`switch -c` など）を deny | 未着手 |
| 2a | セッション開始時に、規約を注入する | 未着手 |
| 2b | 利用者専用の逃がし口（develop / main で作業したいとき） | 実装済（実機は未検証） |

## 現在地

仕様の正本は [pi の gitflow 規約の強制](../spec/guard/pi-gitflow-guard.md)。保護の対象・結果の表・保証の範囲・試験はそちらを見る。

- **保証外**: bash の中の書き込み、外部スクリプト、`bg_run`、`git worktree add` / `switch -c` などの直接の作成（段 1c まで）
- **利用者への影響**: develop / main で作業したいときは、利用者が入力欄から `/gitflow-allow [edit|commit|all] [分]` で、時間を限って許可できる（段 2b。モデルは呼べない。確認画面で承認したときだけ付与し、ブランチの変化・期限・`off` で失効する）。`.git/` の中・git を読めないとき・外部への送信の確認は、許可でも緩めない。詳細は仕様の「逃がし口」
- **入れ子のリポジトリ（`dir`、コミット d00cc357、2026-10-30）**: `git_commit` は常にセッションの cwd で動くため、cwd の中の独立したリポジトリ（仮想 monorepo の子）でコミットできなかった（`git -C 子 commit` も `git commit` に正規化されて同じツールへ誘導される。コードの読みからの見立てで、実際のエラー文は未確認）。`git_commit` に任意の `dir`（cwd からの相対パス）を足した。この規約の判定は、`dir` を指すときは**解決済みの子のブランチ**で行う（親が develop でも、規約の対象外の子はコミットでき、子が develop なら拒否する）。解決後と実行直前に判定を掛け直し、承認の間に指す先が変われば拒否する。`GIT_DIR` など対象を変える環境変数があれば拒否する。設計は独立した `review`（`gpt-6.1-sol`）を反映済み（解決済み対象への判定、`GIT_*`、退避の場所、`dir` では WIP を自動承認しない）。仕様は [pi の拡張](../spec/guard/pi-extensions.md#guarded_action承認つきの外部操作)の `dir` の項。限界: 最後の syscall 直前の差し替えは原子的には防げない（実機の競合の再現は未確認）。Windows と実際の Orca は未検証
- **CHG-0047 への影響**: 「素の git を deny にしない」方針は、gitflow-lite のリポジトリでは、この案件が一部（直接の編集・コミット。段 1c でブランチ・worktree の作成）を deny にする

## 設計の根拠

設計レビューの要点。

- `.gitflow` の存在だけでなく、**コミット済みの内容**で識別する（作業コピーの削除・改変でガードが外れない）
- cwd ではなく、**編集対象パスの所有 worktree** で判定する（本体から feature の worktree を編集する正規の運用を止めない）
- docs の例外を作らない（`finish` が本体の追跡ファイルの変更を拒否するため、編集できても統合できなくなる）
- 状態に依存する判定は、**execute の直前に取り直す**（`tool_call` の判定のキャッシュは git の状態の変化を検出しない）
- git を読めないときは許可に倒さない（`edit` / `write` は確認、`git_commit` は deny）

## 検証

`test/agents/test_pi_gitflow_guard.py`・`test_pi_gitstate.py`・`test_pi_gitflow_guard_harness.py`・`test_pi_gitflow.py`。実機（実モデル・TUI・Windows）は**未検証**。
