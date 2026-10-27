# スキルの frontmatter の方針

スキルの `SKILL.md` の先頭（frontmatter）に、どのフィールドを書くか、`allowed-tools` と `context: fork` をどう扱うかの、今の方針。
CLI ごとの解釈の違い、`allowed-tools` の書き方、fork の基準、スキルごとの宣言と、委譲の型の割り当てを置く。
調べた経緯と実測は [記録 F1・F2・F3](../research/agents/skill-fork-enforcement.md)、親をオーケストレーターに寄せる設計は [CHG-0045](../change/0045-orchestrator-parent.md)。

## CLI ごとの解釈

スキルは `~/.claude/skills` に置き、Claude Code・pi・OpenCode・Copilot CLI が共通で読む（`home/dot_claude/skills/`。pi と OpenCode は同じ置き場を読む）。

| フィールド | Claude Code | pi | OpenCode |
| --- | --- | --- | --- |
| `name`・`description` | 使う | 使う | 使う |
| `disable-model-invocation` | 使う（モデルの自動発動と一覧の説明を止める） | 使う（一覧から外す） | 読まない |
| `allowed-tools` | 使う（**確認なしで使える**にする許可。制限ではない） | 読み捨てる | 読み捨てる |
| `context: fork`・`agent`・`background` | 使う（本文を子の依頼文にする） | 読み捨てる（ハーネスが解釈する案は CHG-0045） | 読み捨てる（実測。[E1](../research/opencode/skill-frontmatter.md)） |
| `license`・`compatibility`・`metadata` | 受け取るだけ | 受け取るだけ | 読まない |

未知のフィールドは、どの CLI でもエラーなしで無視される。Copilot CLI の解釈は未確認。

## `allowed-tools` の方針

- **許可を足す宣言**で、制限ではない。権限の単一ソースは `common.toml.tmpl` で、スキルは、それに**足してよい**範囲を狭く書く。
  deny > ask > allow の順と hook は、スキルの許可があっても変わらない（ask と deny は、そのまま効く）
- **一括の `Bash` を書かない**。許可するのは、そのスキル自身のスクリプトを、実際に呼ぶ形（`Bash(python3 ~/.claude/skills/<名前>/scripts/* )`）で
- **利用者の合意を取る操作は、許可に含めない**（例: 有料 API を呼びうる `marimo export html`、GitHub への書き込み）。確認が残る
- ファイルのツールは、本文が実際に使うものだけ。一部のファイルだけなら `Edit(AGENTS.md)` の形（新規作成も、この形の編集の許可で足りる）
- 本文のコマンドが `$SKILL_DIR` などの変数を使うと、許可の型に一致しない（照合は、書かれた文字列に対して行われる）。許可したいときは、`~/.claude/skills/<名前>/...` の形で書く
- `Task` は 2.1.63 で `Agent` に改名され、古い名前は別名として動く。古い版との互換のため、`Task` のまま
- 付けないもの: `github-operations`（書き込みは確認が本質）・`oss-research`・`web-search`・`learn`（Bash なし）・各移行スキル。検索のスクリプトなど、足したくなったら、パターンの一致試験と合わせて足す
- 副作用の確認: 本文が書くスクリプトの呼び出しが、許可の型に一致するかは機械的に試験できる（2026-10-28 に実施）。**Claude Code の実機での確認は未実施**（認証が切れている）。許可から外れた操作は、確認が 1 回増えるだけで、動作は変わらない

## `context: fork` の基準

Claude Code の `context: fork` は、**本文（`$ARGUMENTS` 置換後）を、会話を見ない子の依頼文として渡す**。子は質問できず、子を作れず、背景の子は使えるツールが狭く、確認も出せない。
次の**全部**を満たすスキルだけに付ける。

1. 引数だけで始められる（起動前の会話を材料にしない）
2. 利用者への質問・承認・合意が要らない
3. サブエージェントや他のスキルを呼ばない
4. 子が確認なしでできる操作だけ（確認が要る操作・課金・外部への書き込みが無い）
5. 結果が要約で足りる（途中経過を利用者が見たいわけではない）

付ける場合の `agent` は、Claude の役割名（`Explore`・`Plan`・`general-purpose`。省略は `general-purpose`）。編集と実行がある作業は、前景で待つ（`background: false`）。背景の子は使えるツールが狭く、編集が会話の巻き戻しの外になるため。

