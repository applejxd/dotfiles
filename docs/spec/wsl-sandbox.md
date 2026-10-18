# 隔離 GPU サンドボックス（専用 WSL2 ディストロ）

NVIDIA GPU を使った AI OSS の動作確認を、Windows 上の専用 WSL2 ディストロで隔離して行う。
ディストロの中だけに Docker Engine と nvidia-container-toolkit を入れ、Tailscale SSH で別マシン
（Raspberry Pi など）から操作する。Windows 側の sshd・ファイアウォール・portproxy・Docker Desktop・
他の WSL ディストロには触れない。

## 実行方法

**手動で実行する。** `chezmoi apply` では走らない（`home/` の外の `scripts/windows/` にあるため）。

```powershell
pwsh scripts/windows/wsl-sandbox/create.ps1
```

| 引数 | 既定 | 内容 |
| --- | --- | --- |
| `-Name` | `sandbox` | ディストロ名（英数字・`_`・`-` のみ。引数は PowerShell・タスク・`sed` へそのまま渡るため検証する） |
| `-User` | `sbx` | 作業ユーザー（パスワードなし、docker グループ） |
| `-TailnetHostname` | `sandbox-gpu` | tailnet 上のホスト名 |
| `-InstallDir` | `~\wsl\<Name>` | 仮想ディスクの置き場所 |
| `-Memory` | `.wslconfig` の `memory` の約 7 割（無ければ搭載 RAM の約 35%） | コンテナのメモリ上限 |
| `-CudaImage` | `nvidia/cuda:12.4.1-base-ubuntu22.04` | 検証に使う CUDA イメージ（ドライバが対応する新しいものに変えてよい） |
| `-Update` | 無効 | 先に `wsl --update` を実行する |
| `-SkipTailscale` | 無効 | Tailscale の導入とログインを省く |
| `-NoKeepalive` | 無効 | VM 常駐化のタスクを作らない |

