# 仕様・運用

現在有効な構成、セットアップ、運用手順をまとめています。

読み手は**利用者**（エージェントが実装した機能を、全体として見渡すための俯瞰。[ADR-0032](../adr/0032-docs-by-audience.md)）。

## 運用

- ファイル名は `kebab-case-topic.md`（連番なし）
- **現在の姿を書く。** 歴史的な意思決定の長い説明は
  [ADR](../adr/index.md) と [案件](../change/index.md) へリンクする。
  ただし**現在の運用に必要な判断基準・理由はここに書いてよい**
- 古くなった記述は残さず**置換**する（履歴は git が持つ）
- **意図した契約と実装の不一致は、不一致として記録する。**
  観測されたバグや未検証の挙動を、そのまま仕様として追認しない
- dotfiles では「source state を更新した」「対象の機械へ適用した」「実機で確かめた」を
  分けて書く（[用語集](glossary.md#適用と検証の段階)）
- 実装を変えたら同じコミットでここも直す

## 全般

| 文書 | 内容 |
| --- | --- |
| [Raspberry Pi への導入](platform-raspberry-pi.md) | ヘッドレスの Raspberry Pi への導入: ruby のプレビルド、clang の標準ヘッダ、失敗で apply を止めない設計、メモリ切れ対策、GUI 一式の削除 |
| [WSL](platform-wsl.md) | WSL の時刻同期、リモートからの SSH（Tailscale。手順・切り分け・LAN の IP 直指定） |
| [Windows の管理者権限](windows-admin.md) | 管理者権限が要る作業を 1 回の UAC に集約する仕組み（WSL 本体・GPU の電力上限・昇格・winget の scope・hostname） |
| [Windows の設定](windows-settings.md) | 電源・Tailscale の Unattended・7-Zip の関連付け・広告と推奨の抑止・シェルの既定値・Windows Terminal |
| [Tailscale の導入](tailscale.md) | macOS（cask）と Linux（公式の apt。Raspberry Pi を含み WSL を除く）への導入。applejxd だけ・ログインはしない |
| [CLI の導入と管理](cli-management.md) | mise による CLI 管理、pi の導入と更新、Herdr、external の取得 |
| [シェル](shell.md) | シェルの起動契約、マシン固有の設定の置き場、zsh の起動時間とプラグイン、PowerShell プロファイル |
| [開発環境](dev-environment.md) | C++ の単一ファイル実行（runcpp）、VS Code の拡張、code-exam |
| [プロジェクト構造](structure.md) | ディレクトリ構成、chezmoi スクリプトの順序、対応 OS、話題別の文書の地図 |
| [開発ガイド](development.md) | 環境の準備、変更の種類ごとの検証、Windows 実機での検証、スクリプトの追加 |
| [スクリプトが作るキャッシュ・状態](script-artifacts.md) | chezmoi スクリプトが直接作るキャッシュ・状態ファイル・再実行の印・一時ファイルを OS ごとに一覧にし、消すと何が起きるかを示す |
| [テストと検証の仕組み](testing.md) | Docker ハーネスのモード・環境変数・判定の契約、GitHub Actions で見ている範囲、既知の未達 |
| [セキュリティ](security.md) | 秘密情報の保護対象・脅威と、Bitwarden / sops の方式の理由 |
| [秘密情報の管理セットアップ（sops + age）](sops-age.md) | age 鍵の作成・バックアップ、プロジェクト設定、鍵の復旧手順 |
| [MCP サーバの設定](mcp-servers.md) | `[[mcp]]` から pi の `mcp.json` を生成する仕様、AgentCore Web Search の構成 |
| [pi の設定の生成と所有権](agent-config-generation.md) | pi の設定ファイルの構成と編集ルール、宣言した項目と利用者の項目の分け方、permission-system・package・圧縮・子エージェントの設定 |
| [Web 検索（自作の MCP と核）](web-search.md) | 自作 MCP `websearch` と、それが呼ぶ核の Web 検索・ページ取得・論文検索（スキル web-search は廃止）。検索の鎖（Brave → Exa → Tavily → DuckDuckGo）と次へ回す条件、鍵、クエリの秘匿チェックと取得の SSRF 対策、実測、未実装 |
| [imozuru（調べものスキル）](imozuru.md) | 上流 MaryCache/imozuru（MIT）を vendor して調整した調べものスキル。原文を要約せず保存し、検索は使える検索ツール（MCP の websearch）を使う。配る範囲・書き込み先の制限・接続の固定・秘匿チェック・YouTube（applejxd 限定）・`pis` の許可規則・レビューの経緯・未確認 |
| [away-shift（離席中の検証・実験）](away-shift.md) | 離席中に承認なしで検証を反復するスキル。stock の pi での前提（確認は 5 分で拒否・方針は離席中を区別できない）、事前判定を使わない判断、再開の仕組みの評価・未確認 |
| [conference-video（学会発表動画風の解説動画）](conference-video.md) | skill-lab から複製したスキル。流れ・依存（uv・Manim・VOICEVOX）・成果物の保存先・このリポジトリでの扱い（配布から外すもの・lint の対象外） |
| [スキルの frontmatter の方針](skill-frontmatter.md) | `allowed-tools` の書き方、スキルごとの宣言、委譲の型の割り当て |
| [トラブルシューティング](troubleshooting.md) | 症状 → 対象 OS・CLI → 対応先の索引 |
| [トラブルシューティング: 導入と適用](troubleshooting-bootstrap.md) | スクリプトの再実行、Python・Bitwarden・mise・APT・pi の導入で起きる障害 |
| [一時対処の一覧](temporary-workarounds.md) | 上流の不具合を避ける一時対処と撤去の条件。コード側は `TEMP-REMOVE` で探す |
| [用語集](glossary.md) | 囲い・許可の種類、秘密情報と資格情報、適用と検証の段階 |

## pi・サンドボックス

| 文書 | 内容 |
| --- | --- |
| [pi のスラッシュコマンドの早見](pi-commands.md) | 組み込み・package・prompt template のコマンド。実物と突き合わせる試験つき |
| [サンドボックス（総覧）](sandbox/index.md) | 判断・実行の隔離・環境ごとの隔離の 3 層と、撤去した旧来の囲い |
| [隔離 GPU サンドボックス（WSL2）](sandbox/wsl-sandbox.md) | 専用 WSL2 ディストロ + Docker + Tailscale SSH の作成スクリプト（`scripts/windows/wsl-sandbox/`、手動実行）。手順、手作業で残る ACL、隔離の限界 |
| [pi-sandbox-runner（pi のコマンド実行を包む囲い）](sandbox/pi-sandbox-runner.md) | `shellPath` に差す囲い（`pib`・`pib-shell`・runner）。bwrap の引数の並び・設定（`runner.toml`・`runner.local.toml`）・導入と確認・認証情報の扱い・限界。Linux 専用 |

[ドキュメント一覧へ戻る](../index.md)
