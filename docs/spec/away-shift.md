# away-shift（離席中の検証・実験）

利用者が席を外している間、**承認が要らない操作だけ**で、目標に向けた検証・実験を反復し、戻ったときに読めるレポートを残すスキル。
本体は `home/dot_agents/skills/away-shift/`（`chezmoi apply` で `~/.agents/skills/away-shift/` へ）。停止判定・記録・作業コピーは `scripts/away_guard.py`。
2026-11-10 に、自作基盤（フルガード）前提から、**pi の stock**（公式の既定＋人気の拡張。[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)）前提へ直した。
経緯: [CHG-0030](../change/closed/0030-away-shift-on-pi.md)（フルガードでの対応。凍結で打ち切り）、[CHG-0016](../change/0016-away-shift-opencode.md)（深層学習ジョブの運用。保留）。

## stock での前提（実測・確認の範囲）

| 事実 | 内容 | 確認 |
| --- | --- | --- |
| 無人の確認 | 答えのない確認は 5 分で拒否される（`promptTimeoutMs: 300000`）。承認にはならない。1 回で 5 分失うので、確認になる操作を計画に入れない | 設定と docs。実機で拒否された記録は審査ログにある |
| 子の確認 | 背景の子の確認は、親の画面へ転送される（`forwarded_permission.*`）。実測で約 11 秒で承認され、続行した | 実測（2026-11-10。審査ログ） |
| スクリプトの実行 | `python3 ~/.agents/skills/…` は、`python3` を `read` と宣言し、`~/.agents/skills/*` の読み取りを許可しているので、確認なし | 判定表（`permission_cases.json` の `access`）と、実機の `bg_run` |
| 「離席中」の区別 | 方針は区別できない。`git commit`・`uv add`・`mise use -g`・作業ツリー内の `rm -rf` は、確認なしで通る。禁止は、スキルの指示と、停止時の監査（`git status`・`HEAD`）が担う | `cc-safety-net explain`・判定表 |
| 破壊的な形 | `git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D`・`find -delete` は拒否される | `cc-safety-net explain`（2026-11-10） |

確認になる操作の一覧は、スキル内の `references/stock-pi.md`（方針の写し。迷ったら配備済みの設定を読む）。

## 判断（標準を先に使う: [ADR-0031](../adr/0031-evaluate-existing-extensions-first.md)）

- **事前判定 `preflight.py` は stock では使わない。** 凍結した旧ハーネスの判定器を呼ぶ作りで、stock の実際のガードと食い違う（`git status` を確認にする、など）。
  ファイルと試験は、凍結した custom プロファイル用として残す（`common.toml` の `skill_scripts` と golden の再生成を避ける）。
  実エンジンを呼ぶ自作の事前判定は、維持費に見合わないので作らない。代わりに、確認になる操作の一覧と、「確認が出たら 5 分で拒否される」ことを前提にした運用にした。
- **認可チェーンのリンク（確認の前に自動で引き返す）は作らない。** 標準の機能（方針の `deny` に理由を付ける、操作の `r`）で足りる。無人運転で効果が見えたら、再検討する。
- **再開の仕組み**は 2 通りを評価した（下）。
- **作業範囲を `.tmp/away-shift/` に閉じる強制は無い。** 方針は作業ツリーの中の `write`・`edit` を区別できない。指示と、停止時の監査で担保する。

## 再開の仕組み

| 手段 | 内容 | 状態 |
| --- | --- | --- |
| A: `bg_run` で `away_guard.py sleep <秒> --note …` | ジョブの完了で、アイドルの親が再開する。通知が起動したコマンドを運ぶので、`--note` で run_id と再開手順を載せる。`bg_kill` で取り消す | 3 秒・5 秒・120 秒を実測（2026-11-10。確認なし・再開・`--note` の行が通知に載る）。時間単位は未確認 |
| B: `/goal` の `goal_wait({ resume_after_ms })` | 標準の拡張 `pi-goal`。時間指定で 1 回だけ起こす。予算・無進捗の検出も標準 | 未確認。利用者が `/goal` を打つ必要があり、「戻ったので止める」を、エージェントが `goal_complete`・`goal_blocked` では表せない見込み |

## 未確認

- 時間単位の待機で、再開が届くこと（手段 A。120 秒までは実測）。`goal_wait` による再開（手段 B）。
- 実際の無人（利用者が不在）での通し運転。Windows。
