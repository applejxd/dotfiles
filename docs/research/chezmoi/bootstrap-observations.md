# 導入・適用の障害の観測記録（mise の npm ツールの欠損、GitHub CLI の APT 鍵の失効）

`docs/spec/troubleshooting-bootstrap.md#mise-の-npm-ツールが突然動かなくなる` と
`docs/spec/troubleshooting-bootstrap.md#apt-update-が-github-cli-の-no_pubkey-を警告する` から移した記録。
移設時点で再測定していない。現在の対処は各節を参照する。

> **現行の仕様**: 症状と対処は [導入と適用のトラブルシューティング](../../spec/troubleshooting-bootstrap.md)。

## 記録 E1 — 2026-09-15（mise の npm ツールの欠損）

- **対象バージョン**: npm-bitwarden-cli 2026.7.0、npm-markdownlint-cli2 0.22.1（mise の npm backend）
- **環境**: Linux / WSL（機は特定していない）

### 問い

mise の npm backend で入れたツールが突然動かなくなった。何が壊れていて、入れ直すとどうなるか。

### 事前の予想

探索的で予想は無い。

### 方法・条件

`installs/` 配下の symlink と実体を調べた。確認コマンドは次。

```bash
find ~/.local/share/mise/installs -path '*/node_modules/.mise/*' \
     -maxdepth 6 -xtype l -printf '%h\n' | sort -u
```

### 結果

導入物の一部が消えていた。2026-09-15 に次の 2 通りを観測した。
**何が消したかは特定できていない**（キャッシュ削除ツール、ディスク掃除、中断した
導入などが候補）。

- **A. キャッシュの実体が消えた**: npm backend は依存の実体を
  `~/.cache/aube/virtual-store/` に置き、`installs/` からそこへ symlink を張ることがある。
  `~/.cache` を消すとリンク先だけが消える。npm-bitwarden-cli 2026.7.0 では `.mise/` 配下の
  symlink 213 個が全滅し、実体ディレクトリで入っていた npm-anthropic-ai-sandbox-runtime は
  無傷だった
- **B. 導入物の一部が欠けた**: 古い世代の導入物は `bin/<tool>` が
  `../lib/node_modules/...` を指す。npm-markdownlint-cli2 0.22.1 は `bin/` が残って
  `lib/` だけが無かった。同じ世代の npm-google-gemini-cli は無傷で、個別の欠損だった

入れ直した後の `.mise/` 配下は symlink ではなく実体のディレクトリになっていた
（2026-09-15、3 ツールとも symlink 0 件）。

### 考察

元の文のとおり、消した主体は不明。再び symlink で入るようなら、`~/.cache` を
消さない運用にするか、消した直後に入れ直す。

### 次の問い

何が `~/.cache` や導入物の一部を消したか（未特定）。

### 参照

エラー文の例（`bw`）:

```text
Error: Cannot find module
  '~/.local/share/mise/installs/npm-bitwarden-cli/latest/node_modules/
   .mise/@bitwarden+cli@2026.7.0/node_modules/@bitwarden/cli/build/bw.js'
```

## 記録 E2 — 2026-10-01（GitHub CLI の APT 署名鍵の失効）

- **対象バージョン**: GitHub CLI の APT リポジトリ（`https://cli.github.com/packages`）
- **環境**: WSL

### 問い

`apt update` が GitHub CLI の `NO_PUBKEY` を警告する。鍵はどうなっているか。

### 事前の予想

探索的で予想は無い。

### 方法・条件

登録の `signed-by=` が指す鍵ファイルを `gpg` で見た。2 列目の `e` が失効。

```bash
gpg --show-keys --with-colons <登録の signed-by= が指す鍵ファイル> | grep -E '^(pub|sub)'
```

### 結果

2026-10-01 に WSL で確かめた例では、手元の鍵（`23F3D4EA75716059`）が
2026-09-06 に失効しており、配布元の鍵ファイルには新しい鍵 `5612B36462313325` が
加わっていた。

### 考察

残っている APT 登録の署名鍵が失効していたのが原因。chezmoi は自動で直さない
（既存の APT 登録・鍵・認証設定は自動削除しない方針）。

### 次の問い

なし。

### 参照

配布元の鍵ファイル: <https://cli.github.com/packages/githubcli-archive-keyring.gpg>
