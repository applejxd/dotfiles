# Claude Code / Copilot CLI で git 入力待ち防止の環境変数を「未設定時のみ」入れられるか

<!-- 現在の総合判断は docs/change/0011-agent-first-shell.md が正本。
     ここは「いつ何を観測したか」を積む場所 -->

OpenCode 版の実測は [エージェントの git 入力待ちを防ぐ環境変数](noninteractive-git-env.md)。
本記録はその続きで、**同じ 3 変数**（`GIT_TERMINAL_PROMPT=0` / `GIT_EDITOR=false` /
`GCM_INTERACTIVE=never`）を **Claude Code と Copilot CLI** でも、**AI のシェルにだけ・
未設定のときだけ**入れられるかを調べた。

## 記録 E1 — 2026-10-04

- **対象バージョン**: Claude Code 2.1.270（実機は OAuth 期限切れで**実測不可**。公式ドキュメントのみ）、
  GitHub Copilot CLI 1.0.87-0（実測あり）、git 2.43.0
- **環境**: WSL2 Ubuntu、基準コミット d52b393。`git config core.editor = vim`、`EDITOR=nvim`
  （つまり `git var GIT_EDITOR` は `GIT_EDITOR` が無ければ `vim`、`GIT_EDITOR=false` なら `false`）
- 一次情報:
  - Claude Code: <https://code.claude.com/docs/en/settings-reference>（`env`）、
    <https://code.claude.com/docs/en/env-vars>（Precedence）、
    <https://code.claude.com/docs/en/hooks>（Persist environment variables / PreToolUse decision control）、
    <https://code.claude.com/docs/en/interactive-mode>（Shell mode with `!` prefix）
  - Copilot CLI: <https://docs.github.com/en/copilot/reference/hooks-configuration>、
    `copilot help config`（ローカル CLI が持つ設定一覧）

### 問い

(1) Claude Code の `settings.json` の `env`、`SessionStart` hook の `CLAUDE_ENV_FILE`、
`PreToolUse` hook の `updatedInput` で、3 変数を「未設定のときだけ」AI のシェルへ入れられるか。
(2) Copilot CLI の設定・hook・起動ラッパーで同じことができるか。
(3) 人の対話シェルに漏れないか、`common.toml.tmpl` から生成できるか、Windows で使えるか。

### 結論（先に）

| CLI | 結果 |
| --- | --- |
| Claude Code | **`env` は不可**（公式: 設定の値がシェルの同名変数を**上書き**する）。**`CLAUDE_ENV_FILE`（SessionStart）に `export X="${X:-既定}"` を書く方式が公式に実在**し、本命。**実機未検証**。`updatedInput` でのコマンド書き換えも公式にあるが、権限規則がその書き換え後の入力で評価される |
| Copilot CLI | 設定ファイルに環境変数を入れる項目は無い。`sessionStart` hook は `additionalContext` しか返せない。`preToolUse` の `modifiedArgs` でコマンドを書き換えられる（**実測**）が、狭い allow 規則の下で**実行が拒否された**（**実測**）。**起動ラッパー（`VAR=${VAR-既定} copilot …`）は実測で成立**（未設定→既定、既設定→維持） |

**推奨**: **起動ラッパー**を共通の方式にする（Claude・Copilot の両方）。理由は「未設定時のみ」が
シェルの `${VAR-既定}` で素直に書け、人のシェルに漏れず、hook と権限規則に触らないから。
Claude は実機検証が出来るようになったら `CLAUDE_ENV_FILE` を**補助**として検討する
（ラッパーを経由しない起動、IDE 拡張・デスクトップからの起動を拾えるため）。

### 方法・条件

#### Claude Code（公式ドキュメントの読解。実機未検証）

