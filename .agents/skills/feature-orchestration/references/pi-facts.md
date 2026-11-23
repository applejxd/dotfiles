# pi と権限の事実（運用の前提。確かめ済み）

権限の正本は [権限の方針](../../../../docs/spec/agent-config-generation.md#permission-system-の設定)。ここは、feature の運用に効く事実だけを集めた表。食い違ったら、正本と審査ログが優先。実測の日付・経緯は [worktree の運用の記録](../../../../docs/research/agents/worktree-lifecycle-2026-11.md)。

## 親の操作

| 操作 | 判定 |
| --- | --- |
| `git commit`（feature の worktree でも） | 確認なし |
| `git push*`・`sudo *` | 拒否 |
| `gh` の変更系・`chezmoi apply`・`git flow * finish*` | 確認（誰も答えないと 5 分で拒否される。YOLO を切る運用が前提） |
| `git config` | 書き込みは拒否。名乗りの鍵（`user.name`・`user.email`）だけ確認。読み取り（`--get`・`--list`）は確認なし |
| `git worktree remove` | `.tmp/worktrees/` の下で、`--force`・`-f`・`..` が無いときだけ確認なし。ほかは確認 |
| `git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D` | 拒否（cc-safety-net） |
| `git -C <絶対パス> merge`・`git flow feature update … --rebase` | 確認なし（`cd … && git merge …` の連結は確認が出る。`git rebase*` は ask） |
| `python3 ~/.agents/skills/…/*.py` | 確認なし（`uv run …`・`node …` は、作業ツリーの外のパスで確認になりうる） |

## 子（worker・reviewer・scout・oracle）

- 起動: `subagent({ agent, task, cwd, async: true, options: { timeoutMs, checkpointBeforeDeadlineMs } })`。agent は worker・scout・reviewer（読み取り専用・shell なし）・evidence-auditor・researcher・oracle・delegate など。モデルは設定で役割ごとに決めてある（`reviewer` は実装と別系統。依頼で指定しない）。
- 前景の子には権限の確認機構が載らないので、`forceTopLevelAsync: true` で背景に固定してある。同時数の上限は外してある（`maxActiveAsyncRunsPerSession: 0`）。入れ子・起動数の上限も取り払ってあり、並列度は CPU（全件検査）と親の確認の手間で決まる。
- **作業ツリーの外の読み書きは、確認なしで即座に拒否**される（`permission: external_directory: deny`。離席中に 5 分止まらない）。引き継ぎは、worktree の中のファイルで行う。
- 子の `stop` は、子のサブプロセスを止めない（[契約](worker-contract.md)で `timeout` を付けさせる）。

## 確認の記録

- 確認が出たかどうかの正は、子の自己申告でなく審査ログ: `~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`。子の確認は、親の画面へ転送される。

## 取り込み・反映

- `git flow feature finish` は、`develop` が `origin/develop` より遅れていると拒否する。`git merge --ff-only origin/develop` で追い付く。
- `chezmoi apply` は、スクリプトが sudo のパスワードを要ると、端末が無くて失敗する（対処は [SKILL.md](../SKILL.md) の落とし穴）。
- `chezmoi update` は `git pull --autostash --rebase` を固定で実行する。未 push の merge commit がある `develop` では、merge commit が平らに作り直される。
