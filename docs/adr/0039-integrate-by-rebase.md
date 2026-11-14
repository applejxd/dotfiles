# feature の統合は rebase + fast-forward を基本にする

- **ステータス**: Accepted
- **日付**: 2026-11-14
- **決定者**: applejxd
- **関係**: ADR-0038（`chezmoi update` が rebase を使う事実を前提にする）。feature-orchestration の「束ねる」（bundle）を廃止する

## コンテキスト

- `chezmoi update` は、内部で `git pull --autostash --rebase` を実行する（`chezmoi update --help`。chezmoi の固定の挙動で、`.gitconfig` の `pull.rebase false` では変えられない）。
- 2026-11-14、未 push の `develop` に対して `chezmoi update --init` を実行すると、`git flow feature finish --no-ff` で作った merge commit 5 件が rebase で平らに作り直された。ファイルの内容は同じ（ツリーのハッシュが一致）だったが、「統合 1 回 = merge commit 1 つ」の履歴は残らなかった。
- 実験（使い捨てのリポジトリ）: `git flow feature update <名前> --rebase` で feature を `develop` の先頭へ載せ替え、`git flow feature finish <名前> --ff-only` で fast-forward すると、merge commit が無い線形の履歴になる。`develop` が進んでいると `--ff-only` は失敗する（検査した先頭がそのまま入ることを保証する）。

## 決定

- **feature → `develop` の統合は、rebase + fast-forward を基本にする。** merge commit は作らない。
  1. `git flow feature update <名前> --rebase`
  2. rebase で変わったら、検査をやり直す
  3. `git flow feature finish <名前> --ff-only --keepremote --no-fetch --no-push --notag`
- 2 件以上は、1 件ずつ順に行う。複数を 1 つの merge commit にまとめる bundle は使わない。
- `develop` → `main` の統合（`git flow integrate develop`）は、これまでどおり merge のまま（リリースの区切りを残すため。`chezmoi update` は `main` を rebase しない）。
- 手順は [feature-orchestration](../../.agents/skills/feature-orchestration/SKILL.md) の工程 8。

## 結果

- 良い点: `chezmoi update` で履歴が書き換わっても、形が変わらない。履歴が線形で読みやすい。
- 悪い点: 「どの feature が何を入れたか」を merge commit で追えない（コミット件名と枝の名前で追う）。rebase のたびに検査をやり直す必要がある。
- 見直しの条件: `chezmoi update` が rebase 以外を選べるようになったとき。
