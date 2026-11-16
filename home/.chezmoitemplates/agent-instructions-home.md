# 自宅の機だけの指示

## 開発中の Web サービス

- 開発中の Web サービス（開発サーバ・ダッシュボード・API の試作など）は、Tailscale が使える機では、**tailnet の中だけに公開する**のを原則にする。使えるかは `tailscale status` が成功すること（ログアウト・停止でないこと）で確かめる。使えない機や、利用者が別の公開範囲を指示したときは、それに従う。
- アプリ自体は `127.0.0.1` で待ち受け、`tailscale serve --bg <ポート>` で tailnet へ出す（`--bg` は外すまで残り続ける。構文は版で違うので、実行前に `tailscale serve --help` で確かめる）。出した URL は `tailscale serve status` で確かめて、利用者に伝える。`0.0.0.0` で待ち受けると LAN にも出る。Tailscale のアドレス（`100.x`）への直接の bind は、WSL の mirrored では届かない実測がある（`docs/spec/platform-wsl.md`）ので避ける。
- インターネットへ出す `tailscale funnel` は、利用者が明示したときだけ使う。tailnet の全端末から見える前提で、認証の無い管理画面や、秘密を返す API は、出す前に利用者へ伝える。
- 使い終えたら、自分が出した公開だけを外す（出したコマンドの末尾に `off` を付けて実行する）。`tailscale serve reset` は他の公開も全部消すので、`tailscale serve status` で他の公開が無いと確かめてから使う。
