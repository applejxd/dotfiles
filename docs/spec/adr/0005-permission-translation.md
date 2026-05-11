# ADR-0005: Permission モデルの翻訳則

- Status: Accepted
- Date: 2026-04-29
- Deciders: maintainer
- Related: ADR-0001, ADR-0004, REQ-040, REQ-041

## Context

Claude Code の `~/.claude/settings.json` には allow / ask / deny の **3 段階 permissions** があり、`home/dot_claude/modify_settings.json` で詳細にチューニングされている:

- allow: 32 件（git/wc/find/uv/cmake/WebFetch ドメイン等）
- ask: 9 件（uv add, npm install, mv, .env._ 編集, git commit, curl 等）
- deny: 30 件（sudo, rm, git push/reset/rebase, .ssh/_, _token_, _password_, etc.）

Copilot CLI の permission モデルは:

- **2 段階**: `allow` / `deny` のみ（`ask` 概念は対話 UI 任せ）
- 表現: `--allow-tool='shell(git:*)'` / `--deny-tool='shell(git push)'`
- 永続化: `~/.copilot/permissions-config.json`（自動管理、手書きも可）
- URL: `allowedUrls` / `deniedUrls`（settings.json）
- 全許可: `--yolo` / `COPILOT_ALLOW_ALL=true`
- **deny は allow に常に優先**

## Decision

### 射影則

| Claude permission 種別 | Copilot 翻訳先 | 変換規則 |
| --- | --- | --- |
| `Bash(cmd:*)` | `shell(cmd:*)` | ツール名のみ `Bash` → `shell` 変換 |
| `Read(path)` | （対応概念なし） | **省略** する。Copilot は path 単位 allow/deny は `--add-dir` / `--allow-all-paths` で粗粒度管理のみ |
| `Write(path)` | （対応概念なし） | 同上、省略 |
| `WebFetch(domain:X)` | `allowedUrls: ["X"]` または `*.X` | `allowedUrls` に追加 |
| `mcp__server__tool` | `allow-tool: 'server(tool)'` | MCP ツール名構文を変換 |

### `ask` の取り扱い

Copilot に `ask` 概念がないため、9 件の Claude `ask` リストは以下の方針で振り分ける:

| 旧 Claude `ask` | 翻訳方針 |
| --- | --- |
| `Bash(uv add:*)` / `Bash(npm install:*)` / `Bash(npm ci:*)` | **何も書かない**（デフォルトでツール実行ごとに対話確認になる） |
| `Bash(mv:*)` / `Bash(curl:*)` / `Bash(python -c:*)` / `Bash(docker exec:*)` | 同上 |
| `Read(.env.*)` / `Write(.env.*)` / `Write(mise.toml)` / `Bash(git commit:*)` | パス系は対応物なし。git commit はデフォルト確認に委ねる |

要するに **「特に書かない = 対話で都度確認」** が Copilot のデフォルト挙動なので、`ask` 相当を表現するには **何もしない** のが最も近い。

### `deny` の優先

### `Read(path)` / `Write(path)` の path 単位 deny

Copilot の `--allow-tool` / `--deny-tool` は **shell 系（コマンド名マッチ）** が主であり、Read / Edit / Write / MultiEdit のような **ネイティブツールへの path 単位 deny は公式には対応物がない**。本リポジトリの最重要要件である機密ファイル保護（`.ssh/*`, `*.env`, `*token*` 等）を維持するため、以下の二段階で代替する:

1. **Bash 経由のアクセス**は既存の `check_bash` hook が `SENSITIVE_PATH_PATTERNS` で拒否（既存ロジックを維持）
2. **ネイティブの Read / Edit / Write / MultiEdit 経由のアクセス**は `redirect-tmp` hook（ADR-0004 で再構築）に **path 検査を追加** するか、または **同様の `preToolUse` hook を新設** して `tool_input.file_path` / `tool_input.path` を `SENSITIVE_PATH_PATTERNS` で照合し deny する

`check_bash` 単独では shell コマンド経由しか塞げない点に注意（`check_bash.py:233-239` は `tool_name == "Bash"` のときしか動かない）。本 ADR で path 単位保護を「hook で代替」と書く場合、必ず Bash 以外のツールも対象にする hook 拡張を伴うことを要件 (REQ-041) で固定する。

### 全許可モード

- Claude の `Bash` 全許可 (`Bash(*)`) は Copilot の `--allow-all-tools` 相当
- 既定では全許可にしない（既存ポリシーを維持）

### 設定ファイル

- **URL** の allow / deny（Claude `WebFetch(domain:...)` の翻訳結果）は `home/dot_copilot/modify_config.json` の `allowedUrls` / `deniedUrls` キーに追加（公式 docs で Settings 上のキー名が確認済）
- **Shell tool** の allow / deny（Claude `Bash(...)` の翻訳結果）は **永続化先が公式 docs 上未確定** → 現時点では **TODO: 要確認**
  - Copilot 公式は `~/.copilot/permissions-config.json` を「自動管理ファイル」として案内しており、手書きで `~/.copilot/config.json` / `settings.json` の `hooks` セクションのように直書きできるかは未検証
  - 実装フェーズで以下の検証タスクを行う: (a) `--allow-tool` / `--deny-tool` で 1 件登録した後の `permissions-config.json` の中身を確認、(b) 同ファイルを chezmoi 管理対象にできるかを確認、(c) inline 直書きが許容されるかを確認
  - 検証完了まで shell tool deny の install 方法は **TODO**、要件 REQ-040/REQ-044 に従って `migrated` 判定保留

## Consequences

### 肯定的

- 機密保護系の deny は維持され、セキュリティ要件が後退しない
- `ask` 相当を「何も書かない」で表現することで、Copilot の自然な対話確認に委ねられる
- Path 単位の機密保護は hook 側に集約され、責務分離が明確になる

### 否定的

- `Read(**/*token*)` 等の path 単位 deny は Copilot permissions では表現できないため、hook 経由の保護に依存度が高まる
- `ask` 概念が永続化されないため、新セッション開始時に再確認が発生する可能性がある（Copilot の `permissions-config.json` 自動更新次第）

## Options Considered

1. **採用**: shell 系のみ翻訳、path 単位は hook で代替、`ask` は「書かない」
2. 却下: `--yolo` / `COPILOT_ALLOW_ALL` を常用
   - 却下理由: 現行のセキュリティポリシーを大幅に後退させる
3. 却下: path 単位の保護を諦める
   - 却下理由: `.ssh/*`, `*.env` 等の機密ファイル保護は本リポジトリの最重要要件

## References

- `docs/research/copilot-spec.md` §7.3「Permission モデル」
- `docs/research/copilot-spec.md` §8.2.5「Permission モデルの粒度差」
- `docs/research/claude-spec.md` §4.3「permission rule 構文」
- `home/dot_claude/modify_settings.json`
