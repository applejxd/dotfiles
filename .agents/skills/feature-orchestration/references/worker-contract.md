# worker への契約の雛形（stock の pi）

stock の pi では、依頼は 2 段にする。**契約**をファイル（`.tmp/keep/plan/<名前>.md`。feature の worktree の中）に書き、`subagent` の `task` には契約の**パスと 1〜2 行の指示**だけを渡す（大きな文章・JSON を `task` に直接入れない）。
契約は、worktree を作ってから書く（同時に書くと worktree の作成が失敗する）。

## 起動の形

```js
subagent({
  agent: "worker",
  cwd: "<worktree の絶対パス>",
  async: true,
  options: { timeoutMs: 1800000, checkpointBeforeDeadlineMs: 300000 },
  task: "契約 .tmp/keep/plan/<名前>.md（cwd からの相対パス）を読み、その指示どおりに実装する。"
})
```

- `timeoutMs`・`checkpointBeforeDeadlineMs` の値は目安（担当の大きさで変える）。期限の前に、途中経過を報告させる。
- 前景の子には権限の確認機構が載らないので、`async: true`（背景）で起動する。完了は通知で届き、アイドルの親が自動で再開する。
- 同時数の上限は設定で外してある（並列度は CPU の都合で決める）。worktree への書き手は 1 つだけ。

## 契約に入れるもの

1. **担当 worktree（`cwd`）と、編集してよい範囲**: 担当ファイル（これだけ編集）と、読み取りだけのファイル（worktree の中にあるもの）。**本体と他の worktree は、子には読めない**（作業ツリーの外は確認なしで拒否される）。必要な内容は、親が worktree の中（`.tmp/keep/plan/` など）へ写して渡す。
2. **背景と事実**: 先に読むファイル、確かめ済みの事実（出典つき）、ほかの feature への依存（前提として）。**確かめていないことは「見込み」「未確認」と書かせる**。
3. **作ること**: 優先順位つき。
4. **変えてはいけないもの**: 担当外のファイル、frontmatter の `description` など。共有されやすいファイル（docs の索引・`scripts/verify.py`・`pi-mcp-servers.toml`）は、書かせないか、書く 1 人を指名する。
5. **検査**: 実行するコマンドと、出力を報告に貼る指示。重い検査（`mise run verify:all`）は回させない（親が 1 本だけ回す）。長く動くコマンドには `timeout` を付けさせる。
6. **コミット**: コミット前の監査が必要なら「コミットしない」と書く。監査の対象外で worker にコミットさせる場合だけ、契約で明示する。`git push*` は拒否される。
   `git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D` は cc-safety-net が拒否するので、使わせない。
7. **報告の形**: 結論を先頭 3 行以内。続けて、変更ファイル・各検査の出力（抜粋）・判断に迷った点・確かめられなかったこと・次への申し送り。
8. **止まる条件**: 契約にない決定が要る、合格条件を検査できない、確認や権限の拒否に当たった、のいずれかなら止まる。途中の差分・実行した検査と結果・未完了の作業を親に返す。別経路を使ったり、明示されていない再委譲をしたりしない。
9. **残すもの**: 再利用するスクリプトは担当ファイルとしてコミットの対象にする。残したい資料は worktree の `.tmp/keep/` に置かせる（親が消す前に本体へ写す。[工程 9](../SKILL.md)）。それ以外の `.tmp/<話題>/` は使い捨て。

## 時間と終了

- 子の `stop` は、子が起動したサブプロセスを止めない。長く動くコマンドには、契約で `timeout` を付けさせる。
- **確認が出ない書き方を契約に書く**（子は無人で、確認は 5 分待って拒否され、その間コマンドが止まる）: `env VAR=1 cmd` は `VAR=1 cmd`、`bash -c '…'`・`eval` は中を直接書く、`nohup` は拒否される（長い処理は前景で `timeout -k 10 <秒> <cmd>`）。`xargs`・`find -exec` は、読み取りだけのコマンドなら確認なし。詳細は away-shift の `references/child-brief.md`。
- 子の自己申告（「通った」「確認なしで動いた」）は当てにしない。親が同じコマンドを再実行して確かめる。確認が出たかどうかは、審査ログ
  （`~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`）が正。
