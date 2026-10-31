# CHG-0053: feature はローカルで自由にし、保護ブランチへの統合で確認・監査する

- **状態**: Exploring
- **更新日**: 2026-11-01
- **基準**: コミット 78d1dfd 以降、pi 1.4.0（設計の段階。実装は未着手）

## 目的と非目的

**目的**: 確認を、コミットごとから、保護ブランチ（`develop` / `main`）への統合へ寄せる。feature の中の作業を止めず、統合の時点で内容を監査できるようにする。

- 利用者の意図: feature はローカルに閉じるので、好き勝手にやってよい。機能実装をできるだけ止めない。保護ブランチへのマージは、機能のリリースに相当する。作業は完了しているので、そこでしっかり監査する
- 監査は、基本は利用者が git の履歴をツールで見る前提。マージ作業のときに、チャットへサマリーを出すと、なお親切

**非目的**: 規約（保護ブランチへ直接コミットしない）を、`edit` / `write` ごとに git の状態を読んで強制すること（[CHG-0049](closed/0049-gitflow-convention-guard.md) の失敗の再導入）。`git push` / `ssh` の扱いの変更（別案件）。

## 今の事実

- `git_commit`（`guarded_action`）は、どこから呼んでも、確認を 1 回出す。bypass でも省略できない。`dir` で feature の worktree や入れ子のリポジトリを指せる（[CHG-0050](0050-slim-guarded-action.md)）
- 承認画面は、大きな変更では要約と「全文を見る」で出す。詳細は、チャットにもツールの途中経過として出す（[CHG-0046](0046-guarded-action-timeout.md)）
- bash の `git flow` は、特別扱いが無い。`git commit` は、`guarded_action` へ誘導する。`git branch -D` / `git clean` / `git tag -d` などは、bypass でも確認する（`local_git`）
- `git push` と `ssh` は、共通の deny（他の AI CLI と共有の設定）
- 規約（直接コミットしない）は、`AGENTS.md` の指示だけで、機械では止めていない

## 草案と、第 1 回レビューの結果（2026-11-01）

草案の方針: ① 自由区（確認なしの commit）を、リンクされた worktree の保護でないブランチにする ② 出口（保護ブランチを変える操作・戻せない片付け）を強制確認にする ③ 出口の確認画面とチャットに、コミット一覧・差分統計・リスクの印を出す ④ 確認時と実行時の OID を照合する。

独立レビュー（別系統のモデル）の結論: 思想は妥当だが、草案の暫定結論は、そのままでは採用できない。

| 重要度 | 指摘 | 扱い |
| --- | --- | --- |
| BLOCKER | 出口を「サブコマンド名」で定義すると、保護 ref を変える経路が漏れる（`reset --soft`、`update-ref`、`fetch . a:b`、`branch -m`、`symbolic-ref`、実体名の `git-flow`、`git flow integrate`、alias、`rebase --update-refs`、`push . a:b`） | 出口の定義を「保護 ref の変更」にする。門の仕組みは案 H を検討 |
| MAJOR | bash の必須確認は「コマンド文字列の承認」で、git の状態の承認ではない。承認と実行の一致（OID の照合）は、構造化した操作でないと保証できない | 統合は専用の操作に戻す（決定） |
| MAJOR | `git push` / `ssh` の deny は、他の AI CLI と共有。消すと他の CLI にも許可が広がる | deny を維持し、別案件にする（決定） |
| MAJOR | 自由区を「保護でないブランチ全部」にすると広すぎる | 肯定的な条件にする（決定） |
| MAJOR | hook や衝突など、統合の途中の失敗の状態が未定義 | 結果（成功 / 未実行 / 部分実行）を契約に含める |
| MINOR | サマリーは、コミット一覧より、実際に入る結果（target の tree → 予定結果の tree の差分）が中心。リスクの印は、全変更から抽出する。最終結果にも OID と要約を残す | 反映する |

## 決定（利用者、2026-11-01）

