# CHG-0050: pi のフルガードの `guarded_action` を、承認つきの commit と gh 投稿に縮める

- **状態**: In progress
- **更新日**: 2026-10-31
- **基準**: コミット 7422f88 以降、pi 1.4.0（作業ブランチ `feature/slim-guarded-action`。撤去は未コミットの差分として実装済み）

## 目的と非目的

**目的**: 運用の規約（develop / main を直接編集しない、feature を AI が起票する）をコードで強制していた層を撤去し、`guarded_action` を**承認つきの `git_commit` と `gh` の投稿**に縮める。判断と理由は [ADR-0021](../adr/0021-conventions-as-instructions-slim-guarded-action.md)。動機は 4 つ。

1. **副作用**: git の状態を読めないとき（入れ子リポジトリ・仮想 monorepo など）に、bypass でも外れない確認が出る
2. **設計の食い違い**: 規約（運用）を、境界（deny）と同じ強さで強制していた
3. **実装量**: 約 3,900 行（コード・試験）
4. **実行コスト**: コミットごとに、git を多重に起動していた

整理の見取り図（3 層）:

| 層 | 内容 | 強さ |
| --- | --- | --- |
| 境界（deny） | 秘密の読み取りなど、常時禁止 | bypass でも外れない |
| 必須確認 | 外への送信・公開・push・ssh・戻せない操作 | bypass でも外れない確認 |
| 誘導 | 止めずに案内する（fail-open） | 外れてよい |

運用規約は、どの層にも入れず、**指示（`AGENTS.md`・`commit` スキル）**にする。

**非目的**: 誘導の再分類（別案件として起こす予定。「残る課題」）。ブランチモデル gitflow-lite 自体（`.gitflow`・git-flow-next・`scripts/gitflow-setup.sh`）の廃止。承認の時間切れの退避（[CHG-0046](0046-guarded-action-timeout.md)）と子の隔離（`worktree.ts`）の変更。

## 受入条件

実装前に決めた期待動作。

- **A1**: `guarded_action` の操作は `git_commit`（`message`・任意の `dir`）、`gh_issue_comment`、`gh_issue_edit_body`、`gh_issue_edit_title` だけ。`gitflow_feature_*` は無い
- **A2**: `git_commit` は、どの作業ツリーから呼んでも、常に確認する（feature の worktree の無確認の省略は無い）
- **A3**: develop / main への `edit` / `write` / `git_commit` を、機械では拒否しない。git の状態を読めないことを理由にした deny・確認は出ない
- **A4**: bash の `git flow` / `git-flow` は、他の git と同じ扱い（`shell_deny` で専用に止めない）
- **A5**: 承認の時間切れの退避（`pending-store`・`/pending`）と、子の隔離（`worktree.ts`）は変わらない
- **A6**: 生成物（`rules.json` など）・判定の正解データ（golden）・試験・テンプレートの検査が整合する
- **A7**: 撤去した機能を指す docs が、経緯として書かれているもの以外に残らない

## 実施計画

撤去の単位。状態は、作業ツリーの差分に実装済みで、コミット前。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| 1 | 規約を強制する層を外す | gitflow-lite の規約ガード（`harness/gitstate.ts`・`judge/gitflow_gate.ts`・`gitflow-allow.ts`）、`edit` / `write` と `git_commit` への gate、`/gitflow-allow` を撤去 | 完了（コード。実機は未検証） |
| 2 | `guarded_action` を縮める | `gitflow_feature_start` / `commit` / `finish` / `discard` の 4 操作と、`gitflow.ts`・`gitflow-ops.ts`・`AUTO_CONFIRM`、feature の worktree 内の `git_commit` の無確認（WIP の省略）を撤去 | 完了（コード。実機は未検証） |
| 3 | bash の特別扱いを外す | `git flow` / `git-flow` の `shell_deny` を撤去 | 完了 |
| 4 | 試験と生成物を揃える | 対応する試験・ドライバー（`test_pi_gitflow*.py`・`test_pi_gitstate.py` など）を撤去。`common.toml.tmpl`・golden・`export_decide_golden.py`・`generate.py`・`verify.py`・`commit` スキル・`.chezmoiremove` を整合させる | 完了 |
| 5 | docs を揃える | 本案件・ADR-0021・仕様（`pi-extensions.md` ほか）・索引・CHG-0046 / 0047 / 0049 の更新。`pi-gitflow-guard.md` を削除 | 完了（このコミットの前） |
| 6 | 誘導の再分類 | 3 層に沿って、誘導の規則を見直す | 未起票（別案件） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 現在地

- 段 1〜5 は、作業ツリーに実装済み（未コミット）。試験・golden・テンプレートの検査は通っている（下の「実装・検証」）。実機（実モデル・TUI・Windows）は未検証
- 残るのは、段 6 と、「残る課題」の 3 件（実装の整理）
- 撤去後の運用: 利用者が自分のシェルで `git flow feature start` / `finish` を実行し、AI は feature の worktree で起動した `pi` から `git_commit`（確認あり）する。develop / main への直接の編集・コミットは、機械では止めず、`AGENTS.md` と `commit` スキルの指示だけで運用する

