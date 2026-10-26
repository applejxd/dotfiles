# 仕様・運用

現在有効な構成、セットアップ、運用手順をまとめています。

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

## 一覧

### 全般

| 文書 | 内容 |
| --- | --- |
| [Raspberry Pi への導入](platform-raspberry-pi.md) | ヘッドレスの Raspberry Pi への導入: ruby のプレビルド、clang の標準ヘッダ、失敗で apply を止めない設計、メモリ切れ対策、GUI 一式の削除 |
| [WSL](platform-wsl.md) | WSL の時刻同期、リモートからの SSH（Tailscale。手順・切り分け・LAN の IP 直指定） |
| [Windows の管理者権限](windows-admin.md) | 管理者権限が要る作業を 1 回の UAC に集約する仕組み（WSL 本体・GPU の電力上限・昇格・winget の scope・hostname） |
| [Windows の設定](windows-settings.md) | 電源・Tailscale の Unattended・7-Zip の関連付け・広告と推奨の抑止・シェルの既定値・Windows Terminal |
| [CLI の導入と管理](cli-management.md) | mise による CLI 管理、AI CLI の導入と更新、Herdr、Envoy の取得 |
| [シェル](shell.md) | シェルの起動契約、マシン固有の設定の置き場、zsh の起動時間とプラグイン、PowerShell プロファイル |
| [開発環境](dev-environment.md) | C++ の単一ファイル実行（runcpp）、VS Code の拡張、code-exam |
| [プロジェクト構造](structure.md) | ディレクトリ構成、chezmoi スクリプトの順序、対応 OS、話題別の文書の地図 |
| [開発ガイド](development.md) | 環境の準備、変更の種類ごとの検証、Windows 実機での検証、スクリプトの追加 |
| [スクリプトが作るキャッシュ・状態](script-artifacts.md) | chezmoi スクリプトが直接作るキャッシュ・状態ファイル・再実行の印・一時ファイルを OS ごとに一覧にし、消すと何が起きるかを示す |
| [テストと検証の仕組み](testing.md) | Docker ハーネスのモード・環境変数・判定の契約、GitHub Actions で見ている範囲、既知の未達 |
| [セキュリティ](security.md) | 秘密情報の保護対象・脅威と、Bitwarden / sops の方式の理由 |
| [秘密情報の管理セットアップ（sops + age）](sops-age.md) | age 鍵の作成・バックアップ、プロジェクト設定、鍵の復旧手順 |
| [エージェント権限仕様](agent-permissions.md) | AI CLI の permission / hook / sandbox の入口。CLI ごとの適用範囲、3 層の概要、OpenCode の保存した承認の確認とリセット（`oc-utils`）、動作確認・導入・トラブルシュート |
| [MCP サーバの設定](mcp-servers.md) | `[[mcp]]` を各 CLI の形式へ生成する仕様、AgentCore Web Search の構成 |
| [モデルの割り当て](agent-model-assignment.md) | プロバイダと会社 PC の判定、階層（`[opencode.model.tier.*]` と pi の上書き）、生成されるもの |
| [hook の単一ソース化](agent-hooks-generation.md) | `[[hooks]]` から Claude / Copilot の hook を生成する仕様、外部ツールとの共存、Copilot CLI の制約 |
| [設定の生成と所有権](agent-config-generation.md) | `common.toml` の構成と編集ルール、生成先と所有権、MCP、pi と共有する設定（モデルの割り当て・コミットの確認など）、hook の単一ソース化 |
| [OpenCode 向けの設定の生成](opencode-config-generation.md) | OpenCode だけが使う設定（plugin 層・bypass・キーバインド・隔離起動）の生成。保留中のレガシー（撤去予定） |
| [モデルの割り当ての見直し](model-lineup-review.md) | OpenCode の階層に当てるモデルと effort を見直す時機・調べる場所・自前の評価・決め方・変える手順・再考の候補 |
| [pi の公式仕様と実測の棚卸し](pi-upstream.md) | pi の挙動のうち、公式に明示があるもの（リンクだけ・都度参照）と、明示が無く実測して頼っているもの（ノウハウ・試験で固定）の一覧。確認先と更新時の手順、codemode の扱い |
| [Web 検索（web-search skill）](web-search.md) | skill + CLI の Web 検索・ページ取得・論文検索。検索の鎖（Brave → Exa → Tavily → DuckDuckGo）と次へ回す条件、鍵、クエリの秘匿チェックと取得の SSRF 対策、実測、未実装 |
| [imozuru（調べものスキル）](imozuru.md) | 上流 MaryCache/imozuru（MIT）を vendor して調整した調べものスキル。原文を要約せず保存し、検索は web-search を使う。配る範囲・書き込み先の制限・接続の固定・秘匿チェック・YouTube（applejxd 限定）・`pis` の許可規則・レビューの経緯・未確認 |
| [文脈の引き継ぎ](checkpoint.md) | 圧縮を跨いで作業文脈を保つ checkpoint の保存先・記録の形・plugin・失敗時の動作 |
| [トラブルシューティング](troubleshooting.md) | 症状 → 対象 OS・CLI → 対応先の索引 |
| [トラブルシューティング: 導入と適用](troubleshooting-bootstrap.md) | スクリプトの再実行、Python・Bitwarden・mise・APT・AI CLI の導入で起きる障害 |
| [トラブルシューティング: AI CLI の実行時](troubleshooting-agents.md) | sandbox の依存（Copilot / Claude 別）、Windows の hook、skills の読み込み失敗、`.copilot/skills` の junction |
| [一時対処の一覧](temporary-workarounds.md) | 上流の不具合を避ける一時対処と撤去の条件。コード側は `TEMP-REMOVE` で探す |
| [用語集](glossary.md) | 境界・隔離起動・通常起動、出力内容と配置先、許可の種類、秘密情報と資格情報、適用と検証の段階、A1 / A2 / B |

