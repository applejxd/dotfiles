# develop への統合は merge、rebase は feature 同士だけ

- **ステータス**: Accepted
- **日付**: 2026-11-14
- **決定者**: applejxd
- **関係**: ADR-0038（`init` の前提）。feature-orchestration の統合の手順（束ねる）を定める

## コンテキスト

- `develop` は、この PC だけでなく、他のホスト（主に自宅）も試験的な設定を試すために取り込む。**公開された履歴**なので、書き換えると、他のホストの履歴と食い違う。
- `chezmoi update` は `git pull --autostash --rebase` を固定で実行する（`chezmoi update --help`。`pull.rebase` の設定では変えられない）。
- 2026-11-14、未 push の `develop` に `chezmoi update --init` を実行すると、`git flow feature finish --no-ff` で作った merge commit 5 件が平らに作り直された（ファイルの内容は同じ。ツリーのハッシュが一致）。
- 複数の feature を 1 回の統合（ask 1 回・検査 1 回）にまとめたい。
- 実験（使い捨てのリポジトリ）: feature B を A の上、C を B の上に rebase で積み、C だけを `finish` すると、A・B・C が 1 回で入る。A・B の枝は `git branch -d` で消せる。

## 決定

- **feature → `develop` と、`develop` → `main` は merge**（`--no-ff`）。公開された履歴は書き換えない。
- **rebase してよいのは feature の枝だけ**（まだ誰も持っていない）。push・publish した feature は rebase しない。
  - feature を最新の `develop` に追従させる: `git flow feature update <名前> --rebase`。
  - 複数の feature を束ねる: feature 同士を rebase で 1 本の線に積み、一番上だけを `finish` する（merge commit は 1 つ）。
- **統合後の実機への反映は `chezmoi apply`**（pull しない）。`chezmoi update` は、未 push のコミットが無いときだけ使う（未 push の merge commit を平らにするため）。
- 権限: `.tmp/worktrees/` の下で `feature/*` へ載せる `git -C <worktree> rebase feature/<名前>` だけを allow にする（`--exec`・`-x`・`-i` は ask のまま）。`finish` は ask のまま。
- 手順は [feature-orchestration](../../.agents/skills/feature-orchestration/SKILL.md)。

## 結果

- 良い点: 統合 1 回で merge commit 1 つ・ask 1 回・検査 1 回。公開された履歴を書き換えない。
- 悪い点: `chezmoi update` を、未 push のコミットがある `develop` で使えない（`apply` を使う）。feature を積むとき、衝突が起きうる。
- 見直しの条件: `chezmoi update` が rebase 以外を選べるようになったとき。