| 手段 | 公式の記述（要旨） | 「未設定時のみ」 | 人のシェルへの影響 |
| --- | --- | --- | --- |
| `settings.json` の `env` | 「A value here overwrites the same variable exported in your shell」。空文字 `""` にすると「シェルの export を打ち消す」 | **満たさない**（常に上書き）。`${X:-…}` のような展開の記述は見つからず、できるとは言えない（未確認） | `env` は Claude のプロセス環境へ書かれ、全子プロセスに入る。`!` コマンドも同じプロセスの子なので入ると**推測**（記述なし） |
| SessionStart hook の `CLAUDE_ENV_FILE` | 「write `export` statements to `CLAUDE_ENV_FILE` … persist environment variables for subsequent Bash commands」。SessionStart / Setup / CwdChanged / FileChanged で使える | `export X="${X:-既定}"` と書けば**成立するはず**（シェルが source するとき評価される。**推測**、実機未検証） | 「subsequent Bash commands」とだけ書かれ、`!` コマンドへ効くかは**記述なし（未確認）** |
| PreToolUse hook の `updatedInput` | `hookSpecificOutput.updatedInput` が Bash の `command` を置き換える。「Claude Code evaluates permission rules … against the input your hook returns」 | コマンドの前に `X=${X:-既定}` を足せば成立（**推測**） | 人の `!` には PreToolUse が出ない（ツール呼び出しではない）と**推測**。ただし書き換え後の文字列で allow / ask / deny が評価されるため、前置きで既存の allow 規則に当たらなくなる恐れ（**推測**。leading の `VAR=value` は `if` 条件では剥がされると公式にあるが、permission 規則側の記述は未確認） |

- Claude の hook は同じ matcher の hook を**並列**に走らせる（公式）。このリポジトリでは
  `check_bash.py` が同じ `Bash` に付いており、`updatedInput` を返す hook を足すと、
  deny の判定が書き換え前後のどちらを見るかを別途確かめる必要がある（**未確認**）。

#### Copilot CLI（実測）

##### 設定・hook の静的調査

- `copilot help config` に環境変数を入れる設定キーは**無い**（近いのは `bashEnv`（`BASH_ENV` を bash に使うか）と
  `powershellFlags` だけ）。
- hook の `env` フィールドは「Environment variables to set」とあるが、**hook プロセス用**
  （シェルツールの環境ではない、と**推測**。実測していない）。
- `sessionStart` hook の出力は `additionalContext` だけが使われる（公式）。環境は返せない。
- `preToolUse` hook は `modifiedArgs`（ツール引数の差し替え）を返せる（公式）。入力の `toolArgs` は
  camelCase 形式ではJSON 文字列で来る（実測。下記）。

##### 実測 1: 起動ラッパー（`.tmp` の使い捨て git リポジトリ。モデルは `gpt-5-mini`、`copilot -p`）

`git var GIT_EDITOR` は `GIT_EDITOR` が環境にあればその値、なければ `core.editor`（`vim`）を返す。
`printenv` で他の 2 変数も見た。ラッパー相当は `sh -c` の中の `export X=${X:-既定}`。

```console
$ env -u GIT_EDITOR -u GIT_TERMINAL_PROMPT -u GCM_INTERACTIVE sh -c \
    'export GIT_TERMINAL_PROMPT=${GIT_TERMINAL_PROMPT:-0}; export GIT_EDITOR=${GIT_EDITOR:-false}; \
     export GCM_INTERACTIVE=${GCM_INTERACTIVE:-never}; exec copilot -p "… git var GIT_EDITOR …" --allow-tool="shell(git var)" …'
false                                       # 未設定 → 既定が Copilot のシェルへ届いた

$ env -u GIT_TERMINAL_PROMPT -u GCM_INTERACTIVE GIT_EDITOR=vim sh -c '(同上)'
1) git var GIT_EDITOR  → vim                # 既設定は維持
2) printenv GIT_TERMINAL_PROMPT GCM_INTERACTIVE → 0 / Never
```

- 1) の `Never` はモデルの転記で、実際の値は `never` のはず（**要確認だが影響なし**。値の大文字小文字はこの実測の目的外）。
- 最初の試行で `env | grep …` は、ユーザーの hook（`check_bash.py`）に止められた。環境の一括表示が
  拒否されるのは意図どおりの挙動で、`git var` / `printenv 名前` で測った。

