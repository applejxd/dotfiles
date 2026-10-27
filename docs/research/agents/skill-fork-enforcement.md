# スキルの `context: fork` を、pi のハーネスで仕組みとして強制できるかの実験

<!-- 現在の運用の正本は docs/change/0026-specialist-agents-with-skills.md（案件）。ここは実験の記録（実機の pi 1.4.0、偽のモデル）。 -->

## 記録 F1 — 2026-10-27

- **問い**: Claude Code のスキルの `context: fork` / `agent:` のような宣言を、pi のハーネスで、指示（本文に「委任せよ」と書く）ではなく、
  **モデルが従わなくても効く仕組み**として実現できるか。親にスキルの本文を渡さず、子だけが読む形にできるか
- **方法**: 使い捨ての拡張（`input`・`tool_call` を使う）と、`context: fork` を宣言した試験用のスキルを用意し、偽のモデルで実機の pi を動かした。
  経路ごとに、拡張あり・なしと、親・子を比べた。pi 本体のソース（`dist/core/agent-session.js`・`skills.js`）で、順序と型も確認した
- **限界**: 子の起動そのもの（`guarded_task` と同じ起動）は、この実験では行っていない（結果の文の代わりを返した）。
  実際のモデル・実機のフルガードの子の起動は未確認。Windows・Claude Code は未確認

## 結論

1. **作れる。経路ごとに、強制の強さが違う**。
   - `/skill:名前`（利用者が打つ）: **強い強制ができる**。`input` イベントは展開の**前**に来て、`handled` を返すと、モデルも展開も走らない。
   - モデルが自分でスキルを選んで読む: `tool_call` で、スキルのディレクトリ配下への読み取りを**ブロック**できる（本文はモデルに届かない）。ただし、**ブロックの理由の文でモデルを誘導するだけ**で、委任するかはモデルしだい。
   - 他の読み方（シェル）: **完全には塞げない**。フルガードの判定器は `cat`・`head` を拒否するが、`grep -n . ファイル` は許可され、`ask` になるコマンドは、bypass や利用者の承認で通る。
2. **pi 本体は `context` / `agent` を解釈しない**。スキルの型（`Skill`）は `name`・`description`・`filePath`・`baseDir`・`disableModelInvocation` だけで、他の宣言は捨てられる。
   ハーネスが `SKILL.md` の先頭の宣言を自分で読む必要がある。パスは `pi.getCommands()` の `skill:名前` の `sourceInfo.path` から取れる。
3. 強制の目的は、**親の文脈を守ること（ワークフロー）**で、**悪意への防御ではない**（読み取りの境界は、別の仕組み）。この前提なら、1 と 2 で足りる。

## 実験の結果

| # | 条件 | 結果 |
| --- | --- | --- |
| T1 | 普通のスキルを `/skill:` で呼ぶ（対照） | 本文が展開されて、モデルに届く。`input` には、展開前の `/skill:...` の文字列が来る（入力元は `interactive`・RPC では `rpc`） |
| T2 | fork のスキルを `/skill:` で呼ぶ（拡張あり） | `handled` で、**モデルは呼ばれない**。本文は展開されない |
| T2b | 同じ（拡張なし） | 本文がそのまま展開される（pi 本体は fork を解釈しない） |
| RPC | T2 に加えて、`pi.sendMessage(..., {triggerTurn: true})` で結果の文を返す | **親のターンが 1 つ起きて**、結果の文を読む。本文はいちども親の文脈に入らない（`-p` の 1 回限りの実行は、ターンの前に終わるので不可。常駐する RPC・対話で使う） |
| T3・T4 | モデルが `read` で、fork の `SKILL.md`・`references/` を読む | `tool_call` で**ブロック**。ブロックの理由が、エラーの結果としてモデルに返る |
| T5 | 普通のスキルの `read`（対照） | 通る |
| T6 | 子（`PI_HARNESS_CHILD=1`）が fork スキルを `read` | 通る（本文を読める）。子は除外する |
| T7 | 親が `bash` で `cat`（実験の拡張だけ） | **すり抜ける** |
| T8 | 親が `ls` でスキルのディレクトリを見る | ブロック（読み取り系のツールを広く見る必要がある） |
| T9 | `skills/a/../b/SKILL.md` の形 | ブロック（`path.resolve` で正規化すれば足りる。`realpath`（シンボリックリンク）は未確認） |
| B | 導入済みのフルガードの `guarded_bash` で、13 のコマンド | `cat`・`head` は拒否。**`grep -n .` は許可されて本文が出る**。`wc` も許可（本文は出ない）。`awk`・`sort`・`od`・`base64`・`python3`・`git show`・`diff`・`cp`・`ls` は、「どの規則にも当たらない」で確認（`ask`）になる。確認なしで通るかは、bypass と利用者の承認しだい |

