# agent-permissions の実測・根拠の記録

> `docs/spec/agent-permissions.md#windows-での扱い` と `#保存した承認の確認とリセット` から移した記録。移設時点で再測定していない。
> 現行の仕様は [AI CLI 統合 permission / hook 管理](../../spec/agent-permissions.md)。

## 記録 P1 — 2026-09-27 Windows native での確認の範囲

- **対象**: Claude Code / Copilot CLI / OpenCode（Windows native）
- **観測日**: 2026-09-27

### 問い

Windows native で、AI CLI の OS レベルの保護は実機で確かめられているか。

### 結果

**Windows 11 の実機では確かめていない**（2026-09-27 時点。GitHub Actions の
Windows Server でテストを回したのと、上流のソース・公式資料を読んだのが根拠）。

## 記録 P2 — 2026-09-29 `oc-utils approvals reset --yes --standalone` の所要時間

- **対象バージョン**: OpenCode v2.0.14
- **観測日**: 2026-09-29

### 問い

`--standalone`（`OPENCODE_DB` を複製へ向けた試験用）の `reset` はどれくらい遅いか。

### 結果

呼び出しのたびにサーバーを立てるため遅い。80 件の `reset --yes` で約 90 秒（2026-09-29、v2.0.14）。
