# AI CLI の実行時の障害の観測記録（ツール呼び出しの引数破損の頻度、pis のクリップボード）

`docs/spec/troubleshooting-agents.md#ツール呼び出しの引数が壊れるinvalid-arguments引数が空` と
`docs/spec/troubleshooting-agents.md#pis-の内側でクリップボードへコピーできない` から移した記録。
移設時点で再測定していない。現在の対処は各節を参照する。

> **現行の仕様**: 症状と対処は [AI CLI の実行時のトラブルシューティング](../../spec/troubleshooting-agents.md)。

## 記録 E1 — 2026-10-18（ツール呼び出しの引数破損）

- **対象バージョン**: pi、モデルは `claude-sonnet-5.5`
- **環境**: この機（個人の機）の全セッション

### 問い

`Invalid arguments for tool "guarded_edit": Expected ':' after property name in JSON at position N` で失敗する
呼び出しは、どのくらいの頻度で起き、何が原因か。

### 事前の予想

探索的で予想は無い。

### 方法・条件

セッション記録で失敗を数えた。

```sh
grep -rhoE 'argumentsError": ?"[^\\]*' ~/.pi/agent/sessions | cut -c1-110 | sort | uniq -c
```

### 結果

実測では、`"oldText"` の直後に `:` ではなく `>` が出て、本文も途中で欠けていた。
pi が `argumentsError` として検出し、モデルへ不正な引数と返す。ツールやガードが壊したものではない。

**頻度**（2026-10-18、この機の全セッション）: ツール呼び出し約 2,600 回中 1 回（`guarded_edit` は 211 回中 1 回）。
直後の送り直しで成功した。子のエージェント（`guarded_task`）は `--no-session` で記録が残らないので、
子の失敗率は未測定。

### 考察

モデルが引数の JSON を生成する途中で壊れた出力をした。他のマシンで「引数が空のツール呼び出し」を
見た記憶があるが、同じ現象と推測している（未確認）。

### 次の問い

子のエージェントの失敗率（未測定）。

### 参照

なし（手元のセッション記録）。

## 記録 E2 — 2026-10-25（pis の内側のクリップボード）

- **対象バージョン**: pi 本体 1.3.0（`dist/utils/clipboard.js`）
- **環境**: WSL2（WSLg）、Orca のターミナルから `pis` を使う構成

### 問い

`pis` の内側で `/copy` や選択コピーが `Clipboard unavailable: install \`wl-clipboard\` (\`wl-copy\`) or check Wayland access` で失敗する。原因と上流の見解は何か。

### 事前の予想

探索的で予想は無い。

### 方法・条件

`pis` の外のシェルで、端末が OSC 52（端末へクリップボードを書かせるエスケープ列）に対応しているかを見た。

```bash
printf '\033]52;c;%s\a' "$(printf hello | base64)"
```

### 結果

その後に貼り付けて `hello` が出れば、端末は対応している。2026-10-25 に Orca で確認した。

上流の見解（pi Issue #10558、2026-10-07 に not a bug で close）は「表示の変数が出ているなら、動くソケットを
用意するか、変数を unset する」。同じ症状の回避策として、メンテナは `PI_CLIPBOARD_OSC52=1` を挙げている
（Issue #11273）。

tmux 内で使うなら、別の問題がある。tmux は既定で OSC 52 を転送しない（pi Issue #10628、open。
`set -g set-clipboard on` / `allow-passthrough` が要る）。`WT_SESSION` の継承で無言の失敗になる
報告もある（Issue #11029、2026-10-16 close。`env -u WT_SESSION` が回避策）。

Orca の設定: `Settings → Terminal → Allow TUI Clipboard Writes (OSC 52)`
（<https://www.onorca.dev/docs/terminal、日付未確認>）

### 考察

sandbox がそれらのソケットと、`powershell.exe` の相互運用を塞ぐ（推測。内側では未実測）。

### 次の問い

sandbox の内側での実測。

### 参照

- pi Issue #10558、#11273、#10628、#11029
