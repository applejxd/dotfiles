# Copilot CLI の sandbox の既定の許可範囲（`/sandbox policy`）

- **観測日**: 2026-09-13（記録したコミット `7f30a80` は 2026-09-14 00:12）
- **対象**: GitHub Copilot CLI 1.0.84-5、WSL2、このリポジトリ（chezmoi の source）を
  cwd にして起動。`allowDevToolAccess` は既定の `true`、`copilot_read_allow` /
  `copilot_write_allow` はまだ無い
- **一次情報**: Copilot のセッション内で実行した `/sandbox policy` の表示を、
  同コミットで `docs/spec/agent-permissions.md` に写したもの

現在の設定と、ここから導いた運用上の注意は
[sandbox (Claude Code / Copilot CLI)](../../spec/agent-sandbox.md#実測した既定の許可範囲-wsl2-chezmoi-リポジトリを-cwd-として-sandbox-policy)
が正本。**現在は `allowDevToolAccess = false` で許可も足してあるので、同じ表示には
ならない**。

## 表示

```text
System (read-only):  /etc /usr/bin /usr/lib /usr/lib32 /usr/lib64 /usr/libexec
                     /usr/sbin /usr/share /run/NetworkManager /run/systemd/resolve
                     /mnt/wsl/resolv.conf
System (read-write): $TMPDIR
Working directory:   <cwd> (read-write)
Current session:     ~/.copilot/session-state/<id>/files (read-write)
Copilot home:        ~/.copilot/logs (read-only)
Personal skill roots: ~/.agents/skills ~/.claude/skills (read-only)
Network:             Outbound allowed / Local network blocked
Dev-tool access:     Detected tools: python (パスはレポートに出力されない)
```

## 読み取れたこと

- `$HOME` 直下は 1 つも許可されていない。`~/.copilot` も `logs` だけが read-only で、
  `hooks` と `settings.json` は許可の外
- 設定した deny 10 件のうち、enforce されたのは 7 件だけだった。
  `~/.netrc` / `~/.npmrc` / `~/.pypirc` が未作成で、Notes 節に
  `does not exist; it is not enforced by the OS sandbox` と出た
