# pi-sandbox-toggle（ローカル）

pi のコマンド実行の囲い（`pib`）と YOLO を、セッションの途中で切り替える `/sandbox`。このリポジトリだけが配る自作で、Linux（Ubuntu / WSL）専用。

```text
/sandbox            囲いなし → 囲いあり（on）、囲いあり → 囲いなし（off）の切り替え
/sandbox on         囲いあり（通信は開いている）
/sandbox offline    囲いあり（通信を遮断）
/sandbox off        囲いなし（確認が出る）
/sandbox status     いまの状態と、囲いが実際に効いているかの確認
```

- 囲いを入れると YOLO も入り、囲いを外すと YOLO も切る。起動時にも、YOLO を囲いの状態に揃える。
- 仕組み・安全上の扱い・限界・撤去の条件は [docs/spec/sandbox/pi-sandbox-runner.md](../../../../../docs/spec/sandbox/pi-sandbox-runner.md#実行中の切り替え) と [ADR-0040](../../../../../docs/adr/0040-pi-sandbox-session-toggle.md)。
- 試験: `uv run --with pytest --no-project pytest test/test_pi_sandbox_toggle.py -q`
