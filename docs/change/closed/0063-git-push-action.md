# CHG-0063: git push の承認つき action（`git_push`）

> この文書は取り下げの記録。実装は入れていない。再開するときの論点を残す。

- **状態**: Abandoned
- **更新日**: 2026-11-05
- **基準**: pi 1.4.0、[CHG-0050](0050-slim-guarded-action.md)（`guarded_action`）、[CHG-0053](0053-worktree-integration-gate.md)（push の deny 維持）

## 1. 目的

AI が、利用者の承認を得たときだけ `git push` を実行できるようにする（`guarded_action` に `git_push` を足す。bash の `git push` は共通 deny のまま）。
現状の push は、利用者が手で行う（`develop` の先行分は、次の `git push` で pre-push の gitleaks が動く）。

## 2. 経緯（2026-11-04〜05）

固定 argv の action として設計し、**独立 review を 5 回**かけた。回ごとに別の分類の穴が出て、終わりが見えなかった。

| 回 | 設計 | 出た BLOCKER の分類 |
| --- | --- | --- |
| 1・2 | 黒名簿・解釈（URL・設定・出力の解釈） | 解釈の食い違い、生出力の返却、複数送信先 |
| 3 | v3: 白名簿 URL・設定は拒否のみ | プレビューの署名検証が外部プログラムを起動、`GIT_CONFIG` で設定検査だけが別ファイルを読む、大きい hook の差し替え |
| 4 | v3.1: 設定を白名簿へ | 許可した `remote.<名>.fetch` でローカル ref を書き換え、作業ツリー diff が clean filter を起動、replace ref で表示と送信内容が違う |
| 5 | v3.2: fetch を標準値のみ・diff 廃止・replace 無効化 | symref の追跡 ref でローカル `main` を更新、`reference-transaction` hook が表示・照合なしで動く |

5 回目の 2 件は、「追跡 ref が symref」と「実行可能な `reference-transaction` hook」を確認前に拒否するだけで塞げることを試した（試験 343 件通過）が、
取り下げの決定で実装は残さなかった。

## 3. 取り下げの決定（利用者、2026-11-05）

`git_push` は**入れない**。push は今までどおり利用者が手で行う。

- **理由**: git は、repo の中の設定・attributes・hooks・refs・objects・環境のどれからでも、外部プログラムを起動し、ref を書き換えうる。
  固定 argv の action にしても、「承認画面の内容と、実際に実行・送信される内容が一致する」保証を、分類ごとに塞ぎ続ける必要があり、
  5 回の review で、毎回別の分類の穴が見つかった。維持の費用に対して、便益（AI が承認つきで push できる）が小さい。
- **見たこと**: 見つかった穴は、いずれも、repo の中に細工された構成（`.git` 配下の設定・hooks・refs）が前提だった。
  通常の使い方での事故は見つからなかった。ただし、保証を言うなら、その細工を塞ぐ必要がある。

## 4. 再開するときの論点

- 先に決める: 保証の範囲。「承認画面と実行内容の一致」を、**repo の中に細工された構成を含めて**言うのか、通常の使い方の範囲に限るのか。
- 取り得る形: (a) `git push` を、設定・hooks・環境を空にした**隔離した環境**（`GIT_CONFIG_*`・`core.hooksPath`・`HOME` を固定）で実行し、利用者の認証だけを渡す。
  (b) 承認画面に出すのを、送信先・枝・コミット一覧に限り、hook・設定の扱いは「うっかり防止」と明記する。
- 作業の記録: 実装・試験・各回の review の指摘は、ローカルの ref `refs/archive/git-push-action`（最新 `fcf6c347`）に退避した（公開リポジトリには無い）。
  白名簿・拒否の試験の流儀（CANARY で外部プログラムの未起動を確かめる）は、再利用できる。
