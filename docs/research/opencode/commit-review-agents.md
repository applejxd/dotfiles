# OpenCode V2 の commit / review エージェントの実機確認

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所 -->

> **現行の仕様**: [子エージェント](../../spec/agent-config-generation.md#子エージェント)

## 結論

- `commit` は `claude-opus-5.5#medium`、`review` は `gpt-6-astra` で起動する（Copilot）
- `commit` のエージェント規則 `{shell, "git commit *", deny}` は、`--auto` の下でも、
  手前に `{shell, "*", allow}` を置いても効く（後勝ち）
- **`opencode run --auto` は、子セッションの承認の確認を自動承認しない**（推測。下記）。
  既定で確認が要るシェル（`git status` など）を使う子エージェントは、答える人が
  いないまま止まる。TUI で確認が表に出るかは未確認

## 記録 E1 — 2026-09-28

- **対象バージョン**: opencode v2.0.14
- **環境**: WSL2 Ubuntu / 基準コミット `7978085` に `commit` / `review` の定義を加えた作業ツリー

### 問い

生成した `commit` / `review` は、割り当てたモデルで起動し、権限どおりに振る舞うか。

### 事前の予想

どちらも割り当てたモデルで起動する。`commit` は `git status` などを実行し、
ステージしてメッセージ案を返す。`git commit` は拒否される。

### 方法・条件

- [エージェントごとのモデル指定](agent-models.md)の記録 E1 と同じ試験環境
  （資格情報だけ引き継いだ試験用 DB と、生成した `opencode.json` を置いた試験用の
  設定ディレクトリ）。送信直前のリクエストは `http.request` hook で記録した
- `commit` は、変更を 2 ファイル持つ使い捨てのリポジトリ（`.tmp/opencode/scratch`）で試した
- 親への依頼は「`commit` に下ごしらえを頼み、ステージ後に `git commit -m probe` を
  1 回試させて結果を報告させる」

### 結果

**`review`**: `gpt-6-astra` で起動した（記録したリクエストの `model`）。`echo PROBE` の
実行を頼んだが、指示（コマンドを実行しない）を理由に自分で控えたため、権限の拒否は
踏んでいない。

**`commit`（生成したままの設定）**: `claude-opus-5.5`・variant `medium` で起動し、
commit スキルを読み込んだあと、シェルの呼び出し
（`git status --short --branch; ...; git diff HEAD; ...`）が `running` のまま
5 分以上進まなかった。ページャなどのプロセスは残っていなかった。

```console
$ ps -eo pid,ppid,etime,stat,cmd | grep -E "less|git (status|diff|log)|pager" | grep -v grep
（出力なし）
```

**`commit`（試験用の設定だけ `{shell, "*", allow}` を `git commit` の deny の手前に足した）**:
最後まで進んだ。`a.txt` だけをステージし、`b.md` は別の単位として残し、両方の
メッセージ案を返した。`git commit -m probe` は指示を理由に実行しなかった。

```console
$ git status --short
M  a.txt
 M b.md
```

**拒否そのもの**: 試験用の設定で `commit` を `mode = "all"` にして `system` を外し、
主エージェントとして直接実行させた。

```console
$ opencode run --standalone --auto --agent commit \
    'Run exactly this shell command once and report the tool result verbatim: git commit --allow-empty -m probe'
✗ git commit --allow-empty -m probe failed
Error: Permission denied: shell
$ git log --oneline
763bffb init
```

別件: 同じ依頼の最初の 2 回は、`build` の最初の呼び出しで `Error: Transport` になった。
簡単な依頼（`Reply with exactly: OK`）は同じディレクトリで通った。原因は未特定。

### 考察

- 止まった原因は承認の確認だと考える。シェルを許可しただけで先へ進んだため。
  ただし「`--auto` が子セッションに及ばない」ことを直接示す記録（承認要求の一覧など）は
  取っていないので**推測**
- `commit` から確認を無くすには `git status` / `git diff` を allow にするしかないが、
  どちらもリポジトリ側の設定（fsmonitor・外部 diff）で任意のコマンドを起動しうる
  （[allow リスト監査](permission/allow-list-audit.md)）。allow にはしない
- `git commit` の拒否は指示ではなく権限で担保できている

### 次の問い

- TUI で、子セッションの承認の確認が表に出て答えられるか。未確認
- `Error: Transport` の原因。未特定

### 参照

> Subagents run with fresh context in foreground or background child sessions. The parent agent's `subagent`
> permissions control which agents it may launch; the child uses its own configured permissions.

出典: <https://opencode.ai/v2/docs/agents/>
