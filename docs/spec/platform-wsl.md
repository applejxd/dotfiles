# WSL（時刻同期・リモートからの SSH）

WSL（Windows Subsystem for Linux）に関する仕様: 時刻同期、リモートからの SSH（Tailscale）。専用の WSL2 で GPU を隔離する環境は [隔離 GPU サンドボックス](sandbox/wsl-sandbox.md)。全体の構成は [プロジェクト構造](structure.md)。

## WSL

`/etc/wsl.conf` は `100_linux/run_once_after_120_wsl.sh.tmpl` が丸ごと書き出します
（内容を変えると次の `apply` で再実行され、sudo を求めます）。既存の内容が違うときは
`/etc/wsl.conf.bak.<日時>.<乱数>` に退避して差分を表示してから書き換え、`[automount] enabled=false`
（隔離ディストロ）のときは書き換えずに警告して飛ばします。反映には Windows 側で
`wsl --shutdown` が要ります。

`[automount] mountFsTab = false` で、`/etc/fstab` の処理を WSL の init ではなく
systemd（`systemd=true`）に任せます。WSL の init は起動直後に `mount -a` を一度だけ
実行するため、Tailscale の名前など起動直後に解決できないホストへの CIFS マウントが
`Processing /etc/fstab with mount -a failed.` で失敗します。systemd は CIFS を
ネットワーク FS として扱い、ネットワークの起動後にマウントするので、同じ行が
そのままマウントされます（NAS への CIFS マウントで確認済み）。
`/etc/fstab` 自体は chezmoi では管理しません。

### WSL の時刻同期

同じ `120_wsl` が、`systemd-timesyncd` を**止めて mask** し、偏った `adjtimex` の `tick` を標準値へ戻します
（条件: systemd が動いていて、ユニットがあり、まだ mask されていない）。内容を変えたので、既存のマシンでも
次の `apply` で一度だけ実行されます。

- **理由**: Ubuntu 24.04 以前は `systemd-timesyncd` が既定で有効です。WSL は Hyper-V の時刻同期でホストと常に
  同期するため NTP クライアントは不要で、むしろ干渉して `tick` を偏らせ、`CLOCK_MONOTONIC` を約 2% 遅らせます。
  これにより、プロセスの生死を `create_time` の厳密一致で判定するアプリ（FreeVideo の常駐サービスなど）が壊れます。
  Canonical の公式文書も、Ubuntu 24.04 以前では「ホストの暗黙の時刻同期と衝突するのでこのユニットを無効にすべき」としています
  （<https://ubuntu.com/wsl/docs/latest/explanation/time-sync/>）。上流の報告とこの環境の実測は dockers リポジトリの
  `wsl2-clock-timesyncd-upstream.md` と `freevideo-install-and-generation.md` の記録 E2〜E5 を参照
- **`disable` ではなく `mask --now`**: `disable` だけでは動いているサービスは止まらず、他のユニットが起動し直すこともある。
- **`tick` を戻す理由**: `timesyncd` を止めても、すでに偏った `tick` は誰かが戻すまで残る
  （この環境の実測）。標準値は `1000000 / CLK_TCK`（通常 10000）。再起動でも元に戻る
