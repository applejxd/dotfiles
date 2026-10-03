# エージェントの git 入力待ちを防ぐ環境変数をどこで入れるか

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

## 記録 E1 — 2026-10-03

- **対象バージョン**: OpenCode v2.0.14、git 2.43.0
- **環境**: WSL2 Ubuntu、基準コミット 09abaed。`~/.gitconfig` は `core.editor = vim`、
  `credential.helper = store`（github.com は `gh auth git-credential`）。`EDITOR=VISUAL=nvim`
- 一次情報: <https://opencode.ai/v2/docs/build/plugins>（Hooks → Shell）

### 問い

エージェントの git が入力待ちで固まらないよう、`GIT_TERMINAL_PROMPT=0` /
`GIT_EDITOR=false`（GCM 環境なら `GCM_INTERACTIVE=never`）を**未設定のときだけ**入れたい。
(1) OpenCode V2 のプラグインからシェルツールの子プロセス環境を変えられるか、
(2) 隔離起動 `ocs` のどこに足せるか、(3) 2 変数は何を防ぐか。

### 結論（先に）

| 項目 | 結果 |
| --- | --- |
| プラグインからシェルの環境を変える | **できる**。`ctx.shell.hook("create.before", (e) => { e.env.X ??= "…" })`。実測で子シェルに届いた |
| 「未設定時のみ」 | `e.env` に呼び出し元の環境が入っているので `??=` で成立（`GIT_EDITOR=vim` を渡した実行で `vim` のまま） |
| ocs | `inner_env()`（`cli.py`）が境界内へ渡す環境の唯一の組み立て。ここへ `setdefault` で足せる。ただし **ocs 以外（素の opencode）には効かない** |
| `GIT_TERMINAL_PROMPT=0` | TTY があるとき資格情報の入力待ちを即失敗にする（実測）。TTY が無いときは元々失敗する |
| `GIT_EDITOR=false` | エディタが要る操作を即失敗にする（実測: `rebase -i`・`revert -e`）。TTY 無しの merge / revert 既定は元々エディタを開かない |

**推奨**: **OpenCode のプラグイン（`guide-plugin`）の `shell.create.before`** に 3 変数を
`??=` で入れる。素の起動でも ocs 経由でも同じ 1 か所で効き、`OCS_ISOLATED` のような
起動側の違いに依存しない。ocs の `inner_env` へも足すのは、プラグインがロードに失敗したとき
（fail-open）の保険としては有効だが、2 か所に同じ値を持つことになる（推測: 要否は判断事項）。

### 方法・条件

#### 静的調査

- 公式ドキュメントの Shell 節に `ShellCreateBefore { command, cwd, timeout, shell, env }` が
  あり、`env` は `Record<string, string | undefined>`、例に `event.env.COMPANY_ENV = "development"`。
- 既存記録 [plugin API の実測](../opencode/plugin/api-probe.md) は `shell.create.before` が
  `command / cwd / timeout / shell / env` を持つことまでを確認していた（**書き換えの効果は未確認**だった）。
- 現行の `guide-plugin/index.js` は `tool.hook("execute.before")`・`permission.hook("evaluate")`・
  `tool.hook("execute.after")` だけを使い、`ctx.shell.hook` は使っていない。

#### 実機（テスト用プラグインを `.tmp` の設定ディレクトリへ）

`.tmp/research-env/cfg/plugins/envprobe.js`（`OPENCODE_CONFIG_DIR/plugins/` は自動ロード。
[ロード経路](../opencode/plugin/loading.md)）に次を置いた。

```js
export default {
  id: "envprobe",
  async setup(ctx) {
    await ctx.shell.hook("create.before", (e) => {
      e.env.GIT_TERMINAL_PROMPT ??= "0"
      e.env.GIT_EDITOR ??= "false"
      e.env.PROBE_FROM_PLUGIN = "yes"
    })
  },
}
```

```console
$ env -u GIT_EDITOR -u GIT_TERMINAL_PROMPT OPENCODE_PROBE_CONFIG=$PWD/.tmp/research-env/cfg \
    mise run opencode:probe -- 'シェルツールで echo "GTP=[$GIT_TERMINAL_PROMPT] GE=[$GIT_EDITOR] P=[$PROBE_FROM_PLUGIN]" を実行'
GTP=[0] GE=[false] P=[yes]
$ GIT_EDITOR=vim OPENCODE_PROBE_CONFIG=... mise run opencode:probe -- '(同上)'
GTP=[0] GE=[vim] P=[yes]
```

- 子シェルは `/usr/bin/zsh`。フック引数の `e.env` は 119〜120 キーで、起動時の環境が丸ごと入っている
- 実環境の `guide-plugin` と同時にロードした場合は**未試験**（probe は `OPENCODE_CONFIG_DIR` を差し替える）
- 試験用の設定は `.tmp` に置き、記録後に削除した。V2 の `opencode run` は 1 回あたり
  Copilot のモデルを 1 回呼ぶ

#### ocs（静的）

`home/dot_local/share/ocs/cli.py`:

- `inner_env(sandbox)` が `os.environ` から `DROP_ENV` を除き、`OPENCODE_CONFIG_DIR` と
  `OCS_ISOLATED=1` を足した dict を返す
- `main()` が `check.host_env(env, FENCE_TMP)`（`PATH` と `TMPDIR` を上書き）を `execve` の
  環境にし、内側は `/usr/bin/env PATH=… TMPDIR=/tmp XDG_STATE_HOME=… opencode --standalone`
