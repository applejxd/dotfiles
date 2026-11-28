# 3 OS 隔離スモーク＋人承認で main へ昇格し、端末更新は自動ファイル切り戻し CLI で守る

- **ステータス**: Accepted
- **日付**: 2026-11-28
- **決定者**: applejxd
- **結論**: `develop` → `main` 昇格は手動トリガー＋3 OS 隔離 `chezmoi apply`/起動スモーク全通＋オーナー承認で行う。端末更新は共通 CLI `scripts/chezmoi_safe_update.py` で隔離プレフライト後に適用し、失敗時は直前の正常 SHA へ管理ファイルを自動切り戻して scripts 副作用を明示警告する。理由は多端末が参照する `main` の事故を防ぎつつ、実機を壊さず復旧できるようにするためである。

## コンテキスト

- 背景: [ADR-0044](0044-github-app-auto-merge-and-3os-ci.md) により `ai/*` → `develop` の 3 OS CI と無承認 Squash Auto-Merge が稼働した。一方、他端末の `chezmoi update` が参照する `main` への昇格ゲートと、端末適用失敗時の復旧手段は未整備だった。
- 問題: `chezmoi update --init` は実機 `$HOME` へ直接適用するため、環境依存の `modify_` や設定不整合があると稼働中環境を壊し得る。また `run_once_` / `run_onchange_` スクリプトの外部副作用（パッケージ導入・レジストリ・OS 設定）は単純なファイル再展開では元に戻らない。
- 制約: Windows ネイティブ・Ubuntu/WSL・macOS の全端末で同じ手順を保ちたい。また `.github/workflows/**` は専用 GitHub App に書き込み権限を与えていないため、昇格ワークフロー自体の追加・変更は人手 push が必要になる。

## 検討した選択肢

| 選択肢 | 利点 | 欠点 | 判断 |
| --- | --- | --- | --- |
| 1. 手動トリガー＋3 OS 隔離スモーク＋人承認昇格 ＆ 自動ファイル切り戻し CLI | 事故範囲が最小で、実機破壊を 2 段で防げる | 昇格開始と最終承認に 1 回ずつ人操作が要る | 採用 |
| 2. `develop` 通過後に無承認で `main` へ自動昇格 | 人手がゼロになる | 全端末が参照する `main` まで無承認で動き波及範囲が広い | 却下 |
| 3. 切り戻しを自動化せず手動 `rollback` サブコマンドだけ提供 | 実装がより単純 | 適用失敗直後にシェルや設定が壊れた状態が一時残る | 却下 |
| 4. OS ごとのスナップショット（Btrfs/ZFS/復元ポイント）に依存 | OS パッケージ変更も戻せる場合がある | Windows / WSL / macOS 共通で前提にできず維持費が過大 | 却下 |

### 選択肢 1: 手動トリガー＋3 OS 隔離スモーク＋人承認昇格 ＆ 自動ファイル切り戻し CLI

- 概要:
  - **隔離スモーク（`scripts/isolated_smoke.py`）**: 使い捨ての `-D <dest> -c <cfg> --persistent-state <db>` に対し `chezmoi init --force` → `apply --exclude scripts,externals` → 初回残差分 0 件検査 → 2 回目 `apply` → 生成済み Pi JSON・gitconfig・Vim（ローカル＋`SSH_CONNECTION` ガード）・OS 別シェル（PowerShell `profile.ps1` / `bash`・`zsh` の `shellenv.sh`・`pk`）の起動スモークを行う。
  - **`main` 昇格（`.github/workflows/promote-main.yml`）**: `workflow_dispatch` で起動し、Ubuntu / Windows / macOS の 3 ランナーで `isolated_smoke.py` が全通した後に Environment `protected-path-approval`（`deployment: false`）でオーナー承認を待ち、承認後に `develop` を `main` へ昇格する。
  - **端末の安全更新（`scripts/chezmoi_safe_update.py`）**: ① 更新先 SHA（および初回実行時は切り戻し候補 SHA）を一時 detached worktree＋`isolated_smoke` で**実機に触れる前にプレフライト検証**し、② 本番適用とロールバック適用は一時 worktree ではなく**恒久の本体 `source` ディレクトリ自身**（`-S <repo> --working-tree <repo>`）から行い、`.chezmoi.workingTree` / `sourceDir` を含むテンプレートに使い捨てパスが焼き込まれないようにする。③ 本番適用と実 `$HOME` の `check-dest` スモークが両方通ったときだけ `~/.local/state/dotfiles-safe-update/state.json` の `last_good_sha` をアトミック更新する。④ 本番適用（タイムアウト例外を含む）または実機スモークが失敗した場合は、source を直前の正常 SHA へ戻した上で本体 `source` から `--exclude scripts,externals` で管理ファイルを自動復元し、`run_*` スクリプトが予定されていた場合は「外部副作用は自動では戻らない」旨と一覧を明示警告する。
