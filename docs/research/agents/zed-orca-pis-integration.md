# Zed（pi-acp）・Orca から `pis` を使う方法の調査

> 現在の総合判断は [CHG-0027](../../change/0027-zed-pi-acp-with-pis.md) の候補比較表が正本。ここは「いつ何を観測したか」を積む。

## 記録 Z1 — 2026-10-20

- **対象バージョン**: pi 1.3.0、pi-acp（svkozak/pi-acp の `main`。版は未確認）、Orca 1.4.2xx（Issue の報告の版）
- **環境**: WSL2（Ubuntu）、サンドボックスの外のシェル。`~/.local/bin/pis`・`~/.local/share/ocs/pis.py`

### 結論

- **Zed（pi-acp）**: 起動コマンドは環境変数 `PI_ACP_PI_COMMAND`（README に無い）で差し替えられる。値は実行ファイル 1 つなので、`exec pis --no-sandbox "$@"` のラッパーを渡す形になる。`pis --no-sandbox --mode rpc` の RPC は手元で通った。pi-acp 本体と Zed の実機は**未実施**
- **Orca**: Settings → Agents の起動コマンド上書きで `pis` に替えられる見込み。実機は**未確認**
- どちらもサンドボックスの中では使わない。`--no-sandbox`（守りはフルガードだけ）が前提

### 問い

Zed と Orca が呼ぶ素の `pi` を、フルガード付きの `pis` に替えられるか。

### 事前の予想

pi-acp は `pi` を PATH から探すだけで差し替え口が無く、PATH の細工が要ると予想した。→ **外れ**。ソースに環境変数の差し替え口があった。

### 方法・条件と観測

#### A. 手元の RPC の試験（実測）

```sh
echo '{"id":"1","type":"get_state"}' | pis --no-sandbox --mode rpc
# → get_state の response（success:true）。先に extension_ui_request（setStatus）が 5 件出る。stderr に注意書き 1 行
(printf '{"id":"1","type":"get_state"}\n'; sleep 9) | PATH=/tmp/wrap:$PATH pi --mode rpc --no-themes
# /tmp/wrap/pi = PATH から自分を外して `exec pis --no-sandbox "$@"` を呼ぶラッパー
# → response が 1 件。sleep 4 では 0 件（起動に約 4 秒以上かかる）
```

- `--no-sandbox` の経路は `os.execvpe` で `pi` に置き換わるので、stdin / stdout は素通し。ラッパーが PATH から自分を外せば無限ループにならない

#### B. pi-acp のソースの読み（実行はしていない）