追加の確認:

- **実在する `fix` スキル**（`context: fork`・`agent: general-purpose`）が、そのまま見つかった。Claude の役割名（`general-purpose`・`Explore`・`Plan` など）を、pi の役割（`worker`・`explore` など）へ**対応づける表**が、ハーネスに要る。
- 導入済みの設定では、素の `pi` も `-ne` なしだとフルガードの拡張を読む。実験では `-ne` を付けた。

## 強制の強さの段（設計の材料）

| 段 | 仕組み | 強さ | 代償・限界 |
| --- | --- | --- | --- |
| 0 | 本文に「委任せよ」と書く | 指示だけ | モデルが無視しうる |
| 1 | `/skill:名前` を `input` で捕まえ、ハーネスが子を起動して結果を返す | モデルを介さない（強い） | 利用者が `/skill:` で呼ぶ場合に限る |
| 2 | モデルの読み取りを `tool_call` でブロックし、理由で「`guarded_task` へ」と誘導 | 親は本文を読めない。委任は誘導 | モデルが委任せず、本文なしで作業を始めうる |
| 3 | 2 に加え、ブロックの代わりにハーネスが子を起動し、結果を読み取りの結果として返す（`tool_result`） | 委任そのものを強制できる | 子へ渡す依頼文を、ハーネスが利用者の発言から決める必要がある（誤りやすい）。未実験 |
| 4 | 3 に加え、`guarded_bash` の命令に、スキルのディレクトリ名が含まれるものも止める | 偶然の抜け道を減らす | 迂回（グロブ・変数）は残る。悪意への防御ではない |

## 未確認・次の候補

1. 実際の子の起動（`guarded_task` の `spawnChild`）を `input`・`tool_call` の中から呼べるか（`ctx.executeTool` は、ツールの `execute` の中だけ。ハーネスの内部の関数を直接呼ぶ形になる）。
2. 子が `fork` のスキルの本文と `references/` を実際に読み、親へ要約を返せるか（実モデル）。
3. 段 3 の依頼文の決め方（利用者の直近の発言をそのまま使うか、モデルに要約させるか）。
4. Windows の素の pi（`guarded_task` が無い）では、fork を解釈せず、親で動かす。Claude Code は、自前で `context: fork` を解釈する（共有スキルは、宣言だけで両方に効く）。
5. 段 1 の経路を、`/skill:` 以外の入口（例: モデルによる `skill` の発動）にも広げるときの設計。

## 実験コード

`.tmp/exp_fork/`（`fork_ext.ts`・`run.py`・`run_rpc.py`・`run_bash.py`）。非コミットの使い捨て。要点は、次の 2 つのフックだけ。

- `pi.on("input", ...)`: 入力が `/skill:名前` で、その `SKILL.md` の宣言が `context: fork` なら、子を起動して `{ action: "handled" }` を返す。
- `pi.on("tool_call", ...)`: 読み取り系のツールの `path` を `path.resolve` で正規化し、fork のスキルのディレクトリ配下なら `{ block: true, reason }` を返す。子（`PI_HARNESS_CHILD=1`）は除く。

## 記録 F2 — 2026-10-27（Claude Code のスキルの frontmatter の公式仕様）

- **問い**: Claude Code は、どんな frontmatter をサポートし、`context: fork` をどう動かすか。pi のハーネスで同じ宣言を作るときの手本になるか
- **方法**: 公式のドキュメントを取得（<https://code.claude.com/docs/en/skills>・<https://code.claude.com/docs/en/sub-agents>、2026-10-27 に取得）。手元のスキルの frontmatter を数えた。原文は `.tmp/keep/claude-skills/`（非コミット）
- **限界**: ドキュメントの記述だけで、Claude Code の実機は動かしていない。版による差（`background` は v2.1.218 以降など）がある

### スキルの frontmatter（すべて任意。表に無い名前は、エラーなしで無視される）

| 分類 | フィールド | 内容 |
| --- | --- | --- |
| 標準（Agent Skills の仕様） | `name`・`description`・`license`・`compatibility`・`metadata`・`allowed-tools` | `license`・`compatibility`・`metadata` は受け取るだけで、動作しない |
| 発動の制御 | `disable-model-invocation`・`user-invocable`・`paths`・`when_to_use` | 前者はモデルの自動発動を止める（説明も一覧から外れる）。後者は利用者の `/名前` を止める。`paths` は一致するファイルを扱うときだけ自動で読む。`when_to_use` は `description` に足される（合計 1536 文字で切り詰め） |
| 引数 | `argument-hint`・`arguments` | `$ARGUMENTS`・`$名前`・`$1` の置換 |
| 実行の制御 | `allowed-tools`・`disallowed-tools`・`model`・`effort`・`shell` | `allowed-tools` は「確認なしで使える」だけで、制限ではない。そのターンの間だけ。`model`・`effort` はそのターンの間だけ上書き |
| 子での実行 | **`context: fork`・`agent`・`background`** | 下の節 |
| フック | `hooks` | スキルの発動で登録される |