##### 実測 2: `preToolUse` の `modifiedArgs`

`.tmp` の使い捨てリポジトリに `.github/hooks/probe.json`（`preToolUse`、`bash` 実行）を置き、
`bash` ツールのとき `command` の前に `export GIT_EDITOR="${GIT_EDITOR:-false}";` を付けて
`{"modifiedArgs": {…}}` を返させた。

```console
$ env -u GIT_EDITOR … copilot -p "… git var GIT_EDITOR" --allow-tool="shell(git var)" --allow-tool="shell(export)" …
Permission denied and could not request permission from user      # 狭い allow では拒否
$ env -u GIT_EDITOR … copilot -p "… git var GIT_EDITOR" --allow-all-tools …
false                                                              # 書き換えは効く（書き換え無しなら vim）
```

- Copilot の debug ログに hook の標準出力 `{"modifiedArgs": {"command": "export GIT_EDITOR=…; git var GIT_EDITOR", …}}` が残り、
  **書き換え自体は効く**（`--allow-all-tools` の実行で `false`）。
- 書き換え**前**のコマンドなら通る `--allow-tool="shell(git var)"` が、書き換え**後**は `shell(export)` も許可していたのに
  拒否された。権限判定は書き換え後のコマンドに対して行われ、`export …; git var` の形（`${…:-…}` の展開を含む複合コマンド）が
  既存の allow に当たらなくなる、と**推測**（原因の切り分けはしていない）。実運用の `permissions-config.json` でも
  同じことが起きれば、**全 bash が承認待ちになる**。
- プロジェクトのフックは `-p` でも、フォルダが信頼済み（または opt-in）のとき読み込まれる
  （ログ: `Loading repo hooks in prompt mode (folder is trusted or opt-in set)`）。

### 比較

| 観点 | Claude: `env` | Claude: `CLAUDE_ENV_FILE` | Claude: `updatedInput` | Copilot: `modifiedArgs` | 起動ラッパー（両方） |
| --- | --- | --- | --- | --- | --- |
| 未設定時のみ | **×**（上書き） | ○（`${X:-…}`。実機未検証） | ○（前置き。未検証） | ○（実測） | **○（実測。`${X-…}` / `${X:-…}`）** |
| 人のシェルへ漏れない | △（`!` に入る恐れ） | 不明（`!` への効き方の記述なし） | ○（推測） | ○ | ○（`VAR=… cmd` 形式ならそのプロセスだけ） |
| 権限規則との干渉 | なし | なし | **あり**（書き換え後で評価） | **あり（実測: 拒否）** | なし |
| 単一ソース（`common.toml.tmpl`）から生成 | 可（`[claude]` → `settings.json` の `env`）。ただし上書きなので不適 | 可（`[[hooks]]` に SessionStart を足し、スクリプトが TOML を読む。新規ファイルが要る） | 可（`[[hooks]]`） | 可（`[[hooks]]`。Claude と同じスクリプトを共有） | 可（`shellrc.sh.tmpl` で `includeTemplate … \| fromToml`。同種の例: `346_claude_mcp.ps1.tmpl`） |
| Windows（PowerShell） | 同じ | `CLAUDE_ENV_FILE` は bash の `export` 構文。PowerShell ツールでの扱いは**未確認** | ツール名が `Bash` / `PowerShell` で別の構文が要る | ツール名が `bash` / `powershell`。`$env:` 構文が別に要る | プロファイルに関数を置く（環境は**プロセス全体**なので `try/finally` で戻す。`VAR=… cmd` は使えない） |
| 取りこぼし | なし | なし（Claude 経由なら全部） | なし | なし | ラッパーを通らない起動（IDE 拡張、デスクトップ、Orca などが直接 `copilot` / `claude` を起動、`cron`）は拾えない |
| 保守コスト | 低い | 中（hook 1 本 + テスト） | 高い（権限評価との相互作用） | 高い（実測で拒否） | 低い（シェル関数 1 つ。ただし 2 OS 分） |

### 考察

- **Claude の `env` は目的に合わない**。公式が「シェルの export を上書きする」と明記しているため。
  呼び出し元が明示した値を尊重する（案件 0011 の必須基準）に反する。
