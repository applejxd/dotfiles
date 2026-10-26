# セキュリティ仕様の経緯メモ

`docs/spec/security.md#廃止した仕組み-chezmoi-本体の-age-暗号化` と `docs/spec/security.md#ai-エージェントの実行境界ubuntu--wsl` から移した記録。移設時点で再測定していない。

> **現行の仕様**: [セキュリティ](../../spec/security.md)。実行境界の脅威モデルは [サンドボックス（総覧）](../../spec/sandbox/index.md)。

## 記録 E1 — 廃止した chezmoi 本体の age 暗号化

- **観測日**: 移設前の spec の記述（観測日は元の文書に無い）。移設時点で再測定していない
- **対象**: chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt`、`.chezmoi.toml.tmpl` の `encryption = "age"`）

### 問い

なぜ chezmoi 本体の age 暗号化を廃止したか。

### 結果（元の文）

以前は chezmoi 本体の age 暗号化（`~/.config/chezmoi/key.txt` と
`.chezmoi.toml.tmpl` の `encryption = "age"`）も設定していた。
`chezmoi add --encrypt` したファイルを復号するためのものだったが、
暗号化ファイルを一度も運用しておらず、Bitwarden テンプレート方式
（`{{ (bitwarden ...) }}` を直接書く形）と機能が重複していたため廃止した。
既存マシンに `~/.config/chezmoi/key.txt` が残っていても `chezmoi apply` は
削除しないので、不要であれば手動で削除する。

### 考察

現行の運用は spec 側の 1 文（`key.txt` が残っていても apply は削除しない）だけを守る。

## 記録 E2 — 旧「AI エージェントの実行境界」節（OpenCode / `ocs` 前提）

- **観測日**: 移設前の spec の記述（観測日は元の文書に無い）。pis 前提の現行仕様とは食い違う（例: 「モデル API の資格情報は内側から平文で読める」は `ocs` の共有 DB の話で、`pis` の Copilot ブローカーには当たらない）

### 結果（元の文）

spec 側では `pis` の要約へ置き換え、元の OpenCode / `ocs` の説明は spec の「OpenCode 専用」の印つきの段落に残した（削除していない。CHG-0020 段 6 は保留中）。
元の導入の文は次のとおり。

> OpenCode を OS のアクセス制御（Fence）で囲って起動する（CHG-0004、CHG-0009）。通常起動（`opencode`）と**併用**する段階。
> 構成・起動順序・境界の組み立て規則は OpenCode 隔離起動のアーキテクチャ。ここでは何を守り、何を守らないかを書く。
> 境界の目的はエージェントのうっかり（外部への誤送信、ワークスペース外の破壊、秘密の誤読）の防止に絞っている（ADR-0012）。
