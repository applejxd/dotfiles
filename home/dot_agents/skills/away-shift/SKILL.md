---
name: away-shift
description: "ユーザ離席中（日中の外出・夜間など）に、専用の git worktree（枝つき）で子エージェントに検証・実験を反復させ、戻ってきたときに枝とレポートを渡す。利用者は離席と戻りの時刻を言うだけで、準備（worktree・期限・子への指示）は全自動。worktree の中ではコミットとローカルな依存の変更を自由にさせ、外への書き込み・グローバルな環境変更・push は止める。「離席するので試しておいて」「出かけている間に検証しておいて」「戻るまでに調べておいて」「留守中に実験を回して」と言われたときに使う。親が監督し（期限・再検証・記録・停止）、サイクルごとに新しい子を起動する。子を起動する手段（subagent）が無い環境では開始しない。ユーザが在席していて即座に応答できる作業や、本体の作業ツリーを直接変える作業には使わない。"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(uv run --no-project python ~/.agents/skills/away-shift/scripts/*), Bash(python3 ~/.agents/skills/away-shift/scripts/*), Bash(timeout *)
---

# away-shift

ユーザが席を外している間に、**専用の worktree の中で**、目標に向けた検証・実験を反復する。
戻ってきたときに、**枝（コミット）とレポート**を渡す。統合するかどうかは利用者が決める。

利用者がすることは、**離席と戻りの時刻を言うだけ**。あとは次の手順で全自動に進める。

## 仕組み（親・子・worktree）

| 役 | どこで | 何をする |
| --- | --- | --- |
| **親**（この会話） | 本体の作業ツリー | 準備・サイクルの起動・**再検証**・記録・期限の管理・停止・レポート。実験はしない |
| **子**（`subagent`） | 専用 worktree（`cwd` に指定） | 1 サイクルぶんの実験。**サイクルごとに新しい子**（文脈は引き継がず、ファイルで引き継ぐ） |
| **専用 worktree**（枝 `feature/away-<run_id>`） | `.tmp/worktrees/away-<run_id>/` | 子の作業場。中では**コミットとローカルな依存の変更が自由**。外への書き込みは確認（無人では拒否） |

- 親は子の完了通知で自動に再開する（待つ・`sleep` は不要）。
- 引き継ぎは worktree 内の `.tmp/away/`（共通の指示 `brief-common.md`・サイクルの指示 `cycle-<N>-task.md`・
  子の記録 `cycle-<N>.md`・申し送り `notes.md`）。子から見て本体の `.tmp/` は外側で、確認になるので使えない。
- **子の自己申告を信じない**。親が worktree で同じ確認コマンドを自分で実行して確かめる。
- 仕組みと根拠・実測は、このリポジトリの `docs/spec/away-shift.md`。再開・停止・期限の実測は `references/resume.md`。

> **この skill は fork しない（`context: fork` を付けない）**。親は離席時間をまたいで動き続け、利用者の復帰（メッセージ）を観測する必要がある。

## 前提（pi の stock）

- **確認（ask）に誰も答えない。** 確認の画面は 5 分で拒否される。1 回の ask で 5 分失うので、確認になる操作を計画に入れない
  （一覧: `references/stock-pi.md`）。子の確認は親の画面へ転送されるが、離席中は誰も答えず、同じく拒否される。
- **グローバルな環境変更**（`pip install`・`uv tool install`・`npm -g`・`mise use -g`・`brew install` など）は**拒否**される。理由が出る（uv・mise へ案内）。
  worktree の中のローカルな変更（`uv add`・`uv sync`・`uv run --with`・ローカルの `npm install`）は通る。
- **`subagent stop` は、子の実行中のサブプロセスを止めない**（実測）。子のコマンドには `timeout` を付けさせ、停止時は `audit --kill` で掃除する
  （端末つきのプロセスと、run より前に起動したプロセスは止めない）。
- **本体の `.tmp/` が `.gitignore` で無視されている**ことが前提（無視されていないと、`audit` が本体の `git status` の汚れを違反と見る）。
- スクリプトは `python3 ~/.agents/skills/away-shift/scripts/<名>.py …` で呼ぶ（確認が出ない）。
- 使う道具: `subagent`（起動・`stop`）・`bash`・`read`・`write`・`todo`。

## 使わない場面

| 状況 | 理由 |
| --- | --- |
| ユーザが在席していて即答できる | 対話した方が速い |
| 本体の作業ツリーを直接変える作業 | この skill は専用 worktree の枝にだけ書く |
| 外部サービスへの書き込み（issue・PR の作成など） | 取り消しにコストがかかる。子には許さない |
| `subagent` が使えない・リポジトリの根にいない | 開始せず、理由を利用者へ報告する |

## 手順

### 0. 聞くこと（2 つだけ）

足りないものだけ聞く。それ以外は聞かない。

1. **戻る時刻**（`17:00`・`8h`・`90m` など。読めなければ長さで）
2. **目標**（1 行）。検証できる形でなければ、**自分で言い換えて**始め、レポートに言い換えた旨を書く

### 1. 準備（全自動）

リポジトリの根（本体の作業ツリー）で実行する。

```bash
python3 ~/.agents/skills/away-shift/scripts/away_guard.py prepare --goal "<目標>" --deadline "<戻る時刻>"
```

worktree と枝を作り、run を作り、子への共通の指示を `<worktree>/.tmp/away/brief-common.md` へ書く。
出力の `run_id` と `worktree` を以降使う。`todo` に run_id・枝・worktree を残す。

利用者へ 3 行で伝える: 枝名・worktree・期限（「戻ったら枝を見てください」）。

| 離席の形 | `--deadline` の例 |
| --- | --- |
| 夜に離席して翌朝戻る | `07:30` |
| 日中に出かけて夕方戻る | `17:00` |
| 戻る時刻が読めない | `6h`（長さで指定） |

### 2. サイクルを回す（親）

**各サイクルの最初に必ず `check` を実行する。**

```bash
python3 ~/.agents/skills/away-shift/scripts/away_guard.py check <run_id>
```

- 終了コード 3 → 手順 3（停止）へ。
- 終了コード 0 → 継続。出力の `WORKTREE`・`CHILD_TIMEOUT_MS`・`CHILD_CHECKPOINT_MS` を、子の起動に使う。

1 サイクルは次の順に行う。

1. **仮説を 1 つ立て**、`write` で `<worktree>/.tmp/away/cycle-<N>-task.md` に書く。前のサイクルの結果を踏まえる。

   ```markdown
   # サイクル <N> の仮説

   - **仮説**: <何を確かめるか>
   - **確かめ方**: <コマンドや手順。`.tmp/away/notes.md` に前のサイクルの申し送りがある>
   - **成功の判定**: <どうなれば成立か。落ちたときに何を調べるか>
   - **時間の上限**: <分>（実験コマンドには `timeout` を付ける）
   - N = <N>
   ```

   1 サイクル = 1 仮説。長い処理は、投入と結果の確認を別のサイクルに分ける（`references/experiment-design.md`）。

2. **子を起動する**。`timeoutMs` と `checkpointBeforeDeadlineMs` は `check` の出力をそのまま入れる。

   ```text
   subagent({ agent: "worker", cwd: "<worktree>", async: true,
              options: { timeoutMs: <CHILD_TIMEOUT_MS>, checkpointBeforeDeadlineMs: <CHILD_CHECKPOINT_MS> },
              task: "サイクル <N> を担当する。.tmp/away/brief-common.md と .tmp/away/cycle-<N>-task.md（cwd からの相対パス）を読み、その指示どおりに実行して、コミットまで行う。" })
   ```

   制約は `brief-common.md` に書いてある（依頼文に書き写さなくてよい）。同時に動かす子は **1 つだけ**（worktree への書き手は 1 つ）。
   起動したら**応答を終える**。待たない。

3. **子の完了通知で再開したら、親が再検証する**。

   - worktree の中で、成功の判定に使うコマンドを**自分で実行する**（`cd <worktree> && timeout 5m <コマンド>`）。
     `git -C <worktree> log --oneline -3` と `git -C <worktree> status --short` も見る。
   - 子の `.tmp/away/cycle-<N>.md` と `notes.md` を読む。
   - 記録する。本文を `write` で `<repo>/.tmp/away-shift/<run_id>/work/note.md` に書き、
     `python3 ~/.agents/skills/away-shift/scripts/away_guard.py log <run_id> --note-file note.md` で渡す。
     **子の主張と再検証が食い違ったら、その事実を書く**（再検証が正）。

   ```text
   ### 仮説
   ### やったこと（子のコミットと、親の再検証の結果）
   ### 結果（成立 / 不成立。子の自己申告と一致したか）
   ### 次にやること
   ```

4. 子が失敗・タイムアウト・停止したときは、状態を記録し、同じ仮説を 1 回だけ作り直して再試行するか、次の仮説へ進む。
   子の確認が拒否されたもの（誰も答えなかった）は記録し、代替か次の仮説へ。**同じ操作を繰り返さない**。

### 3. 停止したら

`check` が終了コード 3 を返したら、**新しいサイクルを始めない**。

1. 実行中の子があれば `subagent({ action: "stop", id })`。
2. **監査と掃除**:

   ```bash
   python3 ~/.agents/skills/away-shift/scripts/away_guard.py audit <run_id> --kill --write
   ```

   本体の `HEAD` と `git status` が開始時のままか、枝のコミット一覧・差分、worktree に残ったプロセス（`--kill` で止める）を出す。
   終了コード 4（本体が変わっていた）は**違反**として、レポートの先頭に書く。

3. `report.md`（`.tmp/away-shift/<run_id>/report.md`）を書き、会話にも同じ内容を出す。

```markdown
# away-shift レポート (<run_id>)

## 目標
<宣言した目標と成功の判定。言い換えたなら、その旨>

## 結論
<できた / 一部できた / できなかった>。<1〜3 行で要点>

## 枝とコミット
- 枝: feature/away-<run_id>（worktree: <path>）
- <コミットの一覧と、差分の規模（audit の出力）>

## 分かったこと
- <根拠になるコマンド出力・ファイルとともに。親が再検証した結果を書く>

## 分からなかったこと・詰まった点
- <障害。確認が出て拒否された操作（誰も答えなかった）はここ>

## 次にやるべきこと（利用者の判断）
- 枝を統合するか、捨てるか（`git branch -D` は利用者の操作。worktree は `.tmp/worktrees/` の下なら `git worktree remove` で消せる）。承認が要る操作

## 監査
- 本体 HEAD: <開始時> → <停止時>（同じ / 違う）、本体 `git status`: <件数>
- 残っていたプロセス: <止めたもの>

## 停止理由
<期限 / STOP ファイル / 最大サイクル / 目標達成 / 行き詰まり>（<N> サイクル実行）
```

### 4. ユーザが戻ってきたら

メッセージが来た時点で、**その場でサイクルを打ち切る**。実行中の子を `subagent stop` し、手順 3 の `audit --kill --write` を実行し、
中断したサイクルの状態を 1 行で伝えて、レポートを提示する。

## 停止条件

| 条件 | 検出 |
| --- | --- |
| 期限 | `check` が `--deadline` を過ぎたと判定 |
| 予備時間 | 残りが 15 分未満、または子に割り当てられる時間が 3 分未満 |
| STOP ファイル | `.tmp/away-shift/<run_id>/STOP` または リポジトリ直下の `STOP` |
| 最大サイクル | 既定 20（`prepare --max-cycles` で変更） |
| 目標達成 | 成功の判定を満たした（親が再検証した） |
| 行き詰まり | 3 サイクル連続で新しい情報が出ない |
| 承認が必要 | 目標に到達するには、不可逆・外部・環境変更のいずれかが要ると分かった |

利用者は `touch STOP` だけで止められる。

## 制約

- **親は本体の作業ツリーを変えない**。書くのは `.tmp/away-shift/<run_id>/` と worktree 内の引き継ぎファイルだけ。停止時に `audit` で確かめる。
- **子の書き込みは worktree の中だけ**。コミットは枝へ自由。push・他の枝への統合・枝の削除・履歴の破壊・`git worktree` の操作・外部サービスへの書き込みは、子にさせない（指示は `brief-common.md`、方針の多くは拒否・確認になる）。
- **確認になる操作を計画しない**。拒否された操作は、同じ形で繰り返さない。
- **証跡を消さない**（`cycles/`・`state.json`・`report.md`・`audit.md`）。
- **秘密情報をログ・コミットに出さない**。
- **`check` をサイクルの先頭で必ず実行する**。子へは `timeoutMs` を付ける。
- **行き詰まりを隠さない**。「できなかった」も成果として書く。

詳細は `references/stock-pi.md`（確認になる操作の一覧）、`references/child-brief.md`（子への共通の指示のひな形）、
`references/resume.md`（再開・停止・期限の実測）、`references/unattended.md`（無人実行で避けること）、
`references/experiment-design.md`（1 サイクルの組み立て方）を参照する。