前提: WSL 本体が導入済み（[WslPlatform](structure.md#wsl-本体wslplatform)）、Windows 側の NVIDIA ドライバ、
`~` のドライブに 50GB 以上の空き。管理者権限は要らない。

## 手順の中身

1. **事前確認**: `wsl --version`、`nvidia-smi`、同名ディストロの有無（あれば中止。**削除はしない**。作り直すなら手動で `wsl --unregister`）、空き容量
2. **rootfs**: `https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz` を取得し、`SHA256SUMS` で検証して `wsl --import`。
   `wsl/noble/current/` は 404 になる
3. **隔離**: `/etc/wsl.conf` に `systemd=true`、`[automount] enabled=false`、`[interop] enabled=false`、`appendWindowsPath=false` を書き、`wsl --terminate` で反映
4. **ゲスト内**（`guest/setup.sh`）: Docker 公式 apt から docker-ce 一式、NVIDIA 公式 apt から nvidia-container-toolkit、Tailscale 公式 apt から tailscale。
   `nvidia-ctk runtime configure --runtime=docker`、`sbx` を docker グループへ、`/usr/local/bin/sbx-run`・`sbx-help`・`/home/sbx/AGENTS.md` を配置
5. **検証**: `/mnt/c` が無いか空、`cmd.exe` が失敗（interop 無効）、`sbx-run` でコンテナから GPU が見える、既定でネットワークが無い（I/F が `lo` だけ）、`--privileged` を拒否
6. **常駐化**: スケジュールタスク `<Name>-keepalive`（ログオン時に `conhost.exe --headless wsl.exe -d <Name> -u root -- sleep infinity`）
7. **Tailscale**: `tailscale up --hostname=...`（表示された URL をブラウザで開いてログイン）と `tailscale set --ssh`

ファイルは `scripts/windows/wsl-sandbox/` にある。ゲスト用は `guest/` で、`@USER@`・`@HOST@`・`@MEMORY@` を `setup.sh` が置き換えて配置する。
ファイルは `\wsl.localhost\<Name>` 経由でゲストへ渡す（automount を切っていても使える）。`guest/*` は LF（`.gitattributes`）。

## 手作業が残る点

- **Tailscale ACL の SSH ルール**: 管理画面（<https://login.tailscale.com/admin/acls/file>）で変える。agent は API キーやトークンを扱わない。
  既定の `action: "check"` は初回と 12 時間ごとに認証 URL の承認が要り、非対話の接続（agent、自動化）が止まる。

  ```json
  "ssh": [
    { "action": "accept", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["sbx"] }
  ]
  ```

  共有ユーザーがいる tailnet では `src` を絞る（タグの利用）。
- 確認: 操作元から `ssh sbx@sandbox-gpu docker info` が認証 URL なしで通る。
- agent への案内: 「`ssh sbx@sandbox-gpu sbx-help` を読んで、その指示に従って使う」

## 隔離の強さと限界

- `.wslconfig` は `home/dot_wslconfig.tmpl` が `networkingMode=mirrored` で配る。mirrored は**全ディストロが 1 つの VM を共有し、
  ホストの NIC とループバックを共有する**。sandbox の `localhost` はホストのループバックと同じで、ホストの sshd（22 番）にも届く。
- `networkingMode` は VM 全体の設定で、sandbox だけ変えられない。NAT にしてもコンテナの外向き通信は防げない（防ぐのは主にホストのループバックへの到達）。
  当面は mirrored を維持し、隔離は `sbx-run` の既定 `--network none` で補う。
- `sbx` は docker グループなので事実上 root と同等。`sbx-run` は付け忘れを防ぐ仕組みで、強制ではない。
- 隔離ディストロの中で `chezmoi apply` を実行しない。`100_linux/run_once_after_120_wsl.sh.tmpl` は `[automount] enabled=false` を見つけると
  `/etc/wsl.conf` の書き換えを飛ばして警告するが、ほかのスクリプトも走るので、引き続き実行しない。
- `.wslconfig` の `vmIdleTimeout` は全ディストロの VM に効くので、常駐化には使わない。

## 運用上の注意

- keepalive が無いと、セッションが無いときに VM ごと停止して tailnet からオフラインになる。
  `wsl.exe` を直接起動するとコンソールが出る。`powershell.exe -WindowStyle Hidden` 経由でも、既定ターミナルが Windows Terminal だとタブが出て、閉じると止まる。
  このためタスクは `conhost.exe --headless` を使う。ウィンドウを閉じたり `wsl.exe` を終了したりしても止まる。
- SSH が `Connecting to ... port 22.` で止まるときは、(a) VM が停止している（keepalive が動いていない）、
  (b) Tailscale SSH の check モードの承認待ち、のどちらかが多い。
- `sbx-run --net=none` ではイメージ・モデルを取得できない。先に `--net=bridge` で取得する。
- メモリ上限は搭載 RAM ではなく WSL VM の上限（`.wslconfig` の `memory`）を基準にする。
- Windows 側のラッパー `~\wsl\<Name>-run.ps1` は `sbx-run` を呼ぶ（制限を 1 か所に置くため）。ポート公開（`-p`）は渡さない。
- 元に戻す: `Unregister-ScheduledTask -TaskName <Name>-keepalive -Confirm:$false`。
  Tailscale のみ外すなら ゲスト内で `tailscale logout`・`apt-get purge tailscale`、管理画面でノードを削除。
  全部戻すなら `wsl --unregister <Name>`（仮想ディスクごと削除）と `~\wsl\` 以下の rootfs・ラッパー。

## 検証の状況

- 手順は 2026-10-17 に手作業で構築して確かめた（RTX 3070、ドライバ 610.88、Docker 29.9.1、nvidia-container-toolkit 1.20.1、Tailscale 1.104.1。
  Raspberry Pi からの `ssh sbx@sandbox-gpu docker info` を含む）。
- **`create.ps1` としてまとめたものは、静的な確認（PowerShell 5.1 / 7 の構文、`shellcheck`、`sbx-run` の引数拒否）だけで、通しの実行は未検証。**
  実機で新しい名前（例: `-Name sandbox2`）を使って通しで確かめること。確かめるまでは次が未確認:
  `\wsl.localhost` 経由の書き込み、`systemctl is-system-running --wait` の待ち、通常権限でのスケジュールタスク登録。

## 位置づけ

`create.ps1` は Tailscale のログインでブラウザを開く操作を待つ（標準入力の対話ではない）。
AGENTS.md の「対話入力が必須なスクリプトや長時間実行スクリプトは追加しない」は `chezmoi apply` で自動実行するスクリプトの約束で、
手動実行の `scripts/windows/` にあるこのスクリプトは対象外とする。CHG-0022 の保留（既定ディストロと置き場所の方針）は別件のまま。

## 途中で失敗したとき

- `wsl --import` のあとに失敗すると、次の実行は「同名ディストロあり」で中止する（意図。削除はしない）。
  ゲスト内に残したいデータが無ければ `wsl --unregister <Name>` で消して最初からやり直す。
  Docker などの導入でネットワークが落ちただけなら、ディストロを残したまま
  `wsl -d <Name> -u root -- bash /tmp/wsl-sandbox/setup.sh ...` を手で再実行してもよい（`setup.sh` は再実行を想定した書き方だが未検証）。
  `setup.sh` を単体で再実行しても、`-SkipTailscale` で省いた Tailscale は入らず、入れ済みのものは無効化もされない。
- Tailscale のログインで止まったときは、`wsl -d <Name> -u root -- tailscale up --hostname=<ホスト名>` と `tailscale set --ssh` を手で実行する。
- keepalive はログオン時に起動するので、**ログオン前（再起動直後など）はリモートから入れない。**
  常駐化の確認は、タスクが `Running` かどうかまで。60 秒後も `wsl -l -v` で Running のままかは、手で確かめる。
- 一時ファイル（`<Name>` の `/tmp/wsl-sandbox`）は成功すると消す。失敗時は残る。
