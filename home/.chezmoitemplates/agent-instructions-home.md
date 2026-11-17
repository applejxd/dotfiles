# 自宅の機だけの指示

## 開発中の Web サービス

- 開発中の Web サービス（開発サーバ・ダッシュボード・API の試作など）は、Tailscale が使える機では、**tailnet の中だけに公開する**のを原則にする。使えるかは `tailscale status` が成功すること（ログアウト・停止でないこと）で確かめる。使えない機や、利用者が別の公開範囲を指示したときは、それに従う。tailnet の端末は利用者本人のものだけなので、tailnet への公開に、認証の有無や中身を理由にした事前の確認・警告は要らない（利用者の方針。2026-11-17）。
- アプリ自体は `127.0.0.1` で待ち受け、`tailscale serve --bg <ポート>` で tailnet へ出す（`--bg` は外すまで残り続ける。構文は版で違うので、実行前に `tailscale serve --help` で確かめる）。出した URL は `tailscale serve status` で確かめて、利用者に伝える。`0.0.0.0` で待ち受けると LAN にも出る。Tailscale のアドレス（`100.x`）への直接の bind は、WSL の mirrored では届かない実測がある（`docs/spec/platform-wsl.md`）ので避ける。
- WSL に `tailscale` の CLI が無い機（WSL2 の mirrored）では、Windows 側の `/mnt/c/Program Files/Tailscale/tailscale.exe` を WSL から呼ぶ（`status`・`serve` とも）。`serve` は Windows の Tailscale が受けて `127.0.0.1:<ポート>` へ転送し、mirrored のループバック共有で WSL のアプリに届く。WSL の中から自分の tailnet のアドレスへは届かない（実測）ので、公開の確認は Windows 側の `curl.exe` で行う。
- 出す前に `tailscale serve status` で既存の公開を見て、すでに使われている https のポート（443 など）を上書きしない。使われていれば `--https=8443` のように別のポートで出す。Host ヘッダを検査するアプリは、公開 URL のホスト名を許可する設定が要る。
- インターネットへ出す `tailscale funnel` は、利用者が明示したときだけ使う。
- 使い終えたら、自分が出した公開だけを外す（出したコマンドの末尾に `off` を付けて実行する）。`tailscale serve reset` は他の公開も全部消すので、`tailscale serve status` で他の公開が無いと確かめてから使う。
