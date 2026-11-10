# worker への契約の雛形（stock の pi）

stock の pi では、依頼は 2 段にする。**契約**をファイル（`.tmp/keep/plan/<名前>.md`。feature の worktree の中）に書き、`subagent` の `task` には契約の**パスと 1〜2 行の指示**だけを渡す（大きな文章・JSON を `task` に直接入れない）。
契約は、worktree を作ってから書く（同時に書くと worktree の作成が失敗する）。凍結した custom の共通の約束は [worker-common.md](worker-common.md)（`guarded_*` 前提）。

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
- 同時に動かせる子は 4 つまで。worktree への書き手は 1 つだけ。

## 契約に入れるもの

1. **担当 worktree（`cwd`）と、編集してよい範囲**: 担当ファイル（これだけ編集）と、読み取りだけのファイル。他の worktree と本体は読み取りだけ。
2. **背景と事実**: 先に読むファイル、確かめ済みの事実（出典つき）。**確かめていないことは「見込み」「未確認」と書かせる**。
3. **作ること**: 優先順位つき。
4. **変えてはいけないもの**: 担当外のファイル、frontmatter の `description` など。共有されやすいファイル（`common.toml.tmpl`・golden・docs の索引・`scripts/verify.py`）は、書かせないか、書く 1 人を指名する。
5. **検査**: 実行するコマンドと、出力を報告に貼る指示。重い検査（`mise run verify:all`）は回させない（親が 1 本だけ回す）。長く動くコマンドには `timeout` を付けさせる。
6. **コミット**: 親が確かめてからコミットするなら「コミットしない」。worker にさせるなら、そう書く（bash の `git commit` は確認なしで通る。`git push*` は拒否される）。
   `git reset --hard`・`git checkout -- <path>`・`git restore`・`git clean -f`・`git branch -D` は cc-safety-net が拒否するので、使わせない。
7. **報告の形**: 結論を先頭 3 行以内。続けて、変更ファイル・各検査の出力（抜粋）・判断に迷った点・確かめられなかったこと・次への申し送り。
8. **止まる条件**: 契約にない決定が要るとき、確認が出る操作に当たったとき（push・`chezmoi apply`・`git worktree remove`・`git config`・`gh` の変更系）は、進めずに報告して止まる。

## 時間と終了

- 子の `stop` は、子が起動したサブプロセスを止めない。長く動くコマンドには、契約で `timeout` を付けさせる。
- 子の自己申告（「通った」「確認なしで動いた」）は当てにしない。親が同じコマンドを再実行して確かめる。確認が出たかどうかは、審査ログ
  （`~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl`）が正。
