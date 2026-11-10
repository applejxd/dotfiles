# away-shift（離席中の検証・実験）

利用者が席を外している間、**専用の git worktree（枝つき）で子エージェントに検証・実験を反復させ**、戻ったときに枝とレポートを渡すスキル。
利用者がすることは、離席と戻りの時刻を言うだけ（準備は全自動）。統合するかどうかは利用者が決める。
本体は `home/dot_agents/skills/away-shift/`（`chezmoi apply` で `~/.agents/skills/away-shift/` へ）。準備・停止判定・記録・事後監査は `scripts/away_guard.py`。
2026-11-10 に、自作基盤（フルガード）前提から、**pi の stock**（公式の既定＋人気の拡張。[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)）前提へ直し、
続けて「親が監督し、サイクルごとに新しい子を専用 worktree で動かす」形へ再設計した（下のリハーサル）。
経緯: [CHG-0030](../change/closed/0030-away-shift-on-pi.md)（フルガードでの対応。凍結で打ち切り）、[CHG-0016](../change/0016-away-shift-opencode.md)（深層学習ジョブの運用。保留）。

## 構成（親・子・worktree）

| 役 | どこで | 何をする |
| --- | --- | --- |
| 親 | 本体の作業ツリー | `prepare`・サイクルの起動・**再検証**・記録・`check`・停止・`audit`・レポート。実験はしない。本体を変えない |
| 子（`subagent`、`async: true`） | 専用 worktree（`cwd` に指定。枝 `feature/away-<run_id>`） | 1 サイクルの実験。**サイクルごとに新しい子**。コミットとローカルな依存の変更は自由 |
| worktree | `.tmp/worktrees/away-<run_id>/`（本体の中。親が自由に読める） | 子の作業場。外への書き込みは確認（無人では 5 分で拒否） |

- **引き継ぎはファイル**: worktree の `.tmp/away/`（`brief-common.md`・`cycle-<N>-task.md`・`cycle-<N>.md`・`notes.md`）。子から見て本体の `.tmp/` は外側（確認になる）。
- **成功の判定は親が再検証**する（worktree で同じコマンドを実行）。子の自己申告は当てにしない。
- 子の完了通知が、親の再開の契機になる（`sleep` は不要）。期限は `timeoutMs`＋`checkpointBeforeDeadlineMs`（実行器が割り込む）。
- 成果は**枝とレポート**。停止時に `audit` が、本体の `HEAD`・`git status` が開始時のままかと、枝のコミット・差分、残ったプロセスを出す。
- 準備は `away_guard.py prepare --goal … --deadline …` 1 つ（worktree・枝・run・`brief-common.md`）。子への指示は `references/child-brief.md` のひな形から作る。

## stock での前提（実測・確認の範囲）

| 事実 | 内容 | 確認 |
| --- | --- | --- |
| 無人の確認 | 答えのない確認は 5 分で拒否される（`promptTimeoutMs: 300000`）。承認にはならない | 設定と docs。審査ログ |
| 子の確認 | 背景の子の確認は、親の画面へ転送される（`forwarded_permission.*`）。約 11 秒で承認され、続行した | 実測（審査ログ） |
| 子の境界 | `cwd` を worktree にした子は、worktree 内の `write`・`git add`/`git commit`・`uv run --with`・`mise exec` が確認なしで通る。本体の `.tmp/` への `write` は `external_directory` の確認になり、親の画面へ転送された | 実測（2026-11-10。`feature/away-boundary-exp`） |
| スクリプトの実行 | `python3 ~/.agents/skills/…` は確認なし（`python3` を `read` と宣言、`~/.agents/skills/*` の読み取りを許可） | 判定表（`permission_cases.json`）と実機 |
| 「離席中」の区別 | 方針は区別できない。`git commit`・`uv add` などは確認なしで通る。止めるのは worktree の境界と、`brief-common.md` の指示、停止時の `audit` | `cc-safety-net explain`・判定表 |
| グローバルな環境変更 | `pip install`・`uv tool install`・`npm -g`・`mise use -g`・`brew install` などは**拒否**し、理由で uv・mise へ案内する（`feature/deny-global-installs`） | 判定表。フラグが後ろにある形（`npm install foo -g`）は拾えない |
| 破壊的な形 | `git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D`・`find -delete` は拒否される | `cc-safety-net explain` |

確認になる操作の一覧は、スキル内の `references/stock-pi.md`（方針の写し。迷ったら配備済みの設定を読む）。

## リハーサルの結果（2026-11-10）

