# gitflow-lite の規約の強制（pi のガード）

gitflow-lite（main / develop / feature。feature は squash）で運用するリポジトリで、AI が **develop / main の作業ツリーを直接編集・コミットしない**ようにする、追加の制限層の仕様。
案件は [CHG-0049](../../change/0049-gitflow-convention-guard.md)。ブランチモデルは [CHG-0047](../../change/0047-gitflow.md)・[開発](../development.md#ブランチモデルgitflow-lite)。

既存の判定（[判定 API](pi-decide.md)）の**外側**に足す層で、`decide.ts`・`common.toml.tmpl`・正解データは変えない。判定を緩めず、deny か確認（`mustConfirm`）を足すだけ。
Python 版（Claude / OpenCode の hook）には複製しない（[ADR-0017](../../adr/0017-pi-only-and-ts-judge.md)）。

## 保証の範囲

- **保証する**: `edit` / `write` の直接の呼び出しと、`guarded_action` の `git_commit`。
- **保証しない**（「うっかり防止」の範囲外。実装は未着手のものを含む）:
  - `bash` の中の書き込み、外部スクリプトの内部、`bg_run`
  - `git worktree add` / `git switch -c` などの、素の git による直接のブランチ・worktree の作成（**未実装**。CHG-0049 の段 1c で deny にする予定）
  - セッション開始時の案内の注入（段 2a。**未実装**）
  - 許可（[逃がし口](#逃がし口gitflow-allow)）の間の `bash` 経由の書き込み（元から止まらない）

## 対象と判定

保護の対象は、**編集対象のパスを所有する worktree** の HEAD が `refs/heads/develop` か `refs/heads/main` のとき、または本体（primary）の detached。
linked worktree の detached（隔離 worker）は対象にしない。cwd ではなく**パスの所有者**で判定するので、本体から feature の worktree を編集する正規の運用は止まらない。

| 呼び出し | 状況 | 結果 |
| --- | --- | --- |
| `edit` / `write` | 保護の対象の worktree の中（`.tmp/` を除く） | deny（feature の起票を案内） |
| 同上 | その worktree の `.tmp/` の下（実体解決した上で） | 通す |
| 同上 | `.git/` の中（lite のリポジトリ） | deny |
| 同上 | git を読めない（`unknown`） | `mustConfirm`（bypass でも承認が要る） |
| 同上 | リポジトリ外、feature の worktree、lite 以外のモデル | 通す（既存の判定のまま） |
| `git_commit` | 保護の対象の worktree の cwd（`dir` を指すときは、その `dir` のリポジトリ） | deny |
| 同上 | git を読めない（`unknown`・HEAD・`.gitflow`） | deny（許可に倒さない） |

- **docs の恒久例外は作らない**。`finish` が本体の追跡ファイルの変更を拒否するので、編集できても統合できなくなる
- 結果の合成は `tighten`（`judge/call.ts`）。既存の判定が deny なら deny のまま、allow / ask に deny か確認を足す。`restrict` オプションで、規約の強制だけを取り直せる

## モデルの識別

`.gitflow` の存在だけでなく、**develop にコミットされた `.gitflow` の内容**で、gitflow-lite か（`gitflow.ts` の `identifyModel`）を決める。
作業コピーの `.gitflow` の削除・改変では、ガードが外れない。結果は `gitflow-lite` / `other` / `none` / `unknown`。`other` と `none` は対象にしない。

**初版は、ブランチ名が `main` / `develop` / `feature` のものだけを対象にする。** develop を別名にするなどのカスタムは `other` か `none` になり、強制の対象外（ガードが黙って効かない）。
実行側の固定操作（`gitflow_feature_*`）も同じ名前を前提にしているので、検出だけを汎用化しない。

## git の状態の収集（`gitstate.ts`）

パスの所有 worktree・HEAD・リポジトリのモデルを、**判定ごとに作り直す**（キャッシュしない）。

- `git status` / `check-ignore` は使わない（`core.fsmonitor` を起動しうる）
- 継承された `GIT_*` を落とし、hook と fsmonitor を無効にして実行する。**3 秒・64 KiB** に制限する
- 読めなければ `unknown` で、許可に倒さない

## 判定を使い回すときの取り直し

pi の `tool_call` の判定は、git の状態の変化を検出しない。そこで、`execute()` が判定を使い回すときも、**規約の強制だけ**を直前に取り直す（`gateNow`）。
承認した状態と違えば（承認の後でブランチが変わったなど）、承認を使わない（`Decision.gateKey` で照合）。
`git_commit` は、スナップショット・プレビューの前（`deps.judge`）と、**実行の直前**にも拒否を確認する（`actions.ts`）。

## 逃がし口（`/gitflow-allow`）

develop / main で作業したい利用者のための、時間を限った許可（段 2b）。実装は `harness/index.ts`（状態 `allowance`・コマンド・`endAllow`・`gateNow`）、`harness/gitflow-allow.ts`（引数の解釈と表示）、`judge/gitflow_gate.ts`（`Allowance` / `permits` / `gate(…, allow?)`）。

- **書式**: `/gitflow-allow [edit|commit|all] [分] | off | status`。範囲は `edit`（edit / write）・`commit`（`git_commit`）・`all`（既定）
- **時間**: 既定 10 分、上限 60 分。上限を超える指定は丸めず拒否する
- **利用者専用**: 入力欄のスラッシュコマンドだけ。モデルが呼べるツールは作らない。環境変数だけで解除する手段も作らない。`/bypass` の意味は変えない
- **確認画面**: 付与は確認を出せるときだけ。対象の worktree・ブランチ・範囲・期限を見せ、承認されたときだけ付与する（UI が無ければ付与しない）
- **結び付き**: 許可は、その worktree の、その HEAD（ブランチ）に結び付く。**メモリだけ**に持ち、セッションには復元しない
- **失効**: ブランチが変わる・期限が来る・`off`。判定は期限を毎回自分で確かめる（タイマーは表示と片付けだけ）。付与・失効のたびに判定の使い回し（`decided`）を捨てる（`epoch++`）
- **許可でも緩めないもの**: `.git/` の中への書き込み、git を読めないとき（`unknown`）の確認・拒否、外部への送信の確認（別の仕組み）。許可が外すのは、**保護の対象の worktree への直接の `edit` / `write` と `git_commit` の deny だけ**
- **監査**: `pi.appendEntry("gitflow-allow", …)`（付与・取消・失効）と `notify`。ステータスに `⚡ gitflow 許可 <branch> <HH:MM> まで`
- **子エージェント**: 別プロセスなので引き継がない
- **保証外**: 許可の間も、`bash` の中の書き込み・`bg_run` は元から止まらない。直接のブランチ・worktree の作成（段 1c）、セッション開始時の注入（段 2a）も対象外

## 試験

| 試験 | 対象 |
| --- | --- |
| `test/agents/test_pi_gitflow_guard.py` | 純関数 `gate` / `isGated` |
| `test/agents/test_pi_gitstate.py` | 実 git での状態の収集 |
| `test/agents/test_pi_gitflow_allow.py` | 逃がし口の純関数（引数の解釈・`permits`・`gate` の許可） |
| `test/agents/test_pi_gitflow_guard_harness.py` | pi との統合（`/gitflow-allow` を含む） |
| `test/agents/test_pi_gitflow.py` | `identifyModel` |

実機（実モデル・TUI・Windows）での確認は**未検証**。