- **コマンドの書き換え方式（`updatedInput` / `modifiedArgs`）は避ける**。実測で Copilot は権限判定が
  書き換え後のコマンドに対して行われ、狭い allow で拒否された。Claude も公式が同じ挙動を述べている。
  このリポジトリは allow / ask / deny のリストが中心なので、前置きの `export` が全 bash 呼び出しの
  判定を変えるリスクが大きい。
- **ラッパーは最も単純**。`alias agent='copilot'` / `'claude'` は `shellrc.sh.tmpl`（対話シェルのみ）にあり、
  同じ場所に `copilot()` / `claude()` の関数（`GIT_TERMINAL_PROMPT=${GIT_TERMINAL_PROMPT-0} … command copilot "$@"`）を
  置けば、alias が関数を呼ぶ。人の対話シェルの環境には**残らない**（コマンド前置きの代入）。
- **弱点**: ラッパーを通らない起動は効かない。OpenCode の `guide-plugin` が起動方法に依らず効くのに比べ、
  Claude / Copilot は「どの経路で起動されるか」に依存する。
- **Windows**: PowerShell の関数は `$env:X = …` でプロセス環境を変えるため、人のシェルへ残る。
  `try { … } finally { 元へ戻す }` が要る。今回は**実機未検証**（WSL のみ）。

### 推奨と実装の要点（案。実装は未着手）

1. 変数の一覧（名前と既定値）を `common.toml.tmpl` に 1 か所だけ置く（例: `[agent_shell_env]`）。
   OpenCode の `guide-plugin`（`rules.json` 経由）と ocs の `inner_env`、ラッパーが同じ表を読む。
2. `shellrc.sh.tmpl`（対話シェルのみ）で `claude()` / `copilot()` の関数を生成する。変数ごとに
   `${VAR-既定}`（空文字を明示した人を尊重するなら `-`、空も未設定扱いなら `:-`。**要判断**）。
3. PowerShell は `$PROFILE` 側（対話判定の後ろ）に同じ関数を生成し、`finally` で元の値へ戻す。
4. Claude は実機検証が可能になってから、`CLAUDE_ENV_FILE` を補助にするかを決める。
   確かめること: (a) `export X="${X:-…}"` が子シェルで効くか、(b) `!` コマンドへ効くか、
   (c) 既存の SessionStart hook（`checkpoint_restore.py` など）と共存できるか。
5. 検証: ラッパー経由の `git var GIT_EDITOR` 相当（本記録の実測 1 の形）を、人が手元で再確認する。

### 未確認

- Claude Code の `CLAUDE_ENV_FILE` の `${X:-…}` が期待どおりに効くか、`!` コマンドへ効くか（実機で未検証）
- Claude の `updatedInput` で書き換えた後、`check_bash.py` など並列 hook の判定が書き換え前後のどちらを見るか
- Copilot: 実運用の `permissions-config.json` 下で `modifiedArgs` が全 bash を承認待ちにするか（狭い allow での拒否までは実測）
- Copilot の hook の `env` フィールドが、シェルツールの環境に効くか（hook プロセス用と推測）
- `GCM_INTERACTIVE=never` の効果（GCM 無しの環境。前記録から引き継ぎ）
- Windows の PowerShell 関数の実機動作

### 試験の後始末

`.tmp/cp-probe`（使い捨ての git リポジトリ、probe 用 hook、スクリプト）は記録後に削除した。
Copilot の実行は `gpt-5-mini` で 5 回（`-p` のみ。実行させたのは読み取りの `git var` / `printenv` だけで、
うち 2 回は権限・hook に止められた）。

### 参照

- 前の記録: [エージェントの git 入力待ちを防ぐ環境変数](noninteractive-git-env.md)
- 案件: [CHG-0011](../../change/0011-agent-first-shell.md)
- 仕様: [hooks の単一ソース化](../../spec/agent-config-generation.md#hooks-の単一ソース化)

[調査記録一覧へ戻る](../../index.md)