一次情報: [README](https://raw.githubusercontent.com/svkozak/pi-acp/main/README.md)、[process.ts](https://raw.githubusercontent.com/svkozak/pi-acp/main/src/pi-rpc/process.ts)、`src/acp/agent.ts`・`src/acp/session.ts`（同じ `main`）

- 起動は `pi --mode rpc --no-themes`。コマンドは `process.env.PI_ACP_PI_COMMAND`（`agent.ts`）、無ければ `pi`
- `extension_ui_request` の扱い（`session.ts`）: `confirm`・`select` は ACP の許可ダイアログ（Yes / No）、`notify` は会話へのメッセージ、`input`・`editor` は「未対応」と表示して取り消し、`setStatus` などその他は取り消しの応答を返して無視
- stdout の JSON でない行は、起動時の案内文として表示する
- フルガード（`~/.config/pi/harness/index.ts`）が使う UI は `confirm`・`notify`・`setStatus` だけ
- 別実装 [victor-software-house/pi-acp](https://github.com/victor-software-house/pi-acp) は pi を SDK で組み込み、子プロセスを起動しない。`pis` の包み方と合わない

#### C. Orca の公開情報の読み（実行はしていない）

- 起動コマンド・引数・環境変数の上書き: Settings → Agents（`agentCmdOverrides`・`agentDefaultArgs`・`agentDefaultEnv`）。[Issue #20552](https://github.com/stablyai/orca/issues/20552)
- 派生の使用例: `agentCmdOverrides.pi = "omo"` で状態表示・再開・事前入力が動く。ただし `worker-start --agent pi` の起動待ち（`agent_readiness`）が、タイトルを変える派生で 60 秒の時間切れ。[Issue #28273](https://github.com/stablyai/orca/issues/28273)（観測日 2026-10-13〜14、open）
- 状態表示の拡張 `~/.pi/agent/extensions/orca-agent-status.ts` を、pi の起動のたびに書き出す。起動の印を付けて送る。[PR #17243](https://github.com/stablyai/orca/pull/17243)
- 独自のエージェント定義は [PR #2521](https://github.com/stablyai/orca/pull/2521)（open）、`expectedProcess` は [Issue #18249](https://github.com/stablyai/orca/issues/18249) で提案中。取り込みは未確認
- このリポジトリの `pis.py` の `orca_args`: `ORCA_AGENT_HOOK_PORT` があり、印のある拡張だけを `-e` で足す。サンドボックスの中は拡張を読まず、`TOKEN` を含む環境変数も落とす（[pis の実機の挙動](pis-sandbox-field-test.md)）

### 未実施・不明

- pi-acp 本体の実行（`npx` で取得して ACP を手で送る）。Zed の実機
- Zed の `env` から `PI_ACP_PI_COMMAND` を渡して起動できるか。起動の約 4 秒以上が時間切れにならないか
- Orca の起動コマンドの上書きに引数（`--no-sandbox`）を足せるか。`pis` 経由で Orca が見るプロセス名・タイトルが変わらないか
- ローカルの `~/.orca` には `agent-hooks` しか無く、Orca の設定は読めなかった

## 記録 Z2 — 2026-10-21

- **対象バージョン**: pi 1.3.0、Orca は Windows 版（版は未確認）。Orca の文書・PR は 2026-10-21 に取得
- **環境**: Windows の Orca から、WSL のプロジェクト（`~/.local/share/chezmoi`）と Local Windows のプロジェクトを開いた（スクリーンショットの観測）

### 結論

- Orca の「構造化ネイティブチャット」（Pi Chat）は、**ローカルの macOS・Linux・ネイティブ Windows と、ペアリングした Orca Server 上のワークスペースだけ**で使える。**WSL と SSH のセッションは、ターミナル型のチャット UI のまま**
- WSL のプロジェクトで「+」を押すと、Pi は「No chat in WSL」で選べず、「Pi (CLI)」（ターミナル）だけが出る。これが「`pis` を起動したらターミナルだった」の原因
- 設定の不足ではない。Settings → チャット の「プロバイダー」で Pi はオン、Settings → Agents の Pi は Command `pis`・引数 `--no-sandbox --bypass` で有効かつデフォルトだった

### 問い

Orca で `pis` を、ターミナルではなくネイティブチャット（Pi Chat）で動かすには何が要るか。

### 方法・条件と観測

#### A. 手元の画面の観測

- Local Windows のワークツリー: 「Pi Chat」タブ（ネイティブチャット）が開いた
- WSL のワークツリー: 「Pi - chezmoi」タブ（ターミナル）。「+」メニューは「Pi: No chat in WSL」と「Pi (CLI)」
- 「チャット」設定のプロバイダー欄には、Agent 設定で無効の Agent に「Turned off in Agent settings」と出る。説明は「無効なら、入っている Agent はターミナルで開く」

#### B. 公開情報の読み

- [Chat UI (native chat) — Orca Docs](https://www.onorca.dev/docs/agents/native-chat): 上の結論の出典。構造化チャットは Claude・Codex・Grok・OpenCode・Pi・OMP・Antigravity が対象。起動は Settings → Agents に保存した Command と引数を使う
- [PR #25851](https://github.com/stablyai/orca/pull/25851)（2026-10-08 マージ）: Pi は `pi --mode rpc`（JSON Lines）で起動する。対象は `@earendil-works/pi-coding-agent` 0.84.0 以降（1.x を含む）。作成前と開始直前に、実行ホストの Pi の版を問い合わせる。バイナリは Command 設定で決まる。Pi のセッションファイルが再開の手掛かり
- [Issue #29714](https://github.com/stablyai/orca/issues/29714): ネイティブチャットの `/` メニューに Pi のスキルが出ない（Orca 側の固定の対応表に Pi が無い）
- [Issue #11327](https://github.com/stablyai/orca/issues/11327)（closed）: WSL 上の Codex の記録をネイティブチャットが読めなかった報告

### 未実施・不明

- Windows のネイティブチャットで、Command `pis`・引数 `--no-sandbox --bypass` が `--mode rpc` と版の問い合わせを通るか（Local Windows の「Pi Chat」が `pis` 経由かの確認を含む）
- WSL を Orca Server としてペアリングすれば構造化チャットになるか。`pis` のサンドボックスと両立するか
- 「WSL は対象外」が将来の版で変わるかは追っていない