- 利点の詳細: テンプレートや JSON・シェル構文の破損は第 1 段（隔離プレフライト）で実機無傷のまま止まり、実機固有の状態差による失敗も第 2 段（恒久 source からの自動ファイル切り戻し）で `git reset --hard` を使わずに直前世代へ戻せる。
- 欠点の詳細: `.chezmoiscripts/` によるパッケージ導入・レジストリ変更・`chezmoistate.boltdb` の `scriptState` は自動では巻き戻せないため、境界を仕様と出力で明示する必要がある。

## 決定事項

選択肢 1 を採用する。

理由:

- chezmoi 標準コマンド（`chezmoi update` / `chezmoi verify`）単体には「一時環境での事前スモーク通過を条件にした実機適用」と「失敗時の `last_good_sha` への自動切り戻し」が無いため、標準ライブラリのみの薄い Python CLI 2 本（`scripts/isolated_smoke.py`・`scripts/chezmoi_safe_update.py`）で補う（[ADR-0031](0031-evaluate-existing-extensions-first.md) の最小自作条件: 依存なし、維持対象は chezmoi CLI フラグ `-S/-D/-c/--persistent-state` のみ、chezmoi 本体が世代ロールバック付き更新を備えたら撤去する）。
- 新スクリプト 2 本とその試験は検査・配備の信頼境界に直結するため、`scripts/ci_policy.py` の保護パスに登録して無承認改変を防ぐ。

## 決定の確認方法

- [ ] `scripts/isolated_smoke.py` が現在のリポジトリに対して残差分 0 件・全起動スモーク通過で成功することを試験で確認する。
- [ ] `scripts/chezmoi_safe_update.py` で ① 正常更新、② 壊れたコミットのプレフライト阻止（実機無傷）、③ 本番後スモーク失敗時の自動ファイル切り戻し＋`run_*` 副作用警告、④ 手動 `rollback`、⑤ dirty / 二重起動ロック拒否がすべて通ることを試験で確認する。
- [ ] `.github/workflows/promote-main.yml` を人手 push 後、手動トリガーで 3 OS 隔離スモーク → 承認待ち → `main` 昇格が通ることを実測する。

## 結果

| 種類 | 内容 |
| --- | --- |
| 良い結果 | `main` 昇格前に 3 OS で実際の chezmoi 展開と起動スモークが強制され、端末更新失敗時も管理ファイルが自動で直前世代へ戻る |
| 悪い結果 | `promote-main.yml` の初回投入・変更には利用者による人手 push が必要。scripts の外部副作用は手動復旧が残る |
| 中立 | 日常更新の推奨入口として `mise run safe-update`（`scripts/chezmoi_safe_update.py update`）が加わる |

## 関連 ADR

- [ADR-0031](0031-evaluate-existing-extensions-first.md): 自作 CLI 2 本の最小化・維持費・撤去条件の根拠
- [ADR-0038](0038-allow-chezmoi-init-dependency.md): `init --force` を含む更新経路の前提
- [ADR-0044](0044-github-app-auto-merge-and-3os-ci.md): 前段となる `ai/*` → `develop` の自動統合基盤
