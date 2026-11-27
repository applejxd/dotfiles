# develop 統合を GitHub App + 3 OS CI + Squash Auto-Merge へ移行する

- **ステータス**: Accepted
- **日付**: 2026-11-27
- **決定者**: applejxd
- **結論**: `develop` への統合はローカルの `git flow feature finish` をやめ、専用 GitHub App が `ai/*` ブランチから PR を立てて 3 OS CI の単一ゲート `ci-gate` 通過後に無承認で Squash Auto-Merge する方式にする。理由は Windows ネイティブ開発を残したまま 3 OS 検証・権限境界・終了後片付けを機械的に担保するためである。

## コンテキスト

- 背景: Windows ネイティブ・Ubuntu/WSL・macOS で dotfiles を開発しており、計画合意後の実装・検証・統合・片付けを全自動化したい。
- 問題: 従来のローカル `verify:all` とローカル `git flow feature finish` 運用は、Windows で `python3` 不在・PyYAML ビルド・CRLF・排他ロック未検証に阻まれ、他 OS の検証と統合ゲートの機械化が両立していなかった。
- 制約: 個人所有の公開リポジトリ（GitHub Free）であり、Merge Queue や Push rulesets は使えない。また PR 作成者本人は自分の PR を Approve できない。

## 検討した選択肢

| 選択肢 | 利点 | 欠点 | 判断 |
| --- | --- | --- | --- |
| 1. 専用 GitHub App + 3 OS `ci-gate` + Squash Auto-Merge + Environment 承認 | サーバ側で境界を強制でき、3 OS 検証と自動片付けが両立する | 初回の App 登録と Ruleset 設定が要る | 採用 |
| 2. 現行のローカル `git flow` 維持＋Windows 修正のみ | 変更量が最小 | ローカルで他 OS を検証できず、承認なし統合の外部ゲートが無い | 却下 |
| 3. Tailnet 内にプライベート Git サーバ＋自宅実機ランナー | 非公開で実機を回せる | 別インフラの保守と実機 `$HOME` 隔離の維持費が重い | 却下 |
| 4. 開発環境を Linux 1 本へ集約 | 開発時の OS 差が消える | Windows ネイティブ開発を継続したい要件に反する | 却下 |
| 5. Fine-grained PAT（本人名義）で PR 運用 | 1 分で発行できる | 個人オーナーの `Repository admin` バイパスを継承し得る | 却下 |

### 選択肢 1: 専用 GitHub App + 3 OS `ci-gate` + Squash Auto-Merge + Environment 承認

- 概要: 作業枝を `ai/<slug>` に統一し、専用 GitHub App（`applejxd-dotfiles-ai`、`contents: write` / `pull_requests: write` / `metadata: read` のみ）が専用入口 `scripts/ai_pr.py` から push・PR 作成・Auto-Merge 有効化を行う。
- 実行主体と信頼境界: `scripts/ai_pr.py` は `pib` の囲いの外（通常の `pi` / T3 Code セッションまたは利用者端末）から実行し、`~/.config/dotfiles-ai` の秘密鍵はファイルの道具・囲い内から読めないよう保護する。真のセキュリティ境界はサーバ側（App に `workflows` 権限・管理者バイパスを与えない構成、`base` コミット側の `scripts/ci_policy.py` による判定、Rulesets、Environment `protected-path-approval`）に置く。
- 保護境界: `.github/workflows/**` は App に `workflows` 権限を与えず push 時点で物理拒否する。ガード・pi 拡張・agent 定義・検査基盤・`.chezmoiscripts/**` は GitHub Actions の Environment `protected-path-approval`（`Required reviewers: applejxd`、`prevent_self_review: false`、`deployment: false`）で 1 クリック人承認待ちにする。
- 対象外: `AGENTS.md`・スキル・プロンプト・一般 dotfiles は保護パスに含めず、3 OS `ci-gate` と独立レビューの通過で無承認自動統合する。
- 片付け: リモートは merged 時の `delete_branch_on_merge` と未マージ close 時の削除ワークフローで 0 本にする。履歴は Squash で 1 仕事 1 コミットに束ねる。ローカルはマージ後に `develop` を `pull --ff-only --prune` し worktree とローカル枝を削除する。

### 選択肢 5 を却下した補足

- 根拠: Fine-grained PAT は発行ユーザー本人に紐づくため、Ruleset のバイパス対象に `Repository admin` を入れると AI 側トークンでもバイパスできてしまう懸念が残る。GitHub App は別アクター（`Integration`）であり、バイパス対象へ入れないことで管理者バイパスを物理的に遮断できる。

## 決定事項

選択肢 1 を採用する。`develop` へのローカル merge を定めた [ADR-0039](0039-merge-to-develop.md) は、本 ADR により置き換える（`Superseded by ADR-0044`）。

理由:

- ローカルの glob 規則だけでは `git push` や `gh` の危険引数を完全に塞げないため、GitHub 側の Ruleset と権限を絞った GitHub App を真の境界にする必要がある。
- 個人公開リポジトリでも GitHub Free で Branch Rulesets・Auto-Merge・Environments（`deployment: false`）が利用でき、3 OS ランナーも無料で使える。
- 統合先を GitHub の Squash Auto-Merge に一本化するとローカルの未 push マージコミットが消え、`chezmoi update` の rebase と衝突する ADR-0039 の前提自体が解消する。
- 専用 CLI（`scripts/ai_pr.py`）は最小限の自作部品として位置づける（[ADR-0031](0031-evaluate-existing-extensions-first.md)）。維持費は標準ライブラリ中心の単一スクリプトと単体テストに留め、撤去条件は GitHub CLI や pi 本体が App 認証＋保護パス検査付きの `ai/*` 限定 PR 入口を標準提供したときとする。

## 決定の確認方法

- [ ] App 認証トークンで `.github/workflows/**` を含む push が GitHub に拒否されることを実測する。
- [ ] App 認証トークンで `develop` への直接 push が Ruleset で拒否されることを実測する。
- [ ] 通常 PR（例: Vim の SSH 修正）が 3 OS `ci-gate` 通過後に無承認で Squash Auto-Merge され、リモート枝とローカル worktree が片付くことを実測する。
- [ ] 保護パス PR が通常テスト通過後に `protected-path-approval` で `Waiting` 停止し、オーナーの 1 クリック承認後にのみ Auto-Merge されることを実測する。
- [ ] 未マージ close した `ai/*` PR のリモート枝が自動削除されることを実測する。

## 結果

| 種類 | 内容 |
| --- | --- |
| 良い結果 | 計画合意後の実装・3 OS 検証・自動統合・片付けを Windows / Linux / macOS のどこからでも同じ流れで回せる |
| 悪い結果 | 途中経過の `ai/*` PR が公開リポジトリの Closed 一覧へ残る。秘密鍵のローカル管理と他マシン配布が新たに必要になる |
| 中立 | 既存の `feature/*` + `git flow feature finish` 運用から `ai/*` PR 運用へ切り替わる。`develop` → `main` の昇格・ロールバックは後続段で接続する |

## 関連 ADR

- [ADR-0031](0031-evaluate-existing-extensions-first.md): 自作ラッパー `scripts/ai_pr.py` の理由・維持費・撤去条件の根拠
- [ADR-0039](0039-merge-to-develop.md): 本 ADR で置き換える旧 `develop` 統合方針
- [ADR-0043](0043-delegate-bounded-implementation-to-a-single-worker.md): 実装と独立監査の委譲方針（本運用の前段で維持）