- **自由区**: リンクされた worktree、かつ現在のブランチが `refs/heads/feature/*`（detached は不許可）。保護の集合は、下限として `main` / `master` / `develop` / `release/*` / `hotfix/*`。入れ子の通常の子リポジトリは、当面、確認を維持する。**判定できないときは、deny にせず、今までどおり確認する**
- **統合**: `guarded_action` に、ローカルの統合だけの専用操作を戻す。計画（source と target の OID、結果の tree、メッセージ、片付けの有無）を固定して、確認し、実行の直前に照合する。起票・WIP の無確認・規約の gate は戻さない
- **`git push` / `ssh`**: deny を維持する。pi 限定の緩和は、生成器の仕組みごと別案件で設計する
- **出口の門**: 案 H（下）を、先にレビューに出す

## 案 H: git の `reference-transaction` hook を、出口の門にする

- git（2.28 以降）が、ref の更新のたびに呼ぶ `reference-transaction` hook で、保護ブランチの更新を止める。`prepared` の状態で非ゼロで終了すると、その更新全体が取り消される。merge・reset・update-ref・fetch・branch -m・commit など、すべての更新が通る
- 止める条件: 更新される ref が保護の集合に含まれ、`old != new` で、AI のシェルの環境（`PI_AGENT_SHELL=1`。`[agent_env]` から渡す）にあり、統合の専用操作の許可（`PI_INTEGRATION_OK=1`。ハーネスが、承認後の git の子プロセスにだけ付ける）が無いとき。利用者の自分のシェルは、素通りする
- 設置: `scripts/gitflow-setup.sh`（利用者が実行）が `.git/hooks/reference-transaction` を作る。共有の `.git` の `hooks` と `config` は、`pis` の内側から書けない（要確認）ので、AI が外せない
- 狙い: 名前の列挙が要らず、BLOCKER の穴が構造的に塞がる。判定は、ref の名前と環境変数だけで、git の状態を読む失敗が無い（CHG-0049 との違い）
- 懸念: 環境変数の偽造（「うっかり防止」の範囲か）、hook の外し方（`-c core.hooksPath=/dev/null` など）、git の版と Windows、`git-flow` の内部の git 呼び出し、hook が落ちたときの方針（fail-open か fail-closed か）、pre-commit との共存、設置の配り方

## 第 2 回レビュー（案 H、2026-11-01）

結論: **案 H は、「穴が構造的に塞がる」「状態を読む失敗が無い」という前提を満たさない。**「監査を外せない門」ではなく、「通常の native git 操作に効く、うっかり防止の補助」として位置づける。思想（実装を止めず、統合で監査する）は妥当。

| 重要度 | 指摘 | 根拠 |
| --- | --- | --- |
| BLOCKER | hook を通らない ref 更新がある。git 2.43.0（この機の版）の `reference-transaction` は symbolic ref を対象にしない。files backend で、`branch -m` / `-c` の宛先の作成、`reflog delete --updateref` が、transaction の外で ref を直接書く | git の公式 docs、`refs/files-backend.c`（v2.43.0 / v2.53.0） |
| BLOCKER | `old != new` の条件は、無条件の削除（`update-ref -d`、`--stdin` の `delete`）を見逃す（old を指定しないとゼロ） | `refs.c` の `run_transaction_hook()` |
| BLOCKER | `[agent_env]` への追加だけでは、`bg_run`（`activity` 拡張は env を渡さない）、子 pi、edit 後の script に印が届かず、利用者の操作と誤認される | `harness/index.ts:479,580,976,1632`、`activity/index.ts:216-222` |
| MAJOR | `PI_INTEGRATION_OK=1` は、承認した操作に束縛されない。子孫プロセス（hook、git-flow の内部の git）全体への包括的な許可になる。許可の自己申告（`PI_INTEGRATION_OK=1 git reset ...`）もできる | `actions.ts:602-619`、git-flow-next の環境継承 |
| MAJOR | 統合の実行場所が Fence と合わない。feature で起動した pi は、本体の develop の作業ファイルを書けない（`dir` も cwd 配下限定） | `boundary.py:244-252`、`actions.ts:144-166` |
| MAJOR | 故障時の契約が不足。`pack-refs` / `gc` が、ゼロ→OID の transaction で保護ブランチを誤検知する。推奨は fail-closed（有効な AI 呼び出しで、保護 ref を無許可更新するとき）。hook の未設置・非実行・未対応は、自由区の確認省略を有効にしない | `refs/files-backend.c` の `files_pack_refs()` |
| MAJOR | 設置の配り方: linked worktree の `.git` はファイル。`gitflow-setup.sh` は既存の `.gitflow` を同期した後に終わる。`core.hooksPath` があると標準の hooks は使われない。pre-commit 4.3.0 は hooksPath を拒否する | `scripts/gitflow-setup.sh:25-29`、`uv.lock`、pre-commit の `install_uninstall.py` |
| 問題なし | 共有 `.git` の `hooks` / `config` が、`pis` の内側から書けない（実測済みの記述）。`pre-commit` / `pre-push` との共存。remote 追跡 ref を保護対象にしないこと | `boundary.py:248-252,291`、`docs/change/0029-worktree-isolation.md` |

