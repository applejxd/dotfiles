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
| Raspberry Pi へ導入する | [Raspberry Pi](spec/structure.md#raspberry-pi) |
| Raspberry Pi に入った GUI 一式を消す | [入ってしまった GUI 一式を消す](spec/structure.md#入ってしまった-gui-一式を消す) |
| Herdr を mise で導入・更新する | [Herdr の管理](spec/structure.md#herdr-の管理) |
| GitHub CLI を mise で導入・更新する | [mise による CLI 管理](spec/structure.md#mise-による-cli-管理) |
| Claude Code / Copilot CLI / OpenCode を導入・更新する | [AI CLI の導入](spec/structure.md#ai-cli-の導入) |
| シェルの起動ファイルに何を置いてよいか知る | [シェルの起動契約](spec/structure.md#シェルの起動契約) |
| oh-my-pi（omp）を使う | [oh-my-pi の設定](spec/structure.md#oh-my-piompの設定) |
| sops + age を導入・復旧する | [秘密情報の管理セットアップ（sops + age）](spec/sops-age.md) |
| 圧縮を跨いで作業文脈を保つ仕組みを知る | [文脈の引き継ぎ](spec/checkpoint.md) |
| エラーを切り分ける | [トラブルシューティング](spec/troubleshooting.md) |
| `run_once_` / `run_onchange_` を走らせ直す | [スクリプトを走らせ直す](spec/troubleshooting-bootstrap.md#スクリプトを走らせ直す) |

### 設定の変更・検証

| 目的 | 文書 |
| --- | --- |
| 開発環境を準備して検証する | [開発ガイド](spec/development.md) |
| テストの種類と Docker ハーネスの契約を知る | [テストと検証の仕組み](spec/testing.md) |
| Windows 資産を実機で検証する | [Windows 実機での検証](spec/development.md#windows-実機での検証) |
| 新しい機械での初回導入を Docker で検証する | [Docker での検証](spec/development.md#新しい機械での初回導入を-docker-で検証する) |
| AI CLI の permission / hook を変更する | [エージェント権限仕様](spec/agent-permissions.md) |
| `common.toml` の書き方と生成先の所有権を知る | [設定の生成と所有権](spec/agent-config-generation.md) |
| コマンド・ファイルの allow / ask / deny を変える | [コマンド・ファイルの判定](spec/agent-command-policy.md) |
| MCP サーバを追加・変更する | [MCP サーバ](spec/agent-config-generation.md#mcp-サーバ) |
| Bedrock の PC で web 検索を使えるようにする（AgentCore Web Search） | [AgentCore Web Search](spec/agent-config-generation.md#agentcore-web-search) |
| OpenCode のモデル・プロバイダ（Copilot / Bedrock）を PC ごとに変える | [モデルの割り当て](spec/agent-config-generation.md#モデルの割り当て) |
| 新しいモデルが出たときに OpenCode のモデルの割り当てを見直す | [モデルの割り当ての見直し](spec/model-lineup-review.md) |
| OpenCode で作業を並列に進める（`/fleet`） | [並列作業](spec/agent-config-generation.md#並列作業fleet) |
| OpenCode のプラグインを検討する | [プラグイン生態系の棚卸し](research/opencode/plugin/ecosystem.md) |

### 安全性

| 目的 | 文書 |
| --- | --- |
| 何を守り、なぜ Bitwarden / sops なのかを知る | [セキュリティ](spec/security.md) |
| Claude Code / Copilot CLI の sandbox で読めない・書けない | [sandbox (Claude Code / Copilot CLI)](spec/agent-sandbox.md) |
| OpenCode の権限がなぜ他と違うか知る | [OpenCode V2 の扱い](spec/agent-permissions.md#opencode-v2-の扱い) |
| OpenCode の「常に許可」で保存した承認を確認・リセットする（`oc-utils`） | [保存した承認の確認とリセット](spec/agent-permissions.md#保存した承認の確認とリセット) |
| OpenCode を境界の内側で起動する仕組み（隔離起動 `ocs`）を知る | [OpenCode 隔離起動のアーキテクチャ](spec/opencode-sandbox.md) |
| 隔離起動の境界内で読めない・書けない原因を調べる | [境界の組み立ての規則](spec/opencode-sandbox.md#組み立ての規則) |
| sandbox で何ができるか調べる | [sandbox機能の包括調査](research/agents/sandbox-capabilities.md) |

### 案件と根拠

| 目的 | 文書 |
| --- | --- |
| いま何を探索しているか知る | [探索・変更案件](change/index.md) |
| 設計理由を確認する | [ADR一覧](adr/index.md) |
| 技術調査の結果を確認する | [調査記録一覧](research/index.md) |
| 文書で使う用語を確かめる | [用語集](spec/glossary.md) |

## 現在有効な状態

「適用」「実機で確かめた」の区別は [用語集](spec/glossary.md#適用と検証の段階) のとおり。
現行仕様の一覧は [仕様・運用](spec/index.md)。

| 対象 | 状態 | 確認日 | 根拠 |
| --- | --- | --- | --- |
| source state 全体 | 全 OS ぶん更新済み。適用して実機で確かめたのは Linux / WSL のみ | 2026-09-19（最終レビュー） | [仕様・運用](spec/index.md) |
| Raspberry Pi（64bit / ヘッドレス） | 実機で `apply` が完走。判定は `apply` のたびに評価する | 2026-09-26 | [CHG-0008](change/closed/0008-raspi-branching.md) |
| Windows native | source state のみ更新。Windows 11 の実機では未確認 | 2026-09-27 | [Windows での扱い](spec/agent-permissions.md#windows-での扱い) |
| 権限 / hook / MCP の生成 | `common.toml` から各 AI CLI へ生成して利用している | 2026-09-19（最終レビュー） | [エージェント権限仕様](spec/agent-permissions.md) |
| 秘密情報の管理 | sops + age と Bitwarden で利用している | 2026-09-19（最終レビュー） | [セキュリティ](spec/security.md) |
| 圧縮を跨ぐ引き継ぎ | OpenCode V2 のみ。実機の自動圧縮で確かめた。Claude / Copilot 向けの圧縮 hook は撤去 | 2026-09-25 | [CHG-0001](change/closed/0001-compaction-context-handover.md) |
| OpenCode の隔離起動（`ocs`） | Ubuntu / WSL で通常起動と併用。境界の道具を Fence に替え、履歴を通常起動と共有する。境界チェックは `ocs --check` で手動 | 2026-09-29 | [CHG-0009](change/closed/0009-ocs-simplify-for-accidents.md) |
| Claude Code | 使えない（OAuth 期限切れ）。棚上げ中 | 2026-09-25 | [判断待ち・障害](#判断待ち障害) |

## 活動中

次の一手の詳細は [案件の索引](change/index.md#活動中) にある。

| 案件 | 状態 | 現在の見立て・最大の未解決点 |
| --- | --- | --- |
| [CHG-0006](change/0006-pi-harness-trial.md) | In progress | Pi / oh-my-pi を**利便性の軸**で試す。段 2（常用）に着手。使って決まった設定の回収は段 2.5 |
| [CHG-0007](change/0007-harness-profiles.md) | In progress | 境界をハーネス非依存にする。プロバイダ層を切り出し済み。次は段 2（共有ランタイムとハーネスの節分け） |
| [CHG-0011](change/0011-agent-first-shell.md) | In progress | シェルの主な利用者を AI エージェントとして残課題を整える。波 1〜3 は実装済み。通常版 pip の誘導文は前段停止で解決。bypass を ask→allow に再定義（ADR-0014）。残りは Claude / Copilot への git 環境変数、Windows 実機での検証 |

## 判断待ち・障害

- **Claude Code が使えない**（2026-09-25〜）。OAuth が期限切れで、再開には
  契約が要る。**棚上げと判断した。** 止まるのは Claude 実機の検証だけで、
  `~/.claude/skills` などの資産は OpenCode / Copilot から使われ続ける
  （`~/.copilot/skills` は symlink、OpenCode は監視対象に含む）。
  再開条件は「Claude Code を再契約したとき」
  - 保留中の測定: [`context: fork` が Claude 側で効くか](research/opencode/skill-frontmatter.md)
- **CHG-0002 / CHG-0005 を保留へ移した**（2026-09-25）。どちらも残りは 1 段だけで、
  CHG-0006 の第一サポート決定を待っている。CHG-0002 は段階 3 まで適用済みで
  動いており、**止まっているだけで壊れてはいない**
  — [案件の索引](change/index.md)

## 最近の重要な変更

終了した案件の一覧は [案件の索引「終了」](change/index.md#終了) にある。

- 2026-09-26 — Raspberry Pi（64bit / ヘッドレス）を導入対象に追加。
  **`chezmoi init` を前提にした設計にしない**という規約を得た
  — [CHG-0008](change/closed/0008-raspi-branching.md)
- 2026-09-25 — スキルを役割で分離。`checkpoint` は復帰記録（A1）、`sdd-docs` は
  案件の更新（A2）と恒久的な文書化（B）
  — [checkpoint 仕様](spec/checkpoint.md)
- 2026-09-25 — `context: fork` は OpenCode に**読み捨てられる**と実測
  — [スキル frontmatter の解釈範囲](research/opencode/skill-frontmatter.md)
- 2026-09-25 — 圧縮要約そのものを checkpoint にした
  — [CHG-0001](change/closed/0001-compaction-context-handover.md)
- 2026-09-21 — OpenCode V2 の permission / MCP を `common.toml` から生成
  — [CHG-0002](change/0002-opencode-ask-by-default.md)
- 2026-09-20 — Copilot でも圧縮直後に checkpoint を自動注入
  — [記録 E7](research/agents/compaction-hooks.md)
- 2026-09-19 — `adr` スキルを `checkpoint` へ統合（役割の重複を解消）
  — [CHG-0001](change/closed/0001-compaction-context-handover.md)
- 2026-09-19 — docs を「情報の役割」で分け、案件を中心に置く運用へ
  — [ADR-0010](adr/0010-exploratory-spec-driven-docs.md)
- 2026-09-19 — `checkpoint` スキルを追加（compaction を跨ぐ復帰記録）
  — [ADR-0009](adr/0009-save-before-documenting.md)
- 2026-09-14 — Copilot の開発ツール自動許可を切り、必要な範囲を明示
  — [ADR-0008](adr/0008-explicit-dev-tool-grants.md)

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
  `checkpoint` スキルが解決するセッション別ファイルへ（固定パスを書かない）
- 文書を増減したら、対応するカテゴリの `index.md` も更新する
- **全ての作業が 4 種類を生産するわけではない。** 誤字修正や単純な設定変更に
  案件や比較表を要求しない
