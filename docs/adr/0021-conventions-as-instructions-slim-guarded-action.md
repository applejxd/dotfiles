# ADR-0021: 運用規約をコードの強制から指示へ戻し、guarded_action を承認つきの commit と gh 投稿に縮める

- **ステータス**: Accepted
- **日付**: 2026-10-31
- **決定者**: リポジトリの所有者

## コンテキスト

pi のフルガード（`pis`）の `guarded_action` は、承認つきの `git_commit` と `gh` の投稿に加えて、gitflow-lite の運用を機械で支える層を持っていた（[CHG-0047](../change/0047-gitflow.md)、[CHG-0049](../change/closed/0049-gitflow-convention-guard.md)）。

- feature の起票・クローズ・コミット・破棄の 4 操作（`git flow` の固定引数の実行、実効設定の安全プロファイル、feature の worktree 内の `git_commit` の無確認）
- develop / main への直接の編集・コミットを拒否する gate（git の状態の収集つき）と、利用者の逃がし口
- bash の `git flow` / `git-flow` の deny

次の問題が分かった。

- **副作用**: git の状態を読めないとき（入れ子リポジトリ・仮想 monorepo など）に、bypass でも外れない確認が出る
- **設計の食い違い**: 規約（運用）を、境界（deny）と同じ強さで強制していた。規約は、守れないときに利用者が判断して外せるものなのに、外せない層に置いていた
- **実装量**: 約 3,900 行（コード・試験）の保守
- **実行コスト**: コミットごとに git を多重に起動していた

設計は 3 層に整理できる。**境界**（deny。秘密の読み取りなど常時禁止）、**必須確認**（外への送信・公開・push・ssh・戻せない操作）、**誘導**（fail-open。止めずに案内する）。運用規約は、このどれにも入らない。

## 検討した選択肢

### 選択肢 1: 全廃

`guarded_action` ごと撤去し、コミットと投稿は bash の ask に戻す。

- **利点**: 実装が最小になる
- **欠点**: 内容を見せて 1 回で承認する経路と、承認の時間切れの退避（[CHG-0046](../change/0046-guarded-action-timeout.md)）を失う。`gh` の本文を bash に引数として渡すと、引用の事故が増える

### 選択肢 2: 縮める（採用）

`guarded_action` を、承認つきの `git_commit`（`message`・任意の `dir`）と `gh_issue_comment` / `gh_issue_edit_body` / `gh_issue_edit_title` に縮める。退避（`pending-store`・`/pending`）と、子の隔離（`worktree.ts`）は残す。規約の強制と gitflow の 4 操作、bash の `git flow` の deny は撤去する。

- **利点**: 境界・必須確認・退避を弱めずに、副作用と実装量を減らせる
- **欠点**: develop / main への直接の編集・コミットを、機械では止めない

### 選択肢 3: 現状維持

- **利点**: 規約が機械で止まる。AI が `git flow` を使える
- **欠点**: 上の 4 つの問題が残る

## 決定事項

**選択肢 2（縮める）を採用する。**

理由:

- 運用規約は、コードで強制せず、指示（`AGENTS.md`・`commit` スキル）にする。外せない層（境界・必須確認）に置くと、状態を読めない場所で副作用が出る。強制が要る危険は、境界と必須確認（外への送信・公開・push・戻せない操作）にあり、ブランチの規約はそこに入らない
- 全廃（選択肢 1）は、内容を見せた 1 回の承認と、時間切れの退避という、残す価値のある部分まで失う
- 現状維持（選択肢 3）は、副作用と実装量を、規約を機械で止める便益のために払い続ける。便益（develop のまま実装が始まるのを防ぐ）は、指示と運用の観察で見積もれる（[CHG-0050](../change/0050-slim-guarded-action.md) の「未解決点」）
- ブランチモデル gitflow-lite 自体は残す。利用者が自分のシェルで `git flow feature start` / `finish` を実行し、AI は feature の worktree で起動した `pi` から `git_commit`（確認あり）する

運用規約を、後から機械で支えたくなったときは、**誘導**（fail-open。git を読めないときは何もしない）として足す。deny・確認にはしない。

## 決定の確認方法

実装の進捗は書かない（[CHG-0050](../change/0050-slim-guarded-action.md) が持つ）。

- [ ] 生成された `rules.json` の `judge.common.pi.actions` に、`gitflow_*` が無く、`git_commit` と `gh_issue_*` がある
- [ ] develop の作業ツリーで、`git_commit` が git の状態の読み取りの失敗を理由に拒否・確認されない
- [ ] 撤去後に develop / main への直接コミットが頻発していないか、履歴で確かめる

## 結果

### ポジティブな結果

- git を読めない場所での、外れない確認が出なくなる
- 約 3,900 行の保守と、コミットごとの git の多重起動が無くなる
- 設計が 3 層（境界 / 必須確認 / 誘導）で説明できる

### ネガティブな結果

- develop / main への直接の編集・コミットを、機械では止めない。指示が守られなければ、利用者が気づくまで続く
- feature の起票・クローズを、AI に任せられなくなる（利用者が自分のシェルで行う）
- feature の worktree 内の WIP コミットも、毎回確認が出る

### 中立的な結果

- ブランチモデル（`.gitflow`・git-flow-next・`scripts/gitflow-setup.sh`）は変わらない
- 誘導の再分類は、別案件として起こす（未起票）

## 関連 ADR

- [ADR-0017](0017-pi-only-and-ts-judge.md): 判定器を TypeScript に移し、pi に一本化した決定。判定器（`decide`）は、今回変えていない
