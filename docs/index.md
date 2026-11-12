# 現在地とドキュメント

目的: Windows / Ubuntu / WSL / macOS の dotfiles を chezmoi で管理し、
pi の設定（権限・MCP・スキル）を chezmoi で配備する。

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
| pi を導入・更新する | [pi の導入](spec/cli-management.md#pi-の導入)・[Windows の pi](spec/cli-management.md#windows-の-pi) |
| シェルの起動ファイルに何を置いてよいか知る | [シェルの起動契約](spec/shell.md#シェルの起動契約) |
| マシンごとに違う設定（データセットの置き場など）を置く | [マシン固有の設定の置き場](spec/shell.md#マシン固有の設定の置き場) |
| C++ の 1 ファイルを debug / release で実行する（`runcpp`） | [C++ の単一ファイル実行](spec/dev-environment.md#c-の単一ファイル実行runcpp) |
| zsh プラグインの遅延読み込みの順序を変える | [zinit の遅延読み込みの順序](spec/shell.md#zinit-の遅延読み込みの順序) |
| sops + age を導入・復旧する | [秘密情報の管理セットアップ（sops + age）](spec/sops-age.md) |
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
| 新しい機械での初回導入を Docker で検証する | [Docker での検証](spec/development.md#新しい機械での初回導入を-docker-で検証する) |
| gitflow-lite の運用（起票は親、AI は feature の worktree でコミット、統合は利用者の指示で）を知る | [開発ガイドのブランチモデル](spec/development.md#ブランチモデルgitflow-lite) |
| pi の設定の生成と所有権（宣言した項目と利用者の項目の分け方）を知る | [設定の生成と所有権](spec/agent-config-generation.md) |
| MCP サーバを追加・変更する | [MCP サーバ](spec/mcp-servers.md#mcp-サーバ) |
| Bedrock の PC で web 検索を使えるようにする（AgentCore Web Search） | [AgentCore Web Search](spec/mcp-servers.md#agentcore-web-search) |
| 調べものスキル（imozuru）を使う・変える・上流を更新する | [imozuru](spec/imozuru.md) |
| pi で作業を並列に進める（`/fleet`・`subagent`） | [プロンプトテンプレート](spec/agent-config-generation.md#プロンプトテンプレートfleetstepback)・[pi のコマンド早見](spec/pi-commands.md) |
| pi のスラッシュコマンドを調べる（`/fleet`・`/subagents-fleet`・`/plan` など） | [pi のスラッシュコマンド（stock）の早見](spec/pi-commands.md) |

### 安全性

| 目的 | 文書 |
| --- | --- |
| 何を守り、なぜ Bitwarden / sops なのかを知る | [セキュリティ](spec/security.md) |
| pi のコマンド実行を囲いの中だけで動かす（`pib`）・内側から見えない・書けない原因を調べる | [pi-sandbox-runner](spec/sandbox/pi-sandbox-runner.md) |

### 撤去した自作基盤

旧 custom プロファイル（フルガード・`pis`）・kcage・PR ビューア・作業台帳・pi 以外のハーネス（Claude Code・Codex・Copilot CLI・Gemini CLI・OpenCode・oh-my-pi）は、
2026-11-12 に撤去した（[ADR-0037](adr/0037-retire-custom-profile-and-other-harnesses.md)）。復元はタグ `archive/custom-harness-2026-11-12`。

| 目的 | 文書 |
| --- | --- |
| 隔離 GPU サンドボックス（専用 WSL2 + Docker + Tailscale SSH）を作る | [隔離 GPU サンドボックス](spec/sandbox/wsl-sandbox.md) |

### 案件と根拠

| 目的 | 文書 |
| --- | --- |
| **今の作業計画（活動中の 1 枚）を追う** | [今の作業計画](change/index.md#今の作業計画活動中) |
| いま何を探索しているか知る | [探索・変更案件](change/index.md) |
| 設計理由を確認する | [ADR一覧](adr/index.md) |
| 技術調査の結果を確認する | [調査記録一覧](research/index.md) |
| 文書で使う用語を確かめる | [用語集](spec/glossary.md) |

## 現在の状態と最近の変更

活動中の案件・状態・終了した案件は [案件の索引](change/index.md) が正本（ここには複写しない。古くなるため）。
「適用」「実機で確かめた」の区別は [用語集](spec/glossary.md#適用と検証の段階)、現行仕様の一覧は [仕様・運用](spec/index.md)。

## 判断待ち・障害

なし（2026-11-12 時点。撤去の後始末は [ADR-0037](adr/0037-retire-custom-profile-and-other-harnesses.md) の「後続」）。

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
  復帰記録は、圧縮を跨ぐ仕組み（文脈の引き継ぎ）が扱う。固定パスを docs に書かない
- 文書を増減したら、対応するカテゴリの `index.md` も更新する
- **全ての作業が 4 種類を生産するわけではない。** 誤字修正や単純な設定変更に
  案件や比較表を要求しない