- よって `env.setdefault("GIT_TERMINAL_PROMPT", "0")` 等を `inner_env` の末尾へ足せば
  内側の opencode（とその子シェル）が継承する（**未実装・未実測**）

#### git の挙動（一時クローン `.tmp/research-env/c`）

エージェントの権限で `git add` / `git commit` / `git checkout` / `git config` は拒否された
（`Permission denied: shell`）ため、**`git commit`（`-m` 無し）と、分岐した履歴での
`merge --no-ff` は測れなかった**。代わりに本リポジトリの `git clone` した履歴の上で、
エディタを起動する別経路を測った。標準入力は `/dev/null`、TTY 無し。

```console
$ GIT_EDITOR=false git rebase -i HEAD~2
error: There was a problem with the editor 'false'.        # rc=1。.git/rebase-merge は残らない
$ git rebase -i HEAD~2        # core.editor=vim、stdin=/dev/null、出力はファイル
Vim: 警告: 端末からの入力ではありません ...               # rc=1。rebase 状態は残らない
$ sleep 12 | timeout 6 git rebase -i HEAD~2
(rc=124。6 秒でタイムアウト = 固まる)                       # .git/rebase-merge が残り、`git rebase --abort` で戻す
$ GIT_EDITOR=false git revert HEAD                          # -e 無し
[main 0d06ce0] Revert "…"                                    # rc=0。TTY 無しでは既定でエディタを開かない
$ GIT_EDITOR=false git revert -e HEAD
error: There was a problem with the editor 'false'.
Please supply the message using either -m or -F option.     # rc=1。コミットされない
$ GIT_EDITOR=false git merge --no-ff main                   # 現在のブランチが main のため "Already up to date."（測れず）
```

- エディタが必要で TTY・端末入力が無いとき、**vim は即終了する場合と、入力が開いたままだと固まる場合がある**
  （`rebase -i` で両方観測。差は標準入力が閉じているか）。`GIT_EDITOR=false` ならどちらでも即失敗
- 残る状態: エディタ失敗の `rebase -i` は rebase 途中状態を残さなかった。固まって打ち切った場合は
  `.git/rebase-merge` が残った
- **推測**: `git commit`（`-m` 無し）は `rebase -i`／`revert -e` と同じ経路で、
  `GIT_EDITOR=false` なら `Aborting commit due to empty commit message.` 相当で止まる。
  merge は git の仕様上、標準入出力が TTY のときだけエディタを開くので、TTY 無しのエージェントには影響しない
  （どちらも本記録では未実測）

#### 資格情報（ローカルの 401 サーバ。`python3 -m http.server` 相当を 127.0.0.1:18080 に起動）

`http://127.0.0.1:9/` は接続が確立せず 20 秒でタイムアウト（rc=124）になり、資格情報の
問い合わせに到達しなかったため、401 を返す一時サーバに替えた。

```console
$ git fetch dead </dev/null                               # TTY 無し
fatal: could not read Username for 'http://127.0.0.1:18080': そのようなデバイスやアドレスはありません   # rc=128
$ GIT_TERMINAL_PROMPT=0 git fetch dead </dev/null
fatal: could not read Username for '…': terminal prompts disabled                                          # rc=128
$ sleep 12 | timeout 10 script -qec "git fetch dead" /dev/null          # 疑似 TTY
Username for 'http://127.0.0.1:18080':                                                                      # rc=124。入力待ちで固まる
$ sleep 12 | GIT_TERMINAL_PROMPT=0 timeout 10 script -qec "git fetch dead" /dev/null
fatal: could not read Username for '…': terminal prompts disabled                                          # rc=128、即失敗
```

### 考察

- 非 TTY のシェルツールでは `GIT_TERMINAL_PROMPT=0` が無くても資格情報の問い合わせは失敗する。
  効くのは **TTY が付く経路**（ヘルパーが TTY を確保する、疑似端末で動かすツール）。保険として安価
- `GIT_EDITOR=false` が効く主な場面は `-m` 無しの `git commit`・`rebase -i`・`commit --amend` の
  エディタ起動。固まるかどうかは標準入力の状態に依存し、閉じていれば vim が即終了するが、
  開いていれば固まる（実測は `rebase -i`）
- `GCM_INTERACTIVE=never` は GCM が無い環境（このマシンは `git-credential-manager` 無し）では測れていない
- ocs 側にだけ入れる案は素の opencode に効かない。プラグインは fail-open（ロード失敗で消える）。
  どちらにも弱点があるため、**プラグインを主、ocs を保険**という分担が筋だが、二重管理のコストは
  判断事項

### 次の問い

- `guide-plugin` へ `shell.create.before` を足した状態で、`git commit`（`-m` 無し）と分岐した merge を
  エージェント権限の外（人が手元で）測る
- `ctx.shell.hook` が他のツール（`bash` ツールが別名の場合や Windows の `pwsh`）でも発火するか、
  並列実行時にも毎回呼ばれるか
- GCM を入れた環境での `GCM_INTERACTIVE=never` の効果

### 参照

- <https://opencode.ai/v2/docs/build/plugins>

> Modify shell commands, working directories, timeouts, executables, or environment variables before execution.

- 仕様: [plugin 層](../../spec/agent-config-generation.md#plugin-層-guide-plugin)、
  [OpenCode の隔離起動](../../spec/opencode-sandbox.md)
- 関連: [mise shims の解決](../shell/mise-shims-resolution.md)

[調査記録一覧へ戻る](../../index.md)
