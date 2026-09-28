# トラブルシューティング

症状から対応する項目を探す索引。本体は 2 つに分けている。

- [導入と適用](troubleshooting-bootstrap.md): `chezmoi apply` / `chezmoi update`、
  スクリプトの再実行、Python、Bitwarden、mise、APT、AI CLI の導入
- [AI CLI の実行時](troubleshooting-agents.md): sandbox、hook、skills

## まず見るもの

```bash
chezmoi apply --verbose            # 実行するスクリプトの中身も表示する
chezmoi status --include=scripts   # 次の apply で走るスクリプト（R）
```

`chezmoi diff` / `chezmoi status` は AI CLI の sandbox の外で実行する。

## 症状から探す

| 症状 | 対象 | 対応先 |
| --- | --- | --- |
| 前提を揃えて `chezmoi apply` してもスクリプトが走らない | 全 OS | [スクリプトを走らせ直す](troubleshooting-bootstrap.md#スクリプトを走らせ直す) |
| 「一部の開発ツールを導入できませんでした」 | Linux / WSL | [ツール 1 個の失敗で apply を止めない](structure.md#ツール-1-個の失敗で-apply-を止めない) |
| sudo のパスワード入力で止まる | macOS | [sudo のパスワードで止まる](troubleshooting-bootstrap.md#sudo-のパスワードで止まる) |
| `No module named 'tomllib'`、`chezmoi-python3: no such file or directory` | Linux / WSL / macOS | [Unix で tomllib が無いと言われて apply が止まる](troubleshooting-bootstrap.md#unix-で-tomllib-が無いと言われて-apply-が止まる) |
| `tomllib` や Python のエラー | Windows | [Windows で tomllib や Python のエラーが出る](troubleshooting-bootstrap.md#windows-で-tomllib-や-python-のエラーが出る) |
| `You are not logged in.`、`error calling bitwarden`、`bw: command not found` | 全 OS | [chezmoi update が Bitwarden で止まる](troubleshooting-bootstrap.md#chezmoi-update-が-bitwarden-で止まる) |
| age 鍵が無い、sops で復号できない | 全 OS | [Secret管理セットアップ: 鍵が見つからない](sops-age.md#鍵が展開されない) |
| `bw` などの npm 由来のツールが `Cannot find module` / `node: not found` | Linux / WSL / macOS | [mise の npm ツールが突然動かなくなる](troubleshooting-bootstrap.md#mise-の-npm-ツールが突然動かなくなる) |
| VS Code の拡張が入っていない | ネイティブ Linux / Windows | [VS Code の拡張が入っていない](troubleshooting-bootstrap.md#vs-code-の拡張が入っていない) |
| `apt update` が GitHub CLI の `NO_PUBKEY` を警告する | Ubuntu | [apt update が GitHub CLI の NO_PUBKEY を警告する](troubleshooting-bootstrap.md#apt-update-が-github-cli-の-no_pubkey-を警告する) |
| `apt update` が VS Code のソース二重登録を警告する | ネイティブ Linux | [apt update が VS Code のソース二重登録を警告する](troubleshooting-bootstrap.md#apt-update-が-vs-code-のソース二重登録を警告する) |
| `No version is set for shim`、`configuration invalid` | Linux / WSL / macOS の AI CLI | [AI CLI が mise に global default version を指定しろと言う](troubleshooting-bootstrap.md#ai-cli-が-mise-に-global-default-version-を指定しろと言う) |
| `403`、「導入できなかった CLI」 | Linux / WSL / macOS の AI CLI | [AI CLI の導入が 403 で失敗する](troubleshooting-bootstrap.md#ai-cli-の導入が-403-で失敗する) |
| sandbox の中で全ツールが即失敗する（`requires 'slirp4netns' on PATH` など） | Linux / WSL の Copilot CLI | [Linux で sandbox がコマンドを 1 つも実行できない](troubleshooting-agents.md#copilot-cli) |
| `/sandbox` に Dependencies タブが出る | Linux / WSL の Claude Code | [Linux で sandbox がコマンドを 1 つも実行できない](troubleshooting-agents.md#claude-code) |
| sandbox の中で読めない・書けない | Claude Code / Copilot CLI | [sandbox](agent-sandbox.md) |
| hook が起動しない | Windows の Copilot CLI | [Windows で Copilot の hook が起動しない](troubleshooting-agents.md#windows-で-copilot-の-hook-が起動しない) |
| `Failed to load 1 skill.` | Claude Code / Copilot CLI | [CLI 起動時に Failed to load 1 skill と出る](troubleshooting-agents.md#cli-起動時に-failed-to-load-1-skill-と出る) |
| `~/.copilot/skills` が作られない | Windows の Copilot CLI | [Windows で .copilot/skills のリンクが作られない](troubleshooting-agents.md#windows-で-copilotskills-のリンクが作られない) |

[仕様・運用一覧へ戻る](index.md)
