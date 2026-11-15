# develop への統合は merge、rebase は feature の枝の追従だけ

- **ステータス**: Accepted
- **日付**: 2026-11-14
- **決定者**: applejxd
- **関係**: ADR-0038（`init` の前提）。feature-orchestration の統合の手順（束ねる）を定める

## コンテキスト

- `develop` は、この PC だけでなく、他のホスト（主に自宅）も試験的な設定を試すために取り込む。**公開された履歴**なので、書き換えると他のホストの履歴と食い違う。
- `chezmoi update` は `git pull --autostash --rebase` を固定で実行する（`chezmoi update --help`。`pull.rebase` の設定では変えられない）。
- 2026-11-14、未 push の `develop` に `chezmoi update --init` を実行すると、`git flow feature finish --no-ff` で作った merge commit 5 件が平らに作り直された（ファイルの内容は同じ。ツリーのハッシュが一致）。
- 複数の feature を 1 回の統合（ask 1 回・検査 1 回）にまとめたい。
- 検討して退けた案: feature 同士を rebase で積んで一番上だけを `finish` する。そのために `git -C <worktree> rebase feature/*` を allow にすると、`reviewer` が、後続引数（`main` や `--onto main`）・追加の `-C`・`-c core.hooksPath=…`・省略形の `--ex=…` で、保護ブランチの書き換えや任意コマンドの実行に回り込めると指摘した。glob のパターンでは、安全な形だけを通せない。

## 決定

- **feature → `develop` と、`develop` → `main` は merge**（`--no-ff`）。公開された履歴は書き換えない。
- **rebase は、feature の枝を最新の `develop` に追従させるときだけ**: `git flow feature update <名前> --rebase`（git-flow が親への rebase だけを行う。確認なしで通る）。feature の枝は未公開なので書き換えてよい。push・publish した feature は rebase しない。
- **複数の feature は、束ね用の feature へ `git merge` で取り込んでから、1 回だけ `finish` する**（merge commit は 1 つ。ask は 1 回、検査は 1 回）。手順は [feature-orchestration](../../.agents/skills/feature-orchestration/SKILL.md) の「束ねる」。
- **`git rebase` の直接の実行は ask のまま**（allow にしない）。
- **統合後の実機への反映は `chezmoi apply`**（pull しない）。`chezmoi update` は、未 push のコミットが無いときだけ使う（未 push の merge commit を平らにするため）。

## 結果

- 良い点: 統合 1 回で ask 1 回・検査 1 回。公開された履歴を書き換えない。権限を緩めない。
- 悪い点: `chezmoi update` を、未 push のコミットがある `develop` で使えない（`apply` を使う）。feature 同士の rebase が必要になったら、確認が出る（直接の `git rebase` は ask）。
- 見直しの条件: `chezmoi update` が rebase 以外を選べるようになったとき。`git flow` が feature 同士の載せ替えを標準で提供したとき。