## スキルごとの宣言（2026-10-28）

| スキル | `context: fork` | 理由 | `allowed-tools` |
| --- | --- | --- | --- |
| `fix` | あり（`general-purpose`・`background: false`） | 5 条件を満たす | 使う linter だけ |
| `away-shift`・`commit`・`learn`・`onboarding`・`review-loop`・`skill-creator`・`github-operations`・`ipynb-to-marimo-pages` | なし（本文が付けないと明記） | 質問・承認・会話履歴・子の使用のどれかが本質 | 下の表 |
| `arxiv-paper-ja`・`powerpoint-studio`・`imozuru`・`friction-review`・`pi-extension-dev`・`sdd-docs` | なし | 子を使う・質問や承認が要る・会話の文脈が材料 | 下の表 |
| `cuda-version-migration`・`uv-migration` | なし | 長時間で、判断が人の側。調査の段だけを `plan` 役へ任せる（[CHG-0044](../change/0044-plan-agent.md)） | なし |
| `oss-research` | なし | 読み取り中心で自己完結だが、`gh`・`curl` の実行と `rm` の承認が、子では通らない | なし |
| `web-search`・`env-check` | なし | 道具。結果を親がそのまま使う | `env-check` はスクリプトだけ |

`allowed-tools` を持つスキル:

| スキル | 内容 |
| --- | --- |
| `away-shift` | 自分のスクリプト（`python3`・`uv run --no-project python`）と `timeout`。`Task` は外した（本文に呼ぶ手順が無い） |
| `env-check` | `env_check.py` だけ |
| `sdd-docs` | 自分のスクリプト（Windows の `py -3` を含む）・`git mv`・`git check-ignore` |
| `skill-creator` | `uv run pre-commit run --files` だけ |
| `ipynb-to-marimo-pages` | 自分のスクリプト・`uv run marimo check`・`convert`・`ruff`・`pre-commit`（`export html` は含めない） |
| `fix` | `ruff`・`pre-commit`・`mise run`・`eslint`・`prettier`・`gofmt`・`go vet`・`golangci-lint`・`cargo fmt`・`cargo clippy`・`clang-format`・`git ls-files`（`Write` は外した） |
| `commit` | 読み取りの git・`git add`・`git restore --staged`・`git commit`（`git commit` は ask が優先） |
| `onboarding` | `Read`・`Grep`・`Glob`・`Edit(AGENTS.md)` |
| `learn` | `Read`・`Edit`・`Write`・`Grep`・`Glob`（Bash なし） |
| `review-loop`・`powerpoint-studio` | 変更なし。テストの実行（対象リポジトリ依存）や `$SKILL_DIR` の変数を使うコマンドが、パターンに落とせないため。`powerpoint-studio` の Web 系の許可は、本文が求める箇所を特定できていない（見直しの候補） |

## 委譲の型（親をオーケストレーターに寄せる設計。案）

親は、利用者との対話・判断・委譲・承認・ToDo の管理に専念し、実作業は子へ任せる、という方向（利用者の方針、2026-10-28）。
スキルは、**対話の段**と**実行の段**を分け、実行の段を、自己完結の依頼文で子に渡す。型の割り当ては案で、[CHG-0045](../change/0045-orchestrator-parent.md) で詰める。

| 型 | 親の仕事 | 子の仕事 | スキル |
| --- | --- | --- | --- |
| A 丸ごと委譲 | 依頼文を渡して結果を受ける | 全部 | `fix`・`env-check`・`web-search`・`friction-review` の分類の段 |
| B 合意だけ親 | 費用・範囲などの合意を取る | 実行（合意は引数で受ける） | `ipynb-to-marimo-pages`・`uv-migration`・`cuda-version-migration` の実行の段 |
| C 文脈を渡して書かせる | 会話の決定事項を要約して依頼文に入れる | 文書・差分を作る | `sdd-docs`・`learn`・`commit` |
| D 対話そのもの | 質問・承認 | 重い読み物だけ | `onboarding`・`skill-creator`・`pi-extension-dev`・`github-operations` |
| E 自分が指揮役 | 子の管理 | 翻訳・レビューなど | `arxiv-paper-ja`・`review-loop`・`away-shift`・`powerpoint-studio` |
