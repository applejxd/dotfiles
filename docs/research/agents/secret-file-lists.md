# 秘密ファイル一覧のずれと直下以外の `.env`

2026-10-03 の観測。OpenCode v2 / WSL2 Ubuntu / `mise run opencode:probe`
（`opencode run --standalone`、実 DB を使わない）。案件は
[CHG-0011](../../change/0011-agent-first-shell.md) の 1c。

## 問い

1. Bash hook の `tables.toml` と `[file] read_deny_globs` で、守るファイルがずれていないか
2. `app/.env` のような直下以外の `.env` は read で守られるか

## 1. 一覧のずれ

`bashrules/tables.toml` の `credential_paths` / `history_basenames` のうち、
`read_deny_globs` に無かったもの（Read ツール・OpenCode の read・Copilot の
`check_file_read.py` で読めた）:

- `~/.config/gh/hosts.yml`、`~/.docker/config.json`、`~/.git-credentials`、`~/.kube/config`
- `~/.config/gcloud/credentials.db`、`~/.azure/msal_token_cache.json`、
  `~/.terraform.d/credentials.tfrc.json`
- シェル履歴 7 種（`.bash_history` `.zsh_history` `.python_history` など）

`~/.copilot/config.json` だけは両方にあった。

## 2. `.env` の実測

配備済みの `opencode.json` には `.env` / `.env.*` が `**/` 無しで入っており、
OpenCode の resource は先頭固定のためルート直下にしか当たらない（`*/.env` が無い）。

```console
$ cd .tmp/envprobe   # app/.env にダミー文字列
$ mise run opencode:probe -- 'read ファイル app/.env を read ツールで読め'
! permission requested: read (app/.env); auto-rejecting
Error: The user declined this tool call
```

deny ではなく **ask**（OpenCode 既定の `*.env` の ask が当たっただけ）。
対話では承認すれば読める。`**/.env` へ直して生成した設定で再実測した。

```console
$ OPENCODE_PROBE_CONFIG=$PWD/.tmp/envprobe/cfg mise run opencode:probe -- 'read ツールで app/.env を読め'
✗ Read app/.env failed
Error: Permission denied: read
$ OPENCODE_PROBE_CONFIG=... mise run opencode:probe -- 'read ツールで <abs>/.kube/config を読め'
Error: Permission denied: read
```

どちらも hard deny（確認が出ない）。

## 結論

- 追加は `read_deny_globs` への 15 件と、`.env`（deny）・`.env.*`（ask）の `**/` 化
- 緩めた規則は無い。`.env.example` は `.env.*` の ask に含まれる（以前も直下では同じ）
- 対応は `test/agents/test_secret_lists_in_sync.py` が固定する
- Claude の `Read(.env)` の直下以外への効き方は未実測（`**/` を付けたので影響は強まる方向のみ）