目標「worktree で FizzBuzz の小さなライブラリを 3 サイクルで作る」を、親が監督し、サイクルごとに新しい子で実行した。

| 確認 | 結果 |
| --- | --- |
| 確認（ask）の件数 | **0 件**（審査ログ。リハーサル中は `permission_request` が無く、子ごとの `config.resolved` が 5 件で cwd は worktree） |
| 本体への影響 | なし。`HEAD`・`git status` は開始時のまま。worktree に 3 コミット、`.venv` は worktree の中 |
| 1 サイクルの所要時間 | 約 30〜45 秒（起動から完了通知まで） |
| 親の再開 | 完了通知で自動。`sleep` 不要 |
| 親の再検証 | 毎回一致（15 件一致・21 passed・33 passed） |
| 引き継ぎ | 子は `notes.md` を読み、前の結果（`uv run --with pytest`・`conftest.py` の知見）を使った |
| `subagent stop` | 子は数秒で `stopped`。**子の実行中のサブプロセスは残った**（孤児になる） |
| `checkpointBeforeDeadlineMs` | `timeoutMs` 90 秒・チェックポイント 45 秒で、44 秒に要求・57 秒に子へ到達（実行中のコマンドが終わる境）・70 秒で正常終了。ハードキルの前 |
| 子の `sleep` の端末 | 端末なし（`ps` の TT が `?`）。pi の画面は `pts/0` → `audit --kill` は端末つきを止めない |

## 判断（標準を先に使う: [ADR-0031](../adr/0031-evaluate-existing-extensions-first.md)）

- **子の起動・停止・期限は `pi-subagents` の標準機能**（`async`・`cwd`・`timeoutMs`・`checkpointBeforeDeadlineMs`・`stop`）。自作したのは、準備と事後監査と停止判定（`away_guard.py`）だけ。
- **`prepare` は `git worktree add -b`** を使う（`git flow feature start` に依存しない。どのリポジトリでも動く）。枝名は `feature/away-<run_id>`。
- **`audit --kill` は、cwd が worktree の中のプロセスだけを止める**。端末つき（利用者の操作）と、run より前に起動したプロセスは止めない。
  `/proc` を読むので Linux だけ。`stop` が子のサブプロセスを止めない実測が理由。
- **事前判定 `preflight.py` は stock では使わない。** 凍結した旧ハーネスの判定器を呼ぶ作りで、stock の実際のガードと食い違う。custom プロファイル用として残す。
- **認可チェーンのリンクは作らない。** 標準の機能（方針の `deny` に理由を付ける）で足りる。グローバルな環境変更は ask ではなく deny + 理由で止める。
- **`snapshot`（作業コピー）は使わない。** worktree が上位互換。コードは残す（custom プロファイルの手順書が参照しうる）。
- **再開は子の完了通知。** `bg_run` の `sleep`（手段 C）は、子を使わない待機の部品として残す。`/goal` の `goal_wait` は採らない（下）。

## 再開の仕組み

| 手段 | 内容 | 状態 |
| --- | --- | --- |
| 子の完了通知（既定） | 子を `async: true` で起動して応答を終える。完了で、アイドルの親が自動で再開する | 5 サイクルで実測 |
| C: `bg_run` で `away_guard.py sleep <秒> --note …` | 子を使わない待機。完了通知が `--note` の行を運ぶ | 3 秒・5 秒・120 秒を実測。時間単位は未確認 |
| B: `/goal` の `goal_wait({ resume_after_ms })` | 標準の拡張 `pi-goal`。時間指定で 1 回だけ起こす | **採らない**。利用者が `/goal` を打つ必要がある。「戻ったので止める」を `goal_complete`・`goal_blocked` で表せない。`--tokens 150k` が数ターンで尽きた |

## 未確認

- 数時間規模の運転（子の完了通知による再開の連鎖）。実際の無人（利用者が不在）での通し運転。
- 子 1 回あたりのトークン・費用と、親の文脈の伸び。
- Windows・macOS（`audit --kill` は Linux のみ。`prepare` と `check` は標準ライブラリだけ）。
- `check` は、worktree の run で `WORKTREE`・`CHILD_TIMEOUT_MS`・`CHILD_CHECKPOINT_MS`（子に渡す `timeoutMs` と `checkpointBeforeDeadlineMs`）を出す。残りの時間から計算した子の時間が 180 秒に満たないときは、停止理由 `child-time` で止める（子を起動しても、完了前に締め切りが来るため）。
- `audit` は、本体の `.tmp/` が `.gitignore` で無視されている前提（無視されていなければ、本体の `git status` が汚れて違反になる）。
