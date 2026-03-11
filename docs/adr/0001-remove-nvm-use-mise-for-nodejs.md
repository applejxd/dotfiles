# ADR 0001: nvm を削除し mise で Node.js を管理する

- **Status**: Accepted
- **Date**: 2026-03-11
- **Deciders**: applejxd

## Context

zsh の起動時間が **~10.7 秒** と非常に遅い。
`zprof` による計測の結果、**nvm が起動時間の 78% (3.5秒)** を占めていることが判明した。

`nvm.sh` は 4,661 行の巨大なスクリプトで、`source` 時に `nvm_auto` → `nvm_ensure_version_installed` と連鎖的に実行される。

一方、すでに `mise` がインストール・設定済みで Node.js v24.5.0 を管理しており、nvm との二重管理となっている。

## Decision

`shellenv.sh.tmpl` から nvm の読み込みコードを削除し、Node.js のバージョン管理を mise に一本化する。

### 削除対象

```bash
# shellenv.sh.tmpl L80-83
export NVM_DIR="$HOME/.nvm"
[[ -s "$NVM_DIR/nvm.sh" ]] && . "$NVM_DIR/nvm.sh"
[[ -s "$NVM_DIR/bash_completion" ]] && . "$NVM_DIR/bash_completion"
```

### 移行手順

1. mise で使用する Node.js バージョンを確認・設定
2. `shellenv.sh.tmpl` から nvm 関連コードを削除
3. `chezmoi apply` で反映
4. 起動時間を再計測

## Consequences

### Positive

- zsh 起動時間が **~3.5 秒短縮**
- Node.js バージョン管理の一元化 (mise)
- プロジェクト単位の `.mise.toml` でバージョン切替可能

### Negative

- `.nvmrc` を使うプロジェクトでは mise の対応が必要
  - mise は `.nvmrc` / `.node-version` を読めるため実質問題なし
- nvm 固有の機能 (`nvm use`, `nvm alias`) は使えなくなる
  - mise の `mise use node@XX` で代替可能

### Risks

- `~/.nvm` ディレクトリは手動削除が必要（本 ADR のスコープ外）
