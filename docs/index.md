# 現在地とドキュメント

目的: Windows / Ubuntu / WSL / macOS の dotfiles を chezmoi で管理し、
AI CLI の権限・hook・スキルを単一ソースから生成する。

導入手順はリポジトリ直下の [README](../README.md) を参照。
文書で使う用語は [用語集](spec/glossary.md) にそろえてある。

## 目的から探す

### 導入・日常の運用

| 目的 | 文書 |
| --- | --- |
| リポジトリ全体の構成を知る | [プロジェクト構造](spec/structure.md) |
| chezmoi スクリプトが作るキャッシュ・状態ファイルを知る | [スクリプトが作るキャッシュ・状態](spec/script-artifacts.md) |
| Raspberry Pi へ導入する | [Raspberry Pi](spec/platform-raspberry-pi.md#raspberry-pi) |
| Raspberry Pi に入った GUI 一式を消す | [入ってしまった GUI 一式を消す](spec/platform-raspberry-pi.md#入ってしまった-gui-一式を消す) |
| Herdr を mise で導入・更新する | [Herdr の管理](spec/cli-management.md#herdr-の管理) |
| GitHub CLI を mise で導入・更新する | [mise による CLI 管理](spec/cli-management.md#mise-による-cli-管理) |
| Claude Code / Copilot CLI / OpenCode を導入・更新する | [AI CLI の導入](spec/cli-management.md#ai-cli-の導入) |
| シェルの起動ファイルに何を置いてよいか知る | [シェルの起動契約](spec/shell.md#シェルの起動契約) |
| マシンごとに違う設定（データセットの置き場など）を置く | [マシン固有の設定の置き場](spec/shell.md#マシン固有の設定の置き場) |
| C++ の 1 ファイルを debug / release で実行する（`runcpp`） | [C++ の単一ファイル実行](spec/dev-environment.md#c-の単一ファイル実行runcpp) |
| zsh プラグインの遅延読み込みの順序を変える | [zinit の遅延読み込みの順序](spec/shell.md#zinit-の遅延読み込みの順序) |
| oh-my-pi（omp）を使う | [oh-my-pi の設定](spec/cli-management.md#oh-my-piompの設定) |
| sops + age を導入・復旧する | [秘密情報の管理セットアップ（sops + age）](spec/sops-age.md) |
| 圧縮を跨いで作業文脈を保つ仕組みを知る | [文脈の引き継ぎ](spec/checkpoint.md) |
| エラーを切り分ける | [トラブルシューティング](spec/troubleshooting.md) |
| 入れてある一時対処と、その撤去の条件を知る | [一時対処の一覧](spec/temporary-workarounds.md) |
| WSL にリモートから SSH する（Tailscale） | [リモートから WSL へ SSH する](spec/platform-wsl.md#リモートから-wsl-へ-ssh-する) |
| `run_once_` / `run_onchange_` を走らせ直す | [スクリプトを走らせ直す](spec/troubleshooting-bootstrap.md#スクリプトを走らせ直す) |

### 設定の変更・検証

| 目的 | 文書 |
| --- | --- |
| 開発環境を準備して検証する | [開発ガイド](spec/development.md) |
| テストの種類と Docker ハーネスの契約を知る | [テストと検証の仕組み](spec/testing.md) |
| Windows 資産を実機で検証する | [Windows 実機での検証](spec/development.md#windows-実機での検証) |
| まっさらな Windows への導入を Sandbox で検証する | [Windows Sandbox での検証](spec/development.md#windows-sandbox-でのクリーン導入の検証) |
| 隔離 GPU サンドボックス（専用 WSL2 + Docker + Tailscale SSH）を作る | [隔離 GPU サンドボックス](spec/sandbox/wsl-sandbox.md) |
| 判定器の TS 移植の進み具合と、次にやることを知る | [TS 版への移植](spec/guard/pi-decide.md#ts-版への移植)（決定は [ADR-0017](adr/0017-pi-only-and-ts-judge.md)） |
| 新しい機械での初回導入を Docker で検証する | [Docker での検証](spec/development.md#新しい機械での初回導入を-docker-で検証する) |
| AI CLI の permission / hook を変更する | [エージェント権限仕様](spec/agent-permissions.md) |
| pi のガードの判定器（`decide`）を変える | [判定 API](spec/guard/pi-decide.md) |
| pi / pis の機能・設定の変え方・独自コマンドを見直す（忘れたときの早見） | [pi / pis マニュアル](spec/pi-manual.md) |
| pi 単独と PR ビューア併用の、運用の違い・手順・旗の使い分けを知る | [運用モード](spec/operation-modes.md) |
| pi のガード（`pis`）を起動する・変える | [pi のガード](spec/guard/pi-guard.md) |
| gitflow-lite の運用（起票は親、AI は feature の worktree から `git_commit`、統合は利用者がビューアで押す）を知る | [開発ガイドのブランチモデル](spec/development.md#ブランチモデルgitflow-lite) |
| `common.toml` の書き方と生成先の所有権を知る | [設定の生成と所有権](spec/agent-config-generation.md) |
| コマンド・ファイルの allow / ask / deny を変える | [コマンド・ファイルの判定](spec/guard/agent-command-policy.md) |
| MCP サーバを追加・変更する | [MCP サーバ](spec/mcp-servers.md#mcp-サーバ) |
| Bedrock の PC で web 検索を使えるようにする（AgentCore Web Search） | [AgentCore Web Search](spec/mcp-servers.md#agentcore-web-search) |
| 調べものスキル（imozuru）を使う・変える・上流を更新する | [imozuru](spec/imozuru.md) |
| OpenCode のモデル・プロバイダ（Copilot / Bedrock）を PC ごとに変える | [モデルの割り当て](spec/agent-model-assignment.md#モデルの割り当て) |
| 新しいモデルが出たときに OpenCode のモデルの割り当てを見直す | [モデルの割り当ての見直し](spec/model-lineup-review.md) |
| OpenCode で作業を並列に進める（`/fleet`） | [並列作業](spec/opencode-config-generation.md#並列作業fleet) |
| OpenCode のプラグインを検討する | [プラグイン生態系の棚卸し](research/opencode/plugin/ecosystem.md) |

### 安全性

| 目的 | 文書 |
| --- | --- |
| 何を守り、なぜ Bitwarden / sops なのかを知る | [セキュリティ](spec/security.md) |
| Claude Code / Copilot CLI の sandbox で読めない・書けない | [sandbox (Claude Code / Copilot CLI)](spec/sandbox/agent-sandbox.md) |
| OpenCode の権限がなぜ他と違うか知る | [OpenCode V2 の扱い](spec/agent-permissions.md#opencode-v2-の扱い) |
| OpenCode の「常に許可」で保存した承認を確認・リセットする（`oc-utils`） | [保存した承認の確認とリセット](spec/agent-permissions.md#保存した承認の確認とリセット) |
| OpenCode を境界の内側で起動する仕組み（隔離起動 `ocs`）を知る | [OpenCode 隔離起動のアーキテクチャ](spec/sandbox/opencode-sandbox.md) |
| 隔離起動の境界内で読めない・書けない原因を調べる | [境界の組み立ての規則](spec/sandbox/fence-boundary.md#組み立ての規則) |
| sandbox で何ができるか調べる | [sandbox機能の包括調査](research/agents/sandbox-capabilities.md) |
| 確認（承認）と封じ込めの設計方針を知る・変える（ask 層と bypass モードの廃止、非同期の承認、複数エージェントの束ね） | [ADR-0022](adr/0022-containment-first-minimal-approvals.md)、[CHG-0054](change/0054-containment-and-async-approval.md)、[調査記録 AC1](research/agents/approval-containment-survey.md) |
| 確認が取れない操作の保留と、利用者が後から承認して実行する仕組み（非同期の承認。**撤去済み**。統合は PR ビューアの押下へ）を知る | [ADR-0024](adr/0024-human-press-merges-in-app.md)、[ADR-0023](adr/0023-pending-approval.md)（Superseded）、[CHG-0055](change/closed/0055-async-approval.md) |
| 並列実装の配車・関門・承認パケット・標的レビュー（利用者が本質的な承認に集中する自動化）を知る・変える | [CHG-0056](change/0056-orchestrator.md) |
| 保留の承認を、巡回・一括で少ない操作にする設計（見送り・撤去済み）を知る | [CHG-0058](change/closed/0058-batch-approval.md) |
| GitHub をリモートに持たない開発向けの、PR 風のローカルのレビュー画面（ref のスキーマ・配送・アプリの安全規則・統合）を知る・変える | [ローカル PR ビューアの設計](spec/pr-viewer.md)、[CHG-0060](change/0060-local-pr-viewer.md) |
| PR ビューアと pi の非同期のメッセージ・キュー（受信箱。見送り・撤去済み）の経緯を知る | [CHG-0061](change/closed/0061-pr-inbox.md) |
| PR の管理・統合を、人が操作するアプリへ移す（保留・受信箱の撤去、merge commit、押下契機の `pis -p`、pi を通常のコーディングへ戻す）を知る・変える | [CHG-0062](change/0062-pr-hub-simplify.md) |
| 親と子で文脈（AGENTS.md）を分ける（子に必要な規則だけを渡す） | [CHG-0059](change/closed/0059-child-context.md) |
| フルガードの統合先・作業ブランチの接頭辞を、リポジトリ内の `pi.json` でプロジェクトごとに変える | [CHG-0057](change/0057-per-project-integrate.md)、[利用者マニュアル 7.6](spec/pi-manual.md#76-プロジェクトごとの設定pijson) |

### 案件と根拠

| 目的 | 文書 |
| --- | --- |
| いま何を探索しているか知る | [探索・変更案件](change/index.md) |
| 設計理由を確認する | [ADR一覧](adr/index.md) |
| 技術調査の結果を確認する | [調査記録一覧](research/index.md) |
| 文書で使う用語を確かめる | [用語集](spec/glossary.md) |

## 現在の状態と最近の変更

活動中の案件・状態・終了した案件は [案件の索引](change/index.md) が正本（ここには複写しない。古くなるため）。
「適用」「実機で確かめた」の区別は [用語集](spec/glossary.md#適用と検証の段階)、現行仕様の一覧は [仕様・運用](spec/index.md)。

## 判断待ち・障害

- **Claude Code が使えない**（2026-09-25〜）。OAuth が期限切れで、再開には
  契約が要る。**棚上げと判断した。** 止まるのは Claude 実機の検証だけで、
  `~/.claude/skills` などの資産は OpenCode / Copilot から使われ続ける
  （`~/.copilot/skills` は symlink、OpenCode は監視対象に含む）。
  再開条件は「Claude Code を再契約したとき」
  - 保留中の測定: [`context: fork` が Claude 側で効くか](research/opencode/skill-frontmatter.md)
- **CHG-0005 を保留へ移した**（2026-09-25）。残りは A2 だけで、
  第一サポートは既に pi に決まっており（2026-10-09）、待つのは CHG-0020 の段 6 での
  OpenCode 節の撤去。
  なお CHG-0002 は終了済み（段階 5 は CHG-0020 へ移管）
  — [案件の索引](change/index.md)

## 運用ポリシー

情報を**役割**で分ける。同じことを二か所に書かない。

| 段階 | カテゴリ | 答える問い | 寿命 |
| --- | --- | --- | --- |
| 探索・計画 | [探索・変更案件](change/index.md) | この目的をどう達成するか | 永続（終了したら `change/closed/` へ移す） |
| 観測 | [調査記録](research/index.md) | 何を観測したか | 永続（追加のみ） |
| 決定 | [ADR](adr/index.md) | なぜその選択をしたか | 永続（覆すときは新規 ADR） |
| 仕様 | [仕様・運用](spec/index.md) | 今どうなっているか | 永続（置換） |

### 案件は経緯ではなく現在の設計を書く

`change/` は**いま何をどう作るか**の正本であって、調査の時系列ではない。

- 実験の手順・生ログ・数値の内訳は `research/` に置く
- 案件に残すのは**判断を動かした結論と、それが設計に与えた影響**だけ
- ただしポインタ集にはしない。**案件だけ読めば現状が分かる**状態を保つ
- 観測を案件へ書き写したくなったら、代わりに `research/` へ 1 本足して
  結論の行からリンクする
- 案件が育って「現在地」が実装計画より長くなったら、整理の合図

### 配置の判断

- 複数候補があり、まだ決着していない → `change/` の案件
- 実際に観測・実測した → `research/` に日付つきの記録を追加
- 後で理由を失うと困る重要な選択をした → `adr/`
- 今の動き方・使い方が変わった → `spec/`
- **このセッション限りの実行状態** → docs に書かない。
  復帰記録は、圧縮を跨ぐ仕組み（[文脈の引き継ぎ](spec/checkpoint.md)）が扱う
  （OpenCode の checkpoint プラグイン。pi では使わない）。固定パスを docs に書かない
- 文書を増減したら、対応するカテゴリの `index.md` も更新する
- **全ての作業が 4 種類を生産するわけではない。** 誤字修正や単純な設定変更に
  案件や比較表を要求しない