手元の 17 スキルの使い方（`name`・`description` は全部）: `allowed-tools` が 11、`context: fork`＋`agent: general-purpose` が `fix` の 1、`compatibility` が `arxiv-paper-ja` の 1。
`disable-model-invocation`・`paths`・`model`・`effort`・`argument-hint`・`when_to_use` は使っていない。

### `context: fork` の動き（これが、pi の実験（F1）の手本になる）

- 新しい子エージェントを起動し、**スキルの本文（`$ARGUMENTS` を置換したもの）を、子の依頼文（タスク）として渡す**。子は会話の履歴を見ない。つまり、**スキルの本文が自己完結した依頼になっている必要がある**（方針だけのスキルは、子が何もせず返る）
- `agent` は、組み込み（`Explore`・`Plan`・`general-purpose`）か、`.claude/agents/` の自作の子。省略は `general-purpose`。子の system・ツール・権限・モデルは、その役割の定義（`model` を足すと上書き）
- **既定はバックグラウンド**で、結果は完了時に会話へ届く（`background: false` で、そのターンで待つ。`-p`・Agent SDK では待つ）。バックグラウンドの子は、ツールが狭い
- 逆向き（役割にスキルを持たせる）は、役割の定義（`.claude/agents/*.md`）の **`skills`**: スキルの全文を、子の起動時に注入する。`disable-model-invocation` のスキルは注入されない。子は、列挙していないスキルも `Skill` ツールで呼べる（制限ではない）
- 役割の定義の frontmatter: `name`・`description`・`tools`・`disallowedTools`・`model`・`permissionMode`・`maxTurns`・`skills`・`mcpServers`・`hooks`・`memory`・`background`・`omitClaudeMd`・`effort`・`isolation`（`worktree`）・`color`・`autoCompactWindow`

### 一覧の費用（今までの議論に関わる）

- スキルの一覧は、**文字数の予算**を持ち、超えると**説明を落とす**（名前は必ず載る）。上げるのは `skillListingBudgetFraction`・`SLASH_COMMAND_TOOL_CHAR_BUDGET`、下げるのは `skillOverrides` の `name-only`。1 スキルの説明は 1536 文字で切る。`/skill-doctor` が、費用と利用の頻度を出す
- 自動圧縮のあと、発動済みのスキルは、各 5000 トークン・合計 25000 トークンまで再添付される

### pi の設計への含意

1. **依頼文の決め方（F1 の未確認 3）は、Claude の流儀を手本にできる**: 子の依頼文は、スキルの本文（引数を置換）そのもの。ハーネスが利用者の発言から作らなくてよい。ただし、対話が必要なスキル・方針だけのスキルは、`fork` に向かない（既に、そうしたスキルは「fork しない」と明記している）
2. **「スキル→役割」の割り当ては、Claude にもある**（`skills` で全文を注入）。ただし、一覧からの除外ではなく**注入**で、強制ではない。pi の割り当て表（CHG-0026 段 2）も、同じ性格（案内）が自然
3. 既定がバックグラウンドで、結果が後から届く点は、pi の `guarded_task` の `background`・完了通知と同じ形で実現できる
4. 手元の `fix` の `agent: general-purpose` は、pi の `worker` に対応づけるのが自然（確認は未）

## 記録 F3 — 2026-10-28（スキルごとの fork と allowed-tools の調査）

- **問い**: 全 20 スキルのうち、`context: fork`・`agent` を付けてよいものはどれか。`allowed-tools` は、何を許可しているのが適切か。親をオーケストレーターに寄せる方針（[CHG-0045](../../change/0045-orchestrator-parent.md)）で、何を委譲できるか
- **方法**: 子（`explore`）4 本が、各 5 スキルの本文と `references/`・`scripts/` を読み、8 項目（ツール・対話と承認・子の使用・会話履歴への依存・副作用・規模・本文の宣言・最小の許可）を、根拠の行つきで答えた。
  親が、中央の権限（Claude 向けの allow 46・ask 22・deny 192、既定の権限モードは `auto`）と、公式の仕様（F2）、過去の記録（[E1](../../research/opencode/skill-frontmatter.md)）と突き合わせた
- **限界**: 子は `references/` を多くは読んでおらず、行番号の一部は概算。許可のパターンは、本文の呼び出しの形との**一致を機械的に試験した**だけで、Claude Code の実機（認証が切れている）では確かめていない。所要時間は、本文に数値があるもの以外は不明