### サンドボックス（`sandbox/`）

| 文書 | 内容 |
| --- | --- |
| [サンドボックス（総覧）](sandbox/index.md) | 目的と脅威モデル、層と責務、起動のモード、内側から見えるもの・見えないもの、通信の方針、設定と試験の対応、未解決 |
| [認証ブローカー（`pis`）](sandbox/broker.md) | Copilot・GitHub・検索の認証ブローカー（Envoy）の正本。責務、全体像、`[pis.broker]` と `--no-broker`、各ブローカーの契約、鍵の隔離、不変条件と試験の対応、Envoy の導入、未対応・未検証（認証つきプロキシ・Bedrock） |
| [Claude / Copilot の sandbox のネットワーク層](sandbox/cli-sandbox-network.md) | ドメインの whitelist、資格情報の除去、WSL2 の抜け穴（seccomp）、sandbox に移せないネットワーク系の検査 |
| [このマシンだけで許可を足す](sandbox/cli-sandbox-local-allow.md) | `local.toml`・`settings.local.json`・Copilot の `allowed_directories` などの使い分け |
| [Copilot の sandbox](sandbox/copilot-sandbox.md) | Claude との違いと、実測した既定の許可範囲 |
| [Fence 境界の組み立て](sandbox/fence-boundary.md) | `pis` と `ocs` が共有する Fence の境界: 組み立ての規則、起動ディレクトリの制限、保護対象、プロジェクトごとの追加、起動前の退避、境界チェック、信頼の鎖 |
| [OpenCode 隔離起動のアーキテクチャ](sandbox/opencode-sandbox.md) | `ocs` の構成、起動順序、Fence の境界の組み立て規則、DB の共有、起動前の退避、境界チェック（`ocs --check`）、環境変数 `PIS_EXTRA_READ` での読み取りの追加、`devices`・`PIS_EXTRA_DEVICES` でのデバイスの追加 |
| [sandbox (Claude Code / Copilot CLI)](sandbox/agent-sandbox.md) | sandbox 層・ネットワーク層・seccomp、マシン固有の許可 (`local.toml`) |
| [隔離 GPU サンドボックス（WSL2）](sandbox/wsl-sandbox.md) | 専用 WSL2 ディストロ + Docker + Tailscale SSH の作成スクリプト（`scripts/windows/wsl-sandbox/`、手動実行）。手順、手作業で残る ACL、隔離の限界（mirrored）、運用上の注意、検証の状況 |

### ガード（`guard/`）

| 文書 | 内容 |
| --- | --- |
| [ガード（総覧）](guard/index.md) | 目的と保証の範囲、判定の 4 つの結果（deny / confirm / ask / allow）、評価の順番、確認の振る舞い、権限の設計（GitHub）、ツール定義の拡張、設定と試験の対応、未解決 |
| [判定 API（`decide`）](guard/pi-decide.md) | pi のガードが呼ぶ CLI 非依存の判定器。入力と応答、`source`、評価の順番、confirm、役割（`[pi.profiles]`）、`check_bash.py` との等価の試験 |
| [pi の拡張と補助機能](guard/pi-extensions.md) | 拡張の入れ方の方針、`guarded_action`、ツールの拡張、圧縮、`git commit` の確認、整形、`/fleet`、stepback、キーバインド、Orca・Zed |
| [pi の子エージェント](guard/pi-subagents.md) | `guarded_task` の起動と役割、`review` への依頼、job、子の操作、worktree 隔離、Windows の `task` |
| [pis のサンドボックス（pi の側）](guard/pi-sandbox.md) | agent 置き場・セッション・認証、プロキシ必須の環境での通信、拒否リスト型の通信、緩和のゲート |
| [pi のガード](guard/pi-guard.md) | 起動の形、素の pi との対応、Windows、pi の設定、判定の外で動くもの、置き場・環境変数・しくみ、MCP、試験、実機で確認する項目 |
| [OpenCode のガードの仕様](guard/opencode-guard.md) | OpenCode の guide plugin が出す誘導・deny の説明・allow したコマンドの書き込み形。保留中のレガシー（撤去予定） |
| [コマンド・ファイルの判定](guard/agent-command-policy.md) | 照合規則、allow / ask / deny の使い分けと例外、bash 検査ルールの足し方、CLI 差 |

[ドキュメント一覧へ戻る](../index.md)
