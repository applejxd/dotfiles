# WSL の時刻同期と SSH の実測メモ

> `docs/spec/structure.md` の次の節から移した記録。移設時点で再測定していない。現在の仕様は各節（下記）を参照。

- **観測日**: 2026-10-18 ほか（各節の本文の日付が正）
- **問い**: WSL の時刻同期の未確認事項と、Tailscale 経由で WSL へ SSH するときの確認の記録
- **根拠**: 各節の本文（元の文のまま。URL・コマンドを含む）

## WSL の時刻同期の未確認事項

元の節: `docs/spec/structure.md` の「WSL の時刻同期」

- **未確認**: `timesyncd` を止めた状態で、壁時計の絶対的なずれが長期（数時間〜数日）で許容範囲に収まるか。
  Canonical の説明（Hyper-V の同期でよい）に頼るが、この環境では測り続けていない。
  このスクリプトを実機で `chezmoi apply` した結果（mask と `tick` の復元）と、再起動後の動作も未確認
  （スクリプトは描画・構文・shellcheck まで確かめた）

## 規則が無い状態で Tailscale 経由の SSH が通った確認

元の節: `docs/spec/structure.md` の「リモートから WSL へ SSH する」

（2026-10-18 に、規則が 1 つも無い状態で iPhone の Termius から Tailscale 経由の SSH が通ることを確認）。

## なぜ規則ではなく `serve` か（確認した層の実測）

元の節: `docs/spec/structure.md` の「なぜ規則ではなく serve か」

mirrored では、**Tailscale のアドレス（`100.x`）への 50022 が WSL の VM に転送されない**（2026-10-18、この機）。
Tailscale の仮想アダプター（Wintun）経由のパケットは、Windows のホストのネットワークスタックで受け取られ、
VM へは転送されない（実測からの推定。Microsoft のドキュメントでの裏付けは未確認）。Windows 自身の sshd（22）は
ホストで受けるので Tailscale 経由でも届く。

| 確認した層 | 結果 |
| --- | --- |
| tailnet の ACL（Tailscale の受信フィルタ） | 全送信元から全ポート許可。原因ではない |
| Hyper-V ファイアウォール（WSL の VM 向け。既定は受信 Block） | 規則を作っても、**無効にしても**届かない |
| 標準の Windows ファイアウォール | 規則あり（`Tailscale-In` は全許可）。届かない |
| WSL の VM の `eth2`（Tailscale）の受信パケット数 | 接続を試した間も増えない。パケットが VM に届いていない |
| `tailscale serve` を設定（規則なし） | **届く** |

## LAN の IP を直接指定する場合の実験

元の節: `docs/spec/structure.md` の「LAN の IP を直接指定する場合」

2026-10-18 に「標準の規則を消すと LAN から届かなくなった」と記録したが、2 つの規則を同じ名前にしていて
`Remove-NetFirewallRule -Name` が Hyper-V の規則も消した可能性があり、単独の必要性を示す実験になっていない。
