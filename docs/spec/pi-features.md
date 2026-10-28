# pi の機能の地図

`pi`（このリポジトリが配るフルガード付きの pi）の機能は、**3 本の柱**と**基本機能**に分けて読む。文書の置き場は歴史的な経緯で、`docs/spec/guard/` に子エージェントや拡張の文書も入っている。
**この地図が入口**で、各柱から正本へリンクする（文書は動かさない）。

| 柱 | 守る・実現すること | 入口 |
| --- | --- | --- |
| **ガード** | 誤操作・意図しない外部送信・秘密の表示を、判定器で止める（allow / ask / confirm / deny）。承認と保留 | [ガード（総覧）](guard/index.md) |
| **サンドボックス** | OS の境界で、書き込み・読み取り・ネットワーク・認証情報を狭める（`pis`）。ガードが破られても残る層 | [サンドボックス（総覧）](sandbox/index.md) |
| **オーケストレーション** | 親が子と feature ブランチで、作業を分けて並列に進める | [オーケストレーションと並列作業の機能一覧](orchestration.md) |
| **基本機能** | 上の 3 つに属さない、pi の日常の機能（スキル・MCP・モデル・圧縮・一時置き場・拡張・コマンド） | 下の表 |

## ガード

| 機能 | 正本 |
| --- | --- |
| 判定器（`decide`）と評価の順番、役割（`implementer`・`worker`・`explorer` など） | [判定 API](guard/pi-decide.md) |
| 保証の範囲（境界ではなく「うっかり防止」）、4 つの結果 | [ガード（総覧）](guard/index.md) |
| bypass、bypass でも確認する操作（`mustConfirm`）、元に戻せない git 操作 | [判定 API](guard/pi-decide.md#confirm)、[pi のガード](guard/pi-guard.md) |
| `guarded_action`（`git commit`・`gh` の書き込みを、固定の引数と確認つきで） | [pi の拡張と補助機能](guard/pi-extensions.md#guarded_action承認つきの外部操作) |
| 承認の時間切れの退避（`/pending`） | [CHG-0046](../change/0046-guarded-action-timeout.md) |
| コマンド・ファイルの判定の規則 | [コマンド・ファイルの判定](guard/agent-command-policy.md) |
| 誘導・出力の伏字化 | [判定 API](guard/pi-decide.md#誘導)、[pi のガード](guard/pi-guard.md) |
| Claude Code / Copilot / OpenCode の権限 | [エージェント権限仕様](agent-permissions.md) |

## サンドボックス

| 機能 | 正本 |
| --- | --- |
| `pis`（Fence の境界で起動。境界の組み立て） | [Fence 境界の組み立て](sandbox/fence-boundary.md)、[pis のサンドボックス（pi の側）](guard/pi-sandbox.md) |
| 認証ブローカー（長期の認証情報を内側へ渡さない） | [認証ブローカー](sandbox/broker.md) |
| ネットワークの層・ローカルの許可 | [ネットワーク層](sandbox/cli-sandbox-network.md)、[ローカルの許可](sandbox/cli-sandbox-local-allow.md) |
| Claude Code / Copilot / OpenCode の sandbox | [sandbox](sandbox/agent-sandbox.md)、[Copilot](sandbox/copilot-sandbox.md)、[OpenCode](sandbox/opencode-sandbox.md) |
| 隔離 GPU サンドボックス（WSL2） | [隔離 GPU サンドボックス](sandbox/wsl-sandbox.md) |
| 子の隔離（`isolation: "worktree"`。Landlock） | オーケストレーションの機能でもある。素の `pi` では保留。[CHG-0029](../change/0029-worktree-isolation.md) |

## オーケストレーション

[機能一覧](orchestration.md)。子エージェント（`guarded_task`）・役割と権限・gitflow と worktree・並列実装の運用・検査・記録。

## 基本機能

| 機能 | 正本 |
| --- | --- |
| スキル（`SKILL.md` の方針、Web 検索、調べもの） | [スキルの frontmatter](skill-frontmatter.md)、[Web 検索](web-search.md)、[imozuru](imozuru.md) |
| MCP サーバ（`[[mcp]]` から各 CLI の形式へ生成、AgentCore Web Search） | [MCP サーバの設定](mcp-servers.md) |
| モデルの割り当て（プロバイダ・階層・子のカタログ） | [モデルの割り当て](agent-model-assignment.md) |
| 圧縮と文脈の引き継ぎ（`checkpoint`） | [圧縮](guard/pi-extensions.md#圧縮旧-checkpoint)、[文脈の引き継ぎ](checkpoint.md) |
| セッションごとの一時置き場（`.tmp/s/<ID>/`） | [一時置き場](guard/pi-extensions.md#セッションごとの一時置き場tmpsid) |
| 自作の拡張（`todo`・`plan`・`btw`・`ask`・`activity`・`notify`・`delegate-nudge`） | [自作の拡張](guard/pi-extensions.md#自作の拡張-todo--plan--btw) |
| 利用者コマンド（`/bypass`・`/plan`・`/pending`・`/agents`・`/fleet` など）、キーバインド | [pi の拡張と補助機能](guard/pi-extensions.md)、[pi のガード](guard/pi-guard.md) |
| 設定の生成（`common.toml` が単一ソース） | [設定の生成と所有権](agent-config-generation.md) |
| pi 本体の公式仕様と実測 | [pi の公式仕様と実測の棚卸し](pi-upstream.md) |

## 柱をまたぐ機能の置き場

1 つの機能は、**主な柱に 1 回だけ**載せ、ほかの柱からはリンクにとどめる。

| 機能 | 主な柱 | 理由 |
| --- | --- | --- |
| 承認の時間切れの退避・`/pending`・`/bypass` | ガード | 判定と承認の仕組み |
| 子の隔離（Landlock） | オーケストレーション（サンドボックスへリンク） | 子の起動の機能で、仕組みが OS の境界 |
| gitflow・feature の worktree | オーケストレーション | 並列実装の作業場所の分離 |
| 子への bypass の継承・既定が deny の役割 | ガード（オーケストレーションへリンク） | 判定器の規則 |
| `pis` の境界で子が止まらない条件 | サンドボックス（オーケストレーションへリンク） | 境界の証明が前提 |
