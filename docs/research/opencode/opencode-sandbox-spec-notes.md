# `ocs` 境界の仕様の補足記録（経緯・実測）

`docs/spec/sandbox/opencode-sandbox.md` の「通常起動と `ocs` の使い分け」「プロジェクトごとの追加」
（`devices`）「セッションの引き継ぎ」「エージェントとコマンド」（`OCS_ISOLATED`）「既知の制約」から
移した記録。移設時点で再測定していない。現在の仕様は
[`docs/spec/sandbox/opencode-sandbox.md`](../../spec/sandbox/opencode-sandbox.md) が正本。

## 記録 N1 — 2026-10-23（移設元の記載日。個別の観測日は各節の本文に従う）

- **対象バージョン**: Fence 0.1.67（`devices` の実測）、OpenCode 2.0.14（`tui.ts` の読み込み）
- **環境**: WSL（Ubuntu）

### 問い

`ocs` の境界の仕様に、なぜ今の形（`bypass` の許可、`devices` の許可リスト、DB の共有、`OCS_ISOLATED`）
が入ったのか。

### 結果

#### `bypass` を `ocs` で使えるようにした経緯

以前は「`ocs` では `bypass` を使わない。復旧は境界の外の通常版」と決めていた
（[CHG-0004](../../change/closed/0004-opencode-sandbox.md)。同じサーバーの中でエージェント名を変えても
OS 上の権限は分かれないため）。[ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md) で境界の目的を
うっかりの防止に絞り、`ocs` の中の `bypass` は境界から抜ける手段ではないので、
[CHG-0010](../../change/closed/0010-ocs-agents.md) で使えるようにした。復旧を通常版で行う点は変わらない。

#### `devices` の許可リストから外した名前

- **外した名前とその理由** (2026-10-23、WSL、fence 0.1.67 の実測と推測を分ける):
  - `dri`: 実測で、`{"mode":"minimal","allow":["/dev/dri"]}` はディレクトリ全体 (`card0` と `renderD128`) を見せた。
    `card0` は KMS の特権操作を含みうる (推測)。計算には不要
  - `kfd`: AMD の ROCm 用。この環境に無い (実測)
  - `nvidia-modeset`: 表示用 (推測)。CUDA の計算に要らない
  - `nvidia-caps`: MIG 用のディレクトリ (推測)。計算に要らない
  - 必要になったら、公開範囲を確かめたうえで、一覧に足す変更をする

#### `devices` の拒否の一覧方式を採らなかった判断

- **拒否の一覧方式は採らなかった** (2026-10-23 に利用者が判断)。一覧に無い未知の危険なデバイスが通ってしまうため。
  `/dev/snd`・`/dev/kvm`・`/dev/ttyS0` などの GPU 以外も、許可リストに無いので拒否する

#### 以前の隔離用 DB の移行案内

以前の `ocs` は起動ディレクトリごとの隔離用 DB（`<起動ディレクトリ>/.opencode-sandbox/`）を
使っていた。`ocs` はこれを消さない。中の古いセッションは次で開ける（`--standalone` が要る）。
これは**会話を読むためのもの**。以前の `ocs` は `XDG_DATA_HOME` も `.opencode-sandbox/data` へ
向けていて snapshot はそちらにあるので、以前の `/undo` は効かない見込み（未確認）。

```bash
OPENCODE_DB="$PWD/.opencode-sandbox/opencode.db" opencode --standalone
```

要らなければ `.opencode-sandbox/` ごと消してよい。`.opencode-sandbox/data/mise` は、
境界の内側の mise が導入済みの道具を見つけられずに入れ直したもので、消してよい。
以前の承認と合格の記録（`~/.local/state/opencode-sandbox/trusted.json`・`checked.json`）も
使われないので消してよい。

#### `OCS_ISOLATED` でモデルの説明を止めた経緯

止めたのは、以前の版では隔離起動で `tui.ts` が読まれず、作っても表示されなかった
ため。OpenCode 2.0.14 では `opencode.json` の登録からも `tui.ts` が読まれるので、モデルを呼ばない
`git commit` の件名と本文の表示は隔離起動でも出る（[`git commit` の件名と本文](../../spec/agent-config-generation.md#git-commit-の件名と本文)）。
モデルの説明を止め続けるかは見直していない

#### 起動時間の実測値

`ocs` の起動は約 0.8 秒遅い（Fence の機能の検出など）。元の記載は
「起動が約 0.8 秒遅い | Fence の機能の検出など（[実測](permission/fence.md)）」。

### 参照

- [ADR-0012](../../adr/0012-ocs-boundary-for-accidents.md)
- [CHG-0004](../../change/closed/0004-opencode-sandbox.md)
- [CHG-0010](../../change/closed/0010-ocs-agents.md)
- [Fence の実測](permission/fence.md)
- [`git commit` の件名と本文](../../spec/agent-config-generation.md#git-commit-の件名と本文)
