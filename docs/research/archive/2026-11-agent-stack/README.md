# 2026-11 エージェント基盤の凍結の原本（archive）

[CHG-0065](../../../change/0065-agent-stack-freeze.md)・[ADR-0030](../../../adr/0030-freeze-agent-stack-return-to-stock-pi.md) の凍結に伴い、**あとで再検討できるように**、調査・設計・契約書の原文を残す。ホームの絶対パスは `/home/alice` に置き換えてある。原文なので、日本語・英語が混ざり、一部の記述は古い（凍結の時点のもの）。`.txt` なのは、整形ルール（markdownlint）の対象にしないため。

## kcage の clone モード（`kcage-clone-mode/`）

| ファイル | 内容 |
| --- | --- |
| `contract-and-decisions.txt` | 契約（目的・守る条件 C1〜C7・決定 D1〜D20・段階 S0〜S4・決定ログ） |
| `api-contract.txt` | API 契約書（許可表の項目・`model` の型・ファイル形式・`gitsync/` の各モジュールの署名・箱の helper の動詞・CLI・波と担当）。末尾に波 1 の結果の更新 |
| `design-single-repo.txt` | 単一 repo の clone モードの計画（方式 M0〜M3 の比較・運用手順・段階） |
| `design-multi-repo.txt` | 複数 repo（virtual monorepo）の設計（列挙・seed・take・ワークスペース・wip・view・S0） |
| `git-safety-policy-notes.txt` | git の安全方針の整理（保留のまま） |
| `repro-mv-git.sh.txt`・`repro-mv-git-pin.sh.txt` | `mv .git` の迂回の再現と、`.git` の pin で封じる確認（bubblewrap。`.txt` を外して実行する） |

実装は枝 `feature/kcage-clone-*`（未統合）。一覧と復元は [CHG-0065](../../../change/0065-agent-stack-freeze.md#未完の作業凍結した枝)。

## 同種の OSS の評価の原文（`oss-evaluations/`）

`coi-summary.txt`・`coi-security-and-auth.txt`・`coi-features.txt`・`coi-maintenance-and-integration.txt`・`isx-summary.txt`・`isx-security-auth-git.txt`・`isx-features-maintenance.txt`。要約は [評価](../../agents/oss-sandbox-evaluations-2026-11.md)。

## ツール隔離の実現性の原文（`tool-isolation/`）

`pi-api-survey.txt`（pi の公式 API・例）・`harness-local-assumptions.txt`（ハーネスのローカル前提・挿入点）・`spike-brief.txt`（最小プロトタイプの依頼文。未着手）。要約は [実現性](../../agents/tool-isolation-feasibility-2026-11.md)。

## 自作路線の見直しの相談の原文（`consult/`）

`own-first-review.txt`（外部 AI との相談。2026-11-09。利用者名・アカウント名は置換済み）。要点は [ADR-0031](../../../adr/0031-evaluate-existing-extensions-first.md)。外部の内容として扱い、鵜呑みにしない。

## stock の pi の package 追加分の評価の原文（`pi-eval/`）

`background.txt`（背景シェル実行）・`plan-goal.txt`（plan mode と /goal）・`rewind-notify.txt`（巻き戻しと通知）・`status.txt`（ステータス表示）。通知とステータス表示の節は、利用者と相談中で決定していない。要約は [評価](../../agents/pi-stock-packages-evaluation-2026-11.md)。

`orchestration-candidates.txt`・`orchestration-subagents.txt`（オーケストレーションの候補と `pi-subagents` の調査。2026-11-09。結論は [評価](../../agents/pi-stock-packages-evaluation-2026-11.md) の「オーケストレーションの評価と決定」）。