### 結果

| スキル | 対話・承認 | 子の使用 | 会話履歴 | 副作用 | `fork` |
| --- | --- | --- | --- | --- | --- |
| `fix` | 無し | 無し | 不要 | linter による編集 | 向く |
| `env-check` | 無し | 無し | 不要 | 無し（読み取り） | 意味が無い（道具） |
| `web-search` | 無し | 無し | 不要 | ネットワーク・キャッシュ | 意味が無い（道具） |
| `oss-research` | 環境が分からなければ質問・`rm` の承認 | 無し | 不要 | `.tmp/oss` への取得と削除・ネットワーク | 微妙（承認が子で通らない） |
| `away-shift` | 無し（宣言のみ） | 本文に手順なし | 不要 | `.tmp/away-shift` | 不可（本文が明言） |
| `ipynb-to-marimo-pages` | 作業前の確認・有料 API の合意 | 独立レビュー | 一部 | 生成・上書き・課金の恐れ | 不可（本文が明言） |
| `arxiv-paper-ja` | 許諾の確認が要るとき | 翻訳と校閲に使う | 不要 | 取得・書き込み | 不可（子の中で子を作れない） |
| `powerpoint-studio` | 費用の提示（有効時） | 別のレビュー役 | 不要 | 生成物・`npm ci` | 不可（子を使う） |
| `review-loop` | リスク受容の承認 | 必須 | 不要 | `.tmp`・編集 | 不可（本文が明言） |
| `sdd-docs` | 依頼が無ければ尋ねる | 任意 | **強い** | `docs/`・`git mv` | 不可（会話が材料） |
| `skill-creator` | 反復で確認 | 任意 | 強い | スキルの作成 | 不可（本文が明言） |
| `github-operations` | 実行前の承認 | 無し | Project の番号を保持 | GitHub への書き込み | 不可（本文が明言） |
| `learn` | 反映は明示依頼のとき | 無し | **強い** | 編集（明示依頼時） | 不可（本文が明言） |
| `onboarding` | 質問・承認 | 無し | 不要 | AGENTS.md の編集 | 不可（本文が明言） |
| `commit` | コミット前の承認 | 想定あり | 一部 | `git add`・`commit` | 不可（本文が明言） |
| `cuda-version-migration` | 無し | 無し | 不要 | ビルド・編集 | 不向き（長時間・判断が人の側） |
| `uv-migration` | 判断は本文に委ねる | 無し | 不要 | 編集・削除・数 GB の取得 | 不向き |
| `imozuru` | 質問 4 か所 | 検索役を使う | 一部 | `.tmp/research` | 不可 |
| `friction-review` | `ask`（採用の確認） | 分類に使う | 不要 | `.tmp/friction` | 不可 |
| `pi-extension-dev` | 承認待ちが核 | 無し | 強い | 編集・試験 | 不可 |

### 読み取れること

1. **`fork` をそのまま付けてよいのは `fix` だけ**。5 条件（[基準](../../spec/skill-frontmatter.md#context-fork-の基準)）を満たすのが、これだけだった
2. **多くのスキルは、対話の段と実行の段が混ざっている**。全体は子へ渡せないが、実行の段だけなら渡せるもの（移行の実行・文書の更新・`commit`）がある。これが「委譲の型」の根拠
3. **`allowed-tools` は、11 スキルのうち 8 つが `Bash` を一括で許可していた**。本文が実際に呼ぶのは、自前のスクリプトと、決まった linter・`uv run marimo` などだった。そこで、スクリプト単位・コマンド単位に絞った（`ipynb-to-marimo-pages` の `marimo export html` は、課金の恐れがあるので許可に含めない）
4. **`Task` を許可していた `away-shift` は、本文に呼ぶ手順が無かった**（`references/` は未読）。外した
5. **`fix` の `fork` は、背景が既定**（Claude Code 2.1.218 以降）。背景の子は使えるツールが狭く、編集が会話の巻き戻しの外になるので、前景で待つ（`background: false`）にした
6. **OpenCode と pi は、`context`・`agent`・`allowed-tools` を読み捨てる**（E1 と F1）。`fork` と `allowed-tools` が実際に効くのは、いまのところ Claude Code だけ（契約が切れた 2026-09-25 から、実機では未確認）

### 未確認

- `fix` の `fork` が、Claude Code で実際に前景で動き、linter の確認が出るか
- 絞った許可で、各スキルの典型の流れが、確認の増加なしで通るか（Claude Code の実機）
- `powerpoint-studio` の `references/` と、`WebFetch`・`WebSearch` の許可が要る箇所
- `review-loop` の許可（対象リポジトリのテストコマンドに依存）を、パターンに落とせるか
