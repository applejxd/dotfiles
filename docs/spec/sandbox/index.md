# サンドボックス（総覧）

pi の実行を**何を・どこまで・何で守るか**の入口。個々の仕様は下の「文書の地図」へ。

旧来の自作の囲い（`pis`・Fence の境界・認証ブローカー・ガード）と、kcage（Incus の箱）は撤去した
（[ADR-0037](../../adr/0037-retire-custom-profile-and-other-harnesses.md)。復元はタグ `archive/custom-harness-2026-11-12`）。
今の構成は、次の 3 層。

| 層 | 役割 | 強制するもの | 正本 |
| --- | --- | --- | --- |
| 判断 | コマンドの文字列と、ファイルの道具のパスを判定する（許可・確認・拒否） | `pi-permission-system`（方針は `pi-permission-policy.json`）・`cc-safety-net`（破壊的な git・rm など） | [pi の設定の生成と所有権](../agent-config-generation.md#permission-system-の設定) |
| 実行の隔離（Linux / WSL） | pi が起動するシェルだけを bwrap の内側で動かす。見える範囲は許可リスト型で、GPU は通す | OS（bwrap） | [pi-sandbox-runner](pi-sandbox-runner.md)（`pib`） |
| 環境ごとの隔離（任意） | GPU 付きの検証用に、専用の WSL2 ディストロを作る | OS・Hyper-V の境界 | [隔離 GPU サンドボックス](wsl-sandbox.md) |

- 守る対象は、外部の文章に指示された、敵対的でないモデルの危険な操作（うっかりを含む）。悪意のあるコードやモデルは範囲外。
- **保証しないこと**: 囲いの内側で許された操作の「中身」の妥当性。認証済みの操作で何ができるかは、**外部のスコープ**（PAT・IAM・ブランチ保護）で決まる。
- pi 本体・LLM の認証・拡張・MCP は囲いの外で動く（信頼するコード）。囲いの内側から見えるもの・見えないものは [pi-sandbox-runner](pi-sandbox-runner.md#保証しないこと限界)。

## 文書の地図

- [pi-sandbox-runner](pi-sandbox-runner.md): pi の `shellPath` に差す囲い（`pib`・`pib-shell`・runner）。bwrap の引数・設定（`runner.toml`・`runner.local.toml`）・導入と確認・限界。
- [隔離 GPU サンドボックス（WSL2）](wsl-sandbox.md): 専用の WSL2 ディストロ + Docker + Tailscale SSH の作成スクリプト（`scripts/windows/wsl-sandbox/`、手動実行）。
- 経緯: [ADR-0036](../../adr/0036-pi-sandbox-shell-wrap-and-tool-policy.md)（シェルの囲いと道具の方針）・[CHG-0066](../../change/0066-pi-sandbox-boundary.md)。

[仕様一覧へ戻る](../index.md)