## 未解決点

- **指示だけで運用が守られるか**: [CHG-0049](closed/0049-gitflow-convention-guard.md) の背景は「指示だけでは守られなかった」だった。撤去後に develop のまま実装が始まる頻度を、運用で見る。再開条件: 頻発し、利用者の手戻りが副作用より大きいと分かったとき。そのときは、**誘導**（fail-open。止めずに案内する）として、git を読めないときは何もしない形で足すことを先に検討する（deny・確認にはしない）
- 実機（TUI・サンドボックス・Windows）で、`git_commit` が feature の worktree から期待どおり動くか

## 次の調査・実験

- 実機で、feature の worktree から起動した `pi` の `git_commit` を通す（確認が 1 回だけ出る）
- 撤去後の数週間、develop / main への直接コミットの頻度を、履歴で数える

## 評価基準

- 必須: 「受入条件」の A1〜A7 を満たす。守る境界（deny・必須確認・退避）が弱まらない
- 望ましい: コミットごとの git の起動が減る。`git_commit` の確認が、git の状態を読めない場所でも出ない

## 候補比較

| 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- |
| 全廃（`guarded_action` ごと撤去） | 実装量が最小。承認つきの操作は bash の ask でもできる | コミット・投稿の「内容を見せて 1 回で承認」と、時間切れの退避を失う。`gh` の投稿を bash へ戻すと、本文の引用の事故が増える | — | 見送り | — |
| **縮める（採用）** | 境界・必須確認・退避を残し、規約の強制と gitflow の自動化だけを外せる。約 3,900 行を撤去できる | 規約が指示だけになり、守られない場合がある | 撤去後の直接コミットの頻度 | 採用 | 「未解決点」 |
| 現状維持 | 規約が機械で止まる | 副作用（git を読めないときの確認）・設計の食い違い・実装量が残る | — | 見送り | — |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| [pi の拡張](../spec/guard/pi-extensions.md)の `guarded_action` | 操作 7 つ・gate・WIP の省略 → 操作 4 つ（`git_commit`・`gh_issue_*`）と `dir`・退避 | 本案件 | 適用済み |
| `pi-gitflow-guard.md` | 規約の強制の仕様 → 削除（履歴で読める） | 機能の撤去 | 適用済み |
| [開発](../spec/development.md)の gitflow-lite | AI が起票 → 利用者が起票し、AI は feature の worktree の `pi` から `git_commit` | 運用の変更 | 適用済み |
| [判定器](../spec/guard/pi-decide.md)の役割 | `shell_deny` に `git flow` → 外す | 機能の撤去 | 適用済み |

## 実装・検証

2026-10-31、作業ツリー（`feature/slim-guarded-action`）での実測。

| 確認 | 結果 |
| --- | --- |
| `test/agents/` | 5452 passed / 7 skipped（Windows のパスの試験） |
| 判定の正解データ（golden） | 6895 件、`--check` で一致 |
| `scripts/lint_templates.py` | 通過 |
| docs の検査（`lint_docs.py`・`pre-commit`） | `lint_docs.py` exit 0、変更ファイルの `pre-commit` 通過。全件は `mise run verify:all` で確認する（1 回目は ruff の 2 件と、`commit` スキルのコード表記を試験が拾った 1 件で失敗し、直して再実行） |

撤去の規模: 約 3,900 行（コード・試験）。

未確認: 実機（実モデル・TUI・Windows・Orca）。撤去の後に、実際の `pi` で `git_commit` を呼んだ確認。

## 残る課題

| 内容 | 状態 |
| --- | --- |
| 誘導の再分類（3 層: 境界 / 必須確認 / 誘導。fail-open の誘導を、止めずに案内する形へ整理） | 別案件として起こす予定（未起票） |
| 判定器の Python 版の撤去（[CHG-0035](0035-retire-python-judge-oracle.md)） | 後続 |
| bash の字句解析（tokenizer）が 6 か所に分かれているのを統合する。`unbash`（npm）を評価する | 後続（未起票） |

## 重要な更新

| 日付 | 変更 | 理由 |
| --- | --- | --- |
| 2026-10-31 | 案件を起こした。規約の強制と gitflow の 4 操作を撤去し、`guarded_action` を縮めた。[CHG-0049](closed/0049-gitflow-convention-guard.md) を Abandoned で閉じ、[CHG-0047](0047-gitflow.md) の目的を改めた | [ADR-0021](../adr/0021-conventions-as-instructions-slim-guarded-action.md) |
| 2026-10-31 | `git_commit` の `dir` が、`GIT_CONFIG_COUNT` を常に設定する環境で拒否されていたのを直した。拒否リスト（`repoSelectingEnv`）をやめ、対象を選ぶ 7 変数を落とした環境（`repoTargetEnv`）を、解決・プレビュー・スナップショット・実行で共用した | `GIT_CONFIG_*` は対象を変えない（実測）。`--show-toplevel` は `GIT_DIR` の乗っ取りを検出できないので、観測ではなく変数を外すことを守りの本体にした |