第 1 回の穴のうち、案 H が止めるもの: `reset --soft` / `reset`、`update-ref`（条件付きで削除を除く）、`fetch . a:b`、`branch develop feature`、`git-flow` の最終更新、`rebase --update-refs` の保護 ref。止めないもの: 上の BLOCKER の経路。

レビューの推奨の方向: H を、限定された補助ガードとして採用する。包括的な boolean 許可をやめ、限定された計画（target の ref、期待する旧 OID、承認した結果の OID）を `update-ref` の CAS で更新する。ただし、この計画を環境変数で渡しても、意図的な偽造は防げない（誤爆・許可の持ち越し・競合を減らすだけ）。偊造不能にするには、AI から ref の書込権限を外す別設計が要り、費用が大きい。

レビューの実装順の提案: ① 保証範囲の確定 ② 使い捨てリポジトリでの実 git 試験 ③ AI 環境の共有 helper ④ hook の設置・健全性確認 ⑤ 限定許可と統合の専用操作 ⑥ 自由区の分類（確認省略なし） ⑦ 合格した対象だけ WIP の確認省略を有効化 ⑧ 整合。

評価: 費用と効果を見直すと、案 H を全部入れると、「hook」「共有環境 helper」「設置の配布」「限定許可と CAS」「実行場所の契約」が同時に要る。これでも完全ではない（symbolic ref、rename/copy の宛先、reflog が残る）。防いでいるのは意図的な ref 操作で、「うっかり防止」の脆威モデルでは、実際に起きうる事故は `merge`・`finish`・`reset`・`cherry-pick`・`rebase` など通常の統合操作である。第 1 回の BLOCKER（名前の列挙の穴）も、多くは意図的な経路。決定: 最小案 M で進める。実装の計画は `plan` で作り、段ごとに feature を切る

### 最小案 M（決定、利用者、2026-11-01）

- 統合の専用操作（`guarded_action`）: 計画（source / target の OID、結果 tree、メッセージ）を固定し、確認し、実行直前に照合する。実行場所は、本体側の pi または利用者のシェル
- bash：保護ブランチを変える**通常の統合コマンド**（`git flow feature finish`、`git-flow`、`merge`、`cherry-pick`、`pull`、`am`、`rebase`、`reset`、`update-ref`、`branch -f/-m/-c`、`symbolic-ref`、`fetch` の宛先が保護 ref、この一覧の外の git 書き込みを確認）を必須確認にし、専用操作へ誘導する
- 自由区（確認省略の commit）: 統合の専用操作ができた**後に**、最後に有効化する
- hook（案 H）: 統合の専用操作と実 git 試験の結果を見て、補助の門として後から足すかを決める。足すなら、`old != new` の条件を落とす、AI 環境を共有 helper で統一する、限定許可にする、fail-closed（設置漏れは自由区を有効にしない）
- 保証の範囲を「ガードが識別する直接経路」と明記する（Python や node から直接書く経路は保証外。従来の脆威モデル）

