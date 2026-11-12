# トラブルシューティング

症状から対応する項目を探す索引。本体は 2 つに分けている。

- [導入と適用](troubleshooting-bootstrap.md): `chezmoi apply` / `chezmoi update`、
  スクリプトの再実行、Python、Bitwarden、mise、APT、pi の導入
- pi の実行時の問題は、[pi の設定の生成と所有権](agent-config-generation.md)・[pi-sandbox-runner](sandbox/pi-sandbox-runner.md)・各 package の Issue から探す

## まず見るもの

```bash
chezmoi apply --verbose            # 実行するスクリプトの中身も表示する
chezmoi status --include=scripts   # 次の apply で走るスクリプト（R）
```

`chezmoi diff` / `chezmoi status` は、囲い（`pib`）の外で実行する。

## 症状から探す

| 症状 | 対象 | 対応先 |
| --- | --- | --- |
| 前提を揃えて `chezmoi apply` してもスクリプトが走らない | 全 OS | [スクリプトを走らせ直す](troubleshooting-bootstrap.md#スクリプトを走らせ直す) |
| 「一部の開発ツールを導入できませんでした」 | Linux / WSL | [ツール 1 個の失敗で apply を止めない](platform-raspberry-pi.md#ツール-1-個の失敗で-apply-を止めない) |
| 「zinit が無いためプラグインを読み込みません」、apply しても `~/.zinit` が空 | Linux / WSL / macOS | [apply しても zinit などの external が取得されない](troubleshooting-bootstrap.md#apply-しても-zinit-などの-external-が取得されない) |
| zsh の起動時に `wait ice received invalid suffix letter` | Linux / WSL / macOS | `chezmoi update` で dotfiles を最新にする（[zinit の遅延読み込みの順序](shell.md#zinit-の遅延読み込みの順序)） |
| `chezmoi: warning: config file template has changed, run chezmoi init` | 全 OS | [config file template has changed と警告される](troubleshooting-bootstrap.md#config-file-template-has-changed-と警告される) |
| sudo のパスワード入力で止まる | macOS | [sudo のパスワードで止まる](troubleshooting-bootstrap.md#sudo-のパスワードで止まる) |
| `No module named 'tomllib'`、`chezmoi-python3: no such file or directory` | Linux / WSL / macOS | [Unix で tomllib が無いと言われて apply が止まる](troubleshooting-bootstrap.md#unix-で-tomllib-が無いと言われて-apply-が止まる) |
| `tomllib` や Python のエラー | Windows | [Windows で tomllib や Python のエラーが出る](troubleshooting-bootstrap.md#windows-で-tomllib-や-python-のエラーが出る) |
| `You are not logged in.`、`error calling bitwarden`、`bw: command not found` | 全 OS | [chezmoi update が Bitwarden で止まる](troubleshooting-bootstrap.md#chezmoi-update-が-bitwarden-で止まる) |
| WSL にリモートから SSH できない（タイムアウト、`Connection refused`、`Permission denied`） | Windows + WSL（mirrored） | [リモートから WSL へ SSH する](platform-wsl.md#リモートから-wsl-へ-ssh-する)（[接続できないときの切り分け](platform-wsl.md#接続できないときの切り分け)） |
| age 鍵が無い、sops で復号できない | 全 OS | [秘密情報の管理セットアップ: 鍵が見つからない](sops-age.md#鍵が展開されない) |
| `bw` などの npm 由来のツールが `Cannot find module` / `node: not found` | Linux / WSL / macOS | [mise の npm ツールが突然動かなくなる](troubleshooting-bootstrap.md#mise-の-npm-ツールが突然動かなくなる) |
| VS Code の拡張が入っていない | 全環境（Settings Sync で同期） | [VS Code の拡張が入っていない](troubleshooting-bootstrap.md#vs-code-の拡張が入っていない) |
| `apt update` が GitHub CLI の `NO_PUBKEY` を警告する | Ubuntu | [apt update が GitHub CLI の NO_PUBKEY を警告する](troubleshooting-bootstrap.md#apt-update-が-github-cli-の-no_pubkey-を警告する) |
| `apt update` が VS Code のソース二重登録を警告する | ネイティブ Linux | [apt update が VS Code のソース二重登録を警告する](troubleshooting-bootstrap.md#apt-update-が-vs-code-のソース二重登録を警告する) |
| `No version is set for shim`、`configuration invalid` | Linux / WSL / macOS の旧 AI CLI | [AI CLI が mise に global default version を指定しろと言う](troubleshooting-bootstrap.md#ai-cli-が-mise-に-global-default-version-を指定しろと言う) |
| `pi --version` が `SyntaxError` などで落ちる、pi の導入（npm）が失敗する | Windows の pi | [Windows で pi が起動しない（古い node が先に見つかる）](troubleshooting-bootstrap.md#windows-で-pi-が起動しない古い-node-が先に見つかる) |

[仕様・運用一覧へ戻る](index.md)
