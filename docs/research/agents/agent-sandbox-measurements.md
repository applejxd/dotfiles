# sandbox（Claude Code / Copilot CLI）の既定の許可範囲と経路の実測の記録

`docs/spec/sandbox/agent-sandbox.md#ホーム外の経路は塞いでいない契約と実装の不一致` と
`#実測した既定の許可範囲-wsl2-chezmoi-リポジトリを-cwd-として-sandbox-policy` から移した記録。
移設時点で再測定していない。現在の仕様は
[`docs/spec/sandbox/agent-sandbox.md`](../../spec/sandbox/agent-sandbox.md) が正本。
Copilot の `/sandbox policy` の表示そのものは
[copilot-sandbox-default-policy.md](copilot-sandbox-default-policy.md)、
開発ツールの許可は [copilot-dev-tool-access-grants.md](copilot-dev-tool-access-grants.md) にある（本文は変えない）。

## 記録 M1 — 2026-09-23（Claude の設定）・2026-09-13（Copilot の `/sandbox policy`）

- **対象バージョン**: 元の記載に無い（Copilot CLI は別記録を参照）
- **環境**: WSL2、`~/.claude/settings.json`、Copilot の `/sandbox policy`

### 問い

`/mnt`（WSL の Windows 側）と `/tmp` `/var/tmp` `/dev/shm` を、Claude と Copilot が sandbox の内側から
読めるのか。意図して開けているのか。

### 結果

#### ホーム外の経路の実測の状況と未決の点

実測の状況:

- **Claude**: 設定の実測（2026-09-23、`~/.claude/settings.json`）では、
  `/mnt` `/tmp` 系への指定は無い。

  ```text
  Claude の denyRead に /mnt・/tmp 系: なし
  Claude の allowRead に /mnt・/tmp 系: なし
  ```

  sandbox 内から実際に読めるかは Claude では
  **未検証**。OpenCode 側では `srt` のころに実測で `/mnt/c/Users` まで読めることを確認して塞いだ
  （[CHG-0004](../../change/closed/0004-opencode-sandbox.md)、
  [調査記録 21 節](../../research/opencode/permission/sandbox-runtime.md)）。
  今の `ocs`（Fence）は読める場所を並べる形なので、`/mnt` は開けない限り見えない。
  **Claude には同じ対処を入れていない**
- **Copilot**: `copilot_*` の許可を足す前の `/sandbox policy`（2026-09-13）では、
  `/mnt` は `/mnt/wsl/resolv.conf` だけが read-only、一時領域は `$TMPDIR` だけが
  read-write で、`/tmp` `/var/tmp` `/dev/shm` は一覧に無かった
  （[既定の許可範囲の実測](../../research/agents/copilot-sandbox-default-policy.md)）。
  このリポジトリでは `TMPDIR` をリポジトリ直下の `.tmp` に向けている。
  現在の設定（`allowDevToolAccess = false` と `copilot_*` の許可）での表示と、
  `TMPDIR` が `/tmp` のままのマシンでの扱いは**未検証**

未決の点と、決めるときの注意:

- 意図的に開けているのであれば、その旨をここに書いて確定させる
- 意図していないなら `[sandbox] deny` に `/mnt` `/tmp` `/var/tmp` `/dev/shm`
  を足す。**ただし `deny` は Copilot の `deniedPaths` にも流れる**ので、
  Claude と Copilot の両方への影響を確かめてから入れる
- `/tmp` を塞ぐと専用の空 tmpfs になり、ホストとのファイル受け渡しが切れる

#### 実測した既定の許可範囲（WSL2, chezmoi リポジトリを cwd として `/sandbox policy`）

`copilot_*` の許可を足す前の Copilot が既定で何を許すかを、`/sandbox policy` で
見たもの。表示そのものは
[既定の許可範囲の実測](../../research/agents/copilot-sandbox-default-policy.md) にある
(当時は `allowDevToolAccess = true`。現在は `false` で許可も足してあるので、
同じ表示にはならない)。
既定で許可されるのはシステム領域 (read-only)、`$TMPDIR`・cwd・セッション領域
(read-write)、`~/.copilot/logs` と skill 置き場 (read-only) だけだった。

### 参照

- [CHG-0004](../../change/closed/0004-opencode-sandbox.md)
- [調査記録 21 節](../opencode/permission/sandbox-runtime.md)
- [既定の許可範囲の実測](copilot-sandbox-default-policy.md)
