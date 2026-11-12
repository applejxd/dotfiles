---
name: experiment-loop
description: "ベンチマークのスコアを上げる実験を、複数 seed の測定と統計比較で回す。「ベンチマークを改善したい」「スコアを上げたい」「実験を回して比較」「チューニング」「変更の効果を測る」で使う。実行の記録 (ledger)・信頼区間つきの比較・調整用と検証用の分割の予算・排他ロックを CLI (exp.py) が持つ。単発の計測、本番運用の監視、機械学習の学習ループ自体のコードには使わない。"
---

# experiment-loop

変更の効果より**スコアのばらつきのほうが大きいことがある**。単一の試行で採否を決めず、複数 seed の測定を統計で比べて決める。

## 道具

`python3 ~/.agents/skills/experiment-loop/scripts/exp.py <サブコマンド>` (標準ライブラリだけ。Python 3.9 以上)。以下 `exp` と書く。

| コマンド | 用途 |
| --- | --- |
| `exp init` | 設定の雛形 `.agents/config/experiments.json` を書く（[設定](references/config.md)） |
| `exp run --label NAME --seeds 0-4 [--set k=v] [--note 理由]` | seed ごとに実行し、`.exp/ledger.jsonl` へ 1 回 1 行で記録 |
| `exp compare A B` | B − A の差・95% 区間・効果量・p 値・判定（[計算と限界](references/stats.md)） |
| `exp log` / `exp best` | 記録の一覧 / ラベルごとの順位（平均・n・標準偏差） |

終了コード: 0=成功、2=使い方・設定の誤り、3=失敗した実行がある。

## 実験ループ

1. **ベースラインを先に測る**（`exp run --label base --seeds 0-4`）。
2. **ばらつきを先に測る**。同じ構成を複数 seed で回し、標準偏差を見る。これより小さい差は、1 回の測定では見えない。
3. **計測してから直す**。時間や誤差の内訳を先に取り（プロファイル）、効く所から手を付ける。
4. 仮説を 1 つ立て、**1 つだけ変える**。複数を同時に変えると、効いた原因が分からない。
5. **複数 seed で測る**（`exp run --label 変更名 --seeds 0-4 --note "仮説"`）。
6. `exp compare base 変更名` で比べる。「改善」「悪化」は区間が 0 を含まず p < 0.05 のときだけ。n < 5 の群は「判断できない」になる。
7. 判断を `.exp/decisions.md` に「何を・なぜ・結果（compare の出力）」で記録する。採用なら、次の比較の基準（base）を更新する。
8. 1 に戻る。

## 守ること

- **単一の試行で採否を決めない。** 1 回の良い値は、運かもしれない。
- **自分で入れた計測・デバッグのコードは、測定の前に外す。** 計測自体が遅くしたり、挙動を変える。外した状態で測り直す。
- **調整用（`tune`）と検証用（`val`）を分ける。** 試行錯誤は `tune` だけで行う。`val` は最後の確認だけに使い、`max_runs` の予算を守る（超えると `exp run` が拒否する。`--allow-overrun` は記録に残る逸脱なので、理由を `decisions.md` に書く）。何度も `val` を見ると、検証用に過学習する。
- 測定中は、同じ計算資源を使う別の実行を走らせない（`resources.lock` が排他を担う）。
- ledger（`.exp/ledger.jsonl`）は、変更を示す commit と一緒に残す。各行に commit・dirty・差分のハッシュが入る。

## 停滞したとき

スコアが伸びない・判断に自信がないときは、レビュー役の子エージェント（pi では `reviewer`。独立した相談役）に [監査の依頼](references/audit-checklist.md) を渡し、判断の根拠・未検証の仮説・自分で入れた計測の残り・分割の予算・ばらつきの見積もりを見直させる。

## pi での使い方

- 長い実行（`exp run` が数分以上）は、`bg_run` で背景に回し、終わりを待たずに別の作業（プロファイルの解析など）を進める。
- 監査役は `subagent({ agent: "reviewer", async: true, cwd, task })` で起動し、`task` にチェックリストの雛形を埋めて渡す（会話の転写ではなく、判断の一覧と数字を渡す）。完了は通知で届き、親が自動で再開するので、待たない。
  - `reviewer`（`pi-subagents` 同梱）を選ぶ理由: 見てほしいのは、実験の判断（採否・予算・未検証の仮説）と手元の数字・差分で、`reviewer.md` の「計画・提案された解決・コードの差分」の見直しに当たる。もう一方の `evidence-auditor` は、調査の主張が出典に裏づけられるかを Web の出典で確かめる役（道具は `web_search`・`fetch_content`・`source_check`）で、数字の統計や自前の計測コードの残りは見ない。
  - `reviewer` は読み取り専用で shell を使えない。`exp log`・`exp best`・`exp compare` の出力、`.exp/decisions.md`、計測コードの `git diff` は、親が実行して依頼文に貼る。
  - 実機では未確認（`pi-subagents` の docs とエージェント定義を読んで書いた）。
- スクリプト（`python3 ~/.agents/skills/experiment-loop/scripts/exp.py …`）は、stock の pi では確認なしで実行できる見込み（`python3` は読み取りと宣言済み。実機では未確認）。`uv run …`・`node …` は、作業ツリーの外のパスだと確認になりうる。
