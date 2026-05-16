# AI CLI 統合 permission 管理

Claude Code / Copilot CLI の permission (allow/deny/ask) 設定を **単一ソース** で
管理し、`chezmoi apply` で両 CLI の設定ファイルへ自動展開する仕組み。

## ファイル構成

```
home/dot_config/agents/
    common.toml                              単一ソース
    critical_deny.py                         hook が import する shell normalizer
scripts/agents/
    generate.py                              modify_ から呼ばれる変換器
home/dot_claude/
    modify_settings.json.tmpl                ~/.claude/settings.json を更新
home/dot_claude/hooks/
    executable_check_bash.py                 critical_deny を呼んで hard-block
home/dot_copilot/
    modify_private_settings.json.tmpl        ~/.copilot/settings.json を更新
    modify_private_permissions-config.json.tmpl
test/agents/
    test_critical_deny.py                    shell normalize / match の unit test
```

`modify_private_*` のように `private_` を付けることで mode 600 を保持し、
`~/.copilot/settings.json` に含まれる `gho_xxx` トークンを保護している。

## 3 層防御モデル

| 層 | 仕組み | 強度 |
|---|---|---|
| 1. CLI UI prompt | Claude/Copilot の対話モードで毎回確認 | 対話時のみ有効 |
| 2. permission リスト | `~/.claude/settings.json` / `~/.copilot/{settings,permissions-config}.json` | 既知バグで bypass される ([後述](#claude-code-permission-リストの既知バグ)) |
| 3. **hook (最終防波堤)** | `check_bash.py` が `bash.critical_deny` を強制 block | 上 2 層を全て bypass されても block |

CLI 側 permission リストは「best-effort」と扱い、本当に止めたい命令は
`[bash.critical_deny]` に書く。

## common.toml の編集ルール

- 編集後は `chezmoi apply` で `~/.claude/settings.json` 等に反映される
- CLI UI で「Always allow」を押した場合は、その項目を common.toml に転記する
  (転記しないと次回 apply で消える。これは意図的な強制で、dotfiles を単一の
  真実とする方針)
- `[bash.critical_deny]` は hook が hard-block するので、Claude/Copilot 双方で
  確実に動作する
- `[bash.deny]` は Claude 側のみ反映 (Copilot CLI は path-scope の設計のため
  CLI フラグでしか細粒度 deny を表現できない)

## Claude Code permission リストの既知バグ

下記は 2026-05 時点で open。`critical_deny` + hook で必ず防ぐべき理由。

| Issue | 概要 |
|---|---|
| [#59498](https://github.com/anthropics/claude-code/issues/59498) | `cd /elsewhere && git push` が `Bash(git push:*)` ask/deny を bypass |
| [#59006](https://github.com/anthropics/claude-code/issues/59006) | `git -C /path commit` が `Bash(git commit *)` deny を bypass |
| [#20085](https://github.com/anthropics/claude-code/issues/20085) | compound 命令 (`a && b`) が個別評価されない |
| [#52419](https://github.com/anthropics/claude-code/issues/52419) | VS Code 拡張の auto-attach が `.claudeignore` / deny を bypass |

`scripts/agents/test_critical_deny.py` の `test_real_bug_*` ケースで、これらの
bypass パターンを hook が確実に block することを保証している。

## Copilot CLI の制約 (実機確認済)

- `~/.copilot/permissions-config.json` は **対話モードでのみロード** される。
  `copilot -p` (非対話モード) では一切無視される。
- `tool_approvals` の `kind: "commands"` の `commandIdentifiers` は
  **command 名の完全一致** のみで、`shell(git:*)` のような glob パターンの
  永続化サポートは未確証。よって本仕組みでは `[bash.allow]` の first token を
  ユニーク化して `commandIdentifiers` に集約する粗粒度方式を採用している。
- `kind: "write"` は MCP write tool 用で、shell tool (`touch`/`rm` 等) には
  効かない。
- `~/.copilot/settings.json` の `copilotTokens` / `loggedInUsers` /
  `installedPlugins` 等は Copilot 自動管理なので、generate.py はキー名
  ホワイトリスト方式で温存する。

## 動作確認手順

### unit test

```bash
python3 test/agents/test_critical_deny.py
# -> 26/26 passed
```

### dry-run

```bash
chezmoi diff ~/.claude/settings.json
chezmoi diff ~/.copilot/settings.json
chezmoi diff ~/.copilot/permissions-config.json
```

### apply 後の hook 動作確認

```bash
# 正常コマンド (PASS)
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | python3 ~/.claude/hooks/check_bash.py

# critical: cd && bypass を block
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"cd /tmp && git push"}}' \
  | python3 ~/.claude/hooks/check_bash.py
# -> stdout に permissionDecision: deny の JSON が出力される
```

## 新環境セットアップ

1. `chezmoi init --apply <repo>` で全ファイルが配置される
2. `~/.config/agents/common.toml` を編集して必要な項目を追加
3. `chezmoi apply` で両 CLI 設定が再生成される

なお初回 apply 時、Claude Code が未起動なら `~/.claude/settings.json` は存在しない。
chezmoi modify_ スクリプトは空 stdin を受けると空オブジェクトとして扱い、common.toml
ベースの最小 settings.json を生成する。

## トラブルシュート

| 症状 | 対応 |
|---|---|
| apply 後 Claude が `permissions` を読まない | Claude Code は起動時に settings.json を読むので再起動 |
| Copilot CLI で hook の deny が効かない | `~/.copilot/hooks/from-claude.json` が apply されているか確認。`copilot --log-level debug` で hook がロードされているか確認 |
| `~/.config/agents/critical_deny.py` の import に失敗 | `~/.config/agents/__pycache__/` を削除して `chezmoi apply` をやり直し |
| common.toml の編集が反映されない | `chezmoi diff` で差分を確認 → `chezmoi apply` |
