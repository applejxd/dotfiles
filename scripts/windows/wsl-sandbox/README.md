# wsl-sandbox

隔離 GPU サンドボックス用の専用 WSL2 ディストロ（Ubuntu 24.04 + Docker + Tailscale SSH）を作る、**手動実行**のスクリプト。
`chezmoi apply` では実行されない。仕組み・隔離の限界・運用は [docs/spec/wsl-sandbox.md](../../../docs/spec/wsl-sandbox.md) が正本。

## 使い方

```powershell
pwsh scripts/windows/wsl-sandbox/create.ps1            # 既定: sandbox / sbx / sandbox-gpu
pwsh scripts/windows/wsl-sandbox/create.ps1 -Name sandbox2 -TailnetHostname sandbox2-gpu
```

- 前提: WSL 本体が導入済み、Windows 側の NVIDIA ドライバ、50GB 以上の空き。管理者権限は不要
- 同名のディストロがあれば中止する（削除はしない。作り直すなら手動で `wsl --unregister <Name>`）
- 途中で Tailscale のログイン URL が出るので、ブラウザで開く
- 引数の一覧は [仕様](../../../docs/spec/wsl-sandbox.md#実行方法)

## 構成

| ファイル | 役割 |
| --- | --- |
| `create.ps1` | Windows 側の司令塔。事前確認、rootfs の取得と検証、import、`wsl.conf`（隔離）、ゲスト内の導入、検証、常駐化タスク、Tailscale |
| `guest/setup.sh` | ゲスト内で root として実行。Docker・nvidia-container-toolkit・Tailscale の導入、`sbx` ユーザー、ラッパーの配置 |
| `guest/sbx-run.sh` | 制限付き `docker run` ラッパー（既定 `--network none`、docker オプションは渡せない） |
| `guest/sbx-help.sh` / `guest/sbx-AGENTS.md` | agent 向けの運用ガイド（`ssh sbx@<host> sbx-help`） |

`guest/` の `@USER@`・`@HOST@`・`@MEMORY@` は `setup.sh` が置き換える。`guest/*` は LF（`.gitattributes`）。

## 手作業が残る点

- Tailscale 管理画面で SSH ルールを `action: "accept"` にする（既定の `check` は非対話の接続が止まる）
- 操作元から `ssh sbx@sandbox-gpu docker info` で確認する

## 状態

通しの実行は**未検証**（静的な確認のみ）。実機では別名（例: `-Name sandbox2`）で試すこと。