- **対象外**: 隔離ディストロ（`[automount] enabled=false`）はこのスクリプトが早期に終わるため触らない。
  sandbox は `guest/setup.sh` が同じ設定を入れる（[時刻同期](sandbox/wsl-sandbox.md#時刻同期)）。Ubuntu 25.10 以降の新規環境は
  既定が chrony（WSL では `-x`）で `timesyncd` が無いため、条件を満たさず何もしない
- 長期の時刻のずれと、実機での適用結果の未確認事項は [記録](../research/chezmoi/structure-wsl-time-and-ssh-notes.md)

## リモートから WSL へ SSH する

**基本は Tailscale 経由で、`tailscale serve` を 1 回設定する。ファイアウォールの規則は要らない**
（規則が無い状態での確認は [記録](../research/chezmoi/structure-wsl-time-and-ssh-notes.md)）

WSL の sshd は `scripts/ubuntu/ssh.sh` が `/etc/ssh/sshd_config.d/10-override.conf` で **50022** 番にします
（Windows 自身の sshd は 22 番で、`309_admin` が管理します）。`.wslconfig` は `networkingMode=mirrored` で、
ポート転送（portproxy）は使いません。

```powershell
tailscale serve --bg --tcp 50022 tcp://localhost:50022
tailscale serve status      # 確認
tailscale serve reset       # 戻す
```

Windows の Tailscale が tailnet の 50022 を受けて、`localhost:50022`（mirrored で WSL の sshd に届く）へ
転送する。接続先は `tailscale serve status` が出す `100.x.x.x:50022` またはホスト名。

- **設定は手動で、Tailscale の状態に保存される**（再起動では消えない。Tailscale の再インストール・
  状態の初期化・`serve reset` で消える）。dotfiles には入らず、秘密も含まない。`chezmoi apply` では実行しない
- 公開範囲は tailnet 内だけ（`funnel` は使わない）。tailnet の ACL は全送信元から全ポート許可なので、
  tailnet の全機器から 50022 に届く。WSL の sshd は公開鍵のみ
- sshd のログの接続元が `127.0.0.1` になる（`serve` が localhost から接続するため）。`AllowUsers user@host` など
  接続元での制限は効かない
- 公開鍵は `400_unix/run_after_440_authorized_keys.sh.tmpl` が Bitwarden から追加する
  （[SSH 公開鍵の authorized_keys への追加](security.md#ssh-公開鍵の-authorized_keys-への追加)。`BW_SESSION` が必要）

### 手動の手順（初回・復旧後）

前提: Windows の Tailscale（ログイン済み）、`.wslconfig` が `networkingMode=mirrored`、WSL が止まっていない（下記）。

1. **WSL の sshd を 50022 にする**（WSL のターミナル。sudo のパスワードを尋ねられる）

   ```sh
   cd ~/.local/share/chezmoi
   PORT=50022 ./scripts/ubuntu/ssh.sh
   ss -ltn | grep 50022      # 0.0.0.0:50022 が LISTEN になっていること
   ```

   既定は公開鍵のみ（`PASSWORD_AUTH=no`）、`PERMIT_ROOT_LOGIN=prohibit-password`。設定は
   `/etc/ssh/sshd_config.d/10-override.conf` に書かれる。
2. **公開鍵を入れる**（WSL。Bitwarden を解除した状態で `apply`）

   ```sh
   export BW_SESSION="$(bw unlock --raw)"   # マスターパスワードが要る
   chezmoi apply
   ```

   `authorized_keys: <hostname> の鍵を追加した`（または「登録済み」）と出ればよい。
   接続元はこの鍵に対応する**秘密鍵**で接続する（[仕組み](security.md#ssh-公開鍵の-authorized_keys-への追加)）。
3. **`tailscale serve` を設定する**（Windows の PowerShell。管理者は不要）。上のコマンド。
   `tailscale` が PATH に無ければ `& 'C:\Program Files\Tailscale\tailscale.exe' serve ...`
4. **接続する**（tailnet の機器から）: `ssh -p 50022 applejxd@<Windows の Tailscale アドレス>`。
   アドレスは Windows で `tailscale ip -4`

**復旧の順番**（起動ディスクの故障などで Windows と WSL を入れ直したとき）: Tailscale を入れ直してログイン →
手順 1 → 2 → 3。`serve` の設定は Tailscale の状態に保存されるので、入れ直すと消える（**忘れやすい**）。
入れ直した機器が同じ名前・アドレスで復帰するかは未確認。

**WSL が止まっていないこと**: WSL の VM が止まっていると、`serve` が `localhost:50022` に届かず
タイムアウトする（Windows の sshd（22）は WSL と関係なく届く）。この機では `sandbox-keepalive` タスクが
実行中で VM を常駐させている（`Ubuntu` と `sandbox` が 1 つの VM を共有する）。`sandbox` を削除する、または
タスクを止めると止まる可能性がある（`.wslconfig` に `vmIdleTimeout` の指定は無い。止まったときの挙動は未実測）。

### 接続できないときの切り分け

| 症状（接続元のエラー） | 主な原因 | 確認 |
| --- | --- | --- |
| `connection timed out` | `tailscale serve` が無い、または WSL が止まっている | Windows で `tailscale serve status`、`wsl.exe -l -v` で `Running` か。Windows の sshd（22）に届くか（届くなら tailnet は正常） |
| `Connection refused` | WSL の sshd が 50022 で待ち受けていない | WSL で `ss -ltn \| grep 50022`、`systemctl is-active ssh` |
| `Permission denied (publickey)` | 到達している。鍵が合わない | 手順 2 を実行。接続元が、`authorized_keys` に入った鍵の秘密鍵を使っているか |

### なぜ規則ではなく `serve` か

mirrored では、Tailscale のアドレス（`100.x`）への 50022 が WSL の VM に転送されない。そのため、規則ではなく `tailscale serve` を使う。
Windows 自身の sshd（22）はホストで受けるので Tailscale 経由でも届く。確認した層ごとの結果と実測は [記録](../research/chezmoi/structure-wsl-time-and-ssh-notes.md)。

### LAN の IP を直接指定する場合

LAN の IP（`<LAN の IP>:50022`）を直接指定する接続は、ファイアウォールの規則が要る可能性が高い
（Tailscale は同じ LAN 内では直接接続するので、通常は不要）。2 つの層（Hyper-V ファイアウォールの規則と、
標準の Windows ファイアウォールの規則）のどちらが単独で必要かは**未確定**。
実験の経過は [記録](../research/chezmoi/structure-wsl-time-and-ssh-notes.md)。
必要になったら、規則を **別々の名前**で作ること（同じ名前だと片方だけの操作ができない）。

```powershell
# 管理者の PowerShell。Domain / Private だけ (Public では開けない)
New-NetFirewallHyperVRule -Name WSL-SSH-In-TCP-HyperV -DisplayName 'OpenSSH Server (WSL)' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPorts 50022 `
    -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Profiles Domain, Private -Enabled True
New-NetFirewallRule -Name WSL-SSH-In-TCP -DisplayName 'OpenSSH Server (WSL)' -Enabled True `
    -Direction Inbound -Protocol TCP -Action Allow -LocalPort 50022 -Profile Domain, Private
```

WSL の VM の作成者 ID は `Get-NetFirewallHyperVVMCreator` で確認できる。LAN 経由（両方の規則を作った状態）で
接続できたことは確認済み。