## 受入条件（暫定。レビューの結果で見直す）

- **A1**: feature（リンクされた worktree、`refs/heads/feature/*`）の `git_commit` は、確認の画面を出さずに実行する。状態を読めないときは、今までどおり確認する
- **A2**: 保護の集合の ref を、AI の経路で更新しようとすると、専用の統合操作を通さない限り、止まる（直接の git・git-flow・plumbing・alias を含む。「ガードが識別する直接経路」の範囲）
- **A3**: 統合の確認画面とチャットに、結果の差分統計・リスクの印（ガードの設定・hook・指示・検証の定義の変更、削除、大きな差分、秘密らしいパス）・実際のメッセージ・OID が出る。承認した計画と実行の直前の状態が違えば、実行しない
- **A4**: 統合の途中の失敗は、成功 / 未実行 / 部分実行を区別して返し、自動の復旧や再試行をしない
- **A5**: 利用者の自分のシェルの操作を、邪魔しない
- **A6**: `git push` / `ssh` の deny、他の AI CLI の生成物は、変わらない

## 実施計画（plan の結果、2026-11-01）

静的な読み取りの計画。実測で確かめた前提: `pis` の内側では、`git merge` / `cherry-pick` / `pull` / `am` / `git flow feature finish` / `update-ref` / `symbolic-ref` が**確認なしで allow** になる。`git rebase` は共通 deny、`git reset --soft` は ask。feature の中でも `rebase` は deny のまま（別案件）。確認を緩める変更は最後の S5b だけ。

| 段 | 内容 | 担当 | 状態 |
| --- | --- | --- | --- |
| S0 | 要約の部品を `confirm-view.ts` へ移す・確認の select ループと git 実行の共通化（挙動不変） | 親 | 未着手（要約を箇条書きにする変更の取り込み後） |
| S1 | 設定の足場（`[pi.integrate]`、`[pi.confirm] integration`、保護 ref の判定）。挙動不変 | worker | 完了（`develop` に取り込み済み、配備済み。挙動不変） |
| S2 | 自由区の判定（linked worktree かつ `feature/*`。確認は省略しない） | worker | 完了（`harness/freezone.ts`・`gitrun.ts`。部品のみで、まだ接続しない。試験 `test_pi_freezone.py`） |
| S3a | 統合の計画の算出と表示（結果の差分・リスクの印。ツールには未接続） | worker | 未着手 |
| S3b | 専用操作 `git_integrate`（計画の固定・直前照合・結果 3 値） | 親 | 未着手 |
| S4 | bash の統合ゲート（保護 ref を変える通常の統合コマンドを必須確認にし、feature の日常の操作は止めない） | worker | 未着手 |
| S5a | 確認省略のコード（設定は false。この段だけでは no-op） | worker | 未着手 |
| S5b | 確認省略を有効化（**最後**） | 親 | 未着手 |
| S6 | docs の整合と `verify:all` | 親 | 未着手 |

順序は利用者の判断待ち（S4 を S3 より先にする推奨案と、計画の順）。計画の全文は非公開の作業置き場（`.tmp/subagents/`）にある。

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り / 消滅

## 未解決点

- 案 H の採否（第 2 回レビューの結果）
- 環境変数による許可の渡し方が、偽造・誤爆・競合に強いか
- 入れ子の子リポジトリ（仮想 monorepo）の自由区への拡張
- hook の設置の配り方（chezmoi の管理外のリポジトリ）と、Windows での動作

## 評価基準

- 必須: 保護ブランチの更新が、AI の経路で、確認なしに通らない。feature の作業が、確認で止まらない
- 望ましい: 承認画面を見る回数が減る（コミットごとから、統合ごとへ）。判定の失敗で作業が止まらない

## 重要な更新

| 日付 | 変更 | 理由 |
| --- | --- | --- |
| 2026-11-01 | 案件を起こした。設計の草案・第 1 回レビューの反映・決定・案 H を記録した | 利用者の意図（feature は自由、統合で監査）の設計 |
