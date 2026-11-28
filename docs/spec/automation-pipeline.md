# 全自動統合・main 昇格・端末安全更新パイプライン

計画合意後の `ai/*` 実装・3 OS `ci-gate`・無承認 Squash Auto-Merge・自動片付け（[ADR-0044](../adr/0044-github-app-auto-merge-and-3os-ci.md)）と、3 OS 隔離スモークによる `develop` → `main` 昇格および端末の自動ファイル切り戻し更新（[ADR-0045](../adr/0045-stage3-smoke-promotion-and-safe-update.md)）の全体仕様。

インタラクティブな全体フロー図（経路フィルタ・ダーク/ライト切替付き単体 HTML）は **[automation-pipeline.html](automation-pipeline.html)** をブラウザで直接開いて参照できる。

## 全体構成（5 段階）

| 段階 | 入口・仕組み | 人手介入の要否 |
| --- | --- | --- |
| 1. 隔離 worktree 実装 | `scripts/ai_pr.py start <slug>` → 実装 → `mise run verify:all` ＋ 独立 `reviewer` 監査 → ローカル commit | 計画合意のみ（ローカル自走） |
| 2. PR 提出 | `scripts/ai_pr.py submit`（専用 GitHub App `applejxd-dotfiles-ai`、`gitleaks` 走査＋`ai/*` 非強制 push＋Auto-Merge 予約） | 不要 |
| 3. 3 OS CI と権限境界 | `.github/workflows/ci.yml`（`policy`・`static`・`linux`・`windows`・`macos` → `ci-gate`）＋ Ruleset `28273156` | 通常パスは**無承認**／保護パスは `protected-path-approval` で **1 クリック承認**／`.github/workflows/**` は**人手 push** |
| 4. 終了後の自動片付け | リモート: `delete_branch_on_merge` ＋ `cleanup-closed-ai-branch.yml` ／ ローカル: `scripts/ai_pr.py cleanup --verify-github` | 不要 |
| 5. `main` 昇格と端末反映 | 昇格: `.github/workflows/promote-main.yml`（手動起動 → 3 OS `isolated_smoke.py` → 人承認 → `main` 更新） ／ 端末: `mise run safe-update`（`scripts/chezmoi_safe_update.py`） | 昇格開始・承認と端末実行は人操作（失敗時のファイル切り戻しは自動） |

## 隔離スモーク検査（`scripts/isolated_smoke.py`）

実機の `$HOME` や永続状態に一切触れず、使い捨てディレクトリに対して chezmoi の展開と主要設定の起動スモークを実行する。

```bash
# 隔離環境での init + 2 回 apply + 残差分 0 件 + 起動スモーク
mise run smoke:isolated
# または
uv run --no-project python scripts/isolated_smoke.py isolate

# 既存の展開先（実 $HOME など）への非破壊ヘルスチェックのみ
uv run --no-project python scripts/isolated_smoke.py check-dest "$HOME"
```

### 検証項目

1. `chezmoi init --force --no-tty`: `home/.chezmoi.toml.tmpl` がエラーなく描画されること。
2. 1 回目 `chezmoi apply --exclude scripts,externals --no-tty --force`: 全テンプレートと `modify_` スクリプトが完走すること。
3. `chezmoi diff --exclude scripts,externals`: **1 回目適用直後の残差分が 0 件**であること（初回作成と更新で出力がずれる非冪等な `modify_` を検出する）。
4. 2 回目 `chezmoi apply --exclude scripts,externals`: 再実行しても失敗しないこと。
5. 生成物の起動スモーク（`check-dest` 共通）:
   - Pi 設定 JSON 6 ファイル（`settings.json`・`mcp.json`・`compaction.json`・`pi-plan-mode.json`・`pi-permission-system/config.json`・`subagent/config.json`）が構文正当な JSON オブジェクトであること。
   - `git config --file <dest>/.config/git/config --list` が成功すること。
   - `vim -Nu <dest>/.vimrc -es -c qa!` がローカル環境で成功し、かつ `SSH_CONNECTION` 設定時に `unnamedplus` が無効化されていること。
   - Windows: `pwsh -NoProfile` で `<dest>/.config/powershell/profile.ps1` がエラーなく読み込めること。
   - Linux / macOS: `bash --norc` で `shellenv.sh`、`zsh -f` で `.zshenv` + `shellenv.sh` が読み込め、`.local/bin/pk --help` が成功すること。

**見ない範囲**: `.chezmoiscripts/` の実実行（パッケージ導入・レジストリ・sudo）と `.chezmoiexternal` のネットワーク取得は除外している。スクリプト込みの初回導入検証は [Docker での cold start 検証](testing.md#docker-での-cold-start-検証) が担う。

## `develop` → `main` 昇格（`promote-main.yml`）

他端末の更新先である `main` は、日常統合ブランチ `develop` から以下のゲートを通して昇格させる。

1. GitHub Actions の `promote-main` ワークフローを `workflow_dispatch`（手動）で起動する。
2. `ubuntu-24.04`・`windows-2025`・`macos-latest` の 3 OS で、`develop` 先端に対する既存テストと `scripts/isolated_smoke.py isolate` を並列実行する。
3. 3 OS すべてが成功した場合のみ、Environment `protected-path-approval`（`deployment: false`）でオーナー承認待ちに入る。
4. 承認後、`main` を検証済みの `develop` SHA へ更新する（Fast-Forward 優先、不可時は merge commit）。

> `.github/workflows/promote-main.yml` 自体は `.github/workflows/**` 配下のため、専用 GitHub App からは push できない（初回投入および変更時は利用者が人手で push する。本 PR 統合後の次ステップで投入する）。

## 端末の安全更新と自動切り戻し（`scripts/chezmoi_safe_update.py`）

各端末（Windows / Ubuntu / WSL / macOS）で dotfiles を取り込んで適用するときの安全な入口。

```bash
# 隔離プレフライト → 本番 init/apply → 実機スモーク（失敗時は直前 SHA へ自動切り戻し）
mise run safe-update

# 事前確認のみ（実機 $HOME を変えずに隔離プレフライトと実行予定 scripts 一覧を表示）
uv run --no-project python scripts/chezmoi_safe_update.py update --dry-run

# スクリプトを実行せず管理ファイルだけ安全更新する
uv run --no-project python scripts/chezmoi_safe_update.py update --exclude-scripts

# 現在の記録（last_good_sha と直近の試行結果）を見る
uv run --no-project python scripts/chezmoi_safe_update.py status

# 直前の正常世代（または指定 SHA）へ管理ファイルを手動で切り戻す
uv run --no-project python scripts/chezmoi_safe_update.py rollback
uv run --no-project python scripts/chezmoi_safe_update.py rollback --to <commit-sha>
```

### 状態遷移と 2 段防御の不変条件

記録先は `~/.local/state/dotfiles-safe-update/state.json`（一時ファイル + `os.replace` によるアトミック更新、同ディレクトリの `update.lock` で二重起動を排他）。

1. **クリーン確認**: source リポジトリに未コミット変更がある場合は何もせず中止する。
2. **第 1 段（実機無傷の隔離プレフライト）**: 更新先 SHA（および `last_good_sha` 未記録の初回実行時は切り戻し候補の現在 HEAD）を一時 detached worktree で `isolated_smoke.py` に通す。不合格なら**実機 `$HOME` と source ブランチに一切触れず**終了コード 1 で止まる（注: プレフライトは `BW_SESSION` を遮断して走るため、Bitwarden テンプレート固有の展開は本番段でのみ評価される）。
3. **予定スクリプトの採取**: `chezmoi status --include scripts` から今回走る `run_` / `run_once_` / `run_onchange_` の一覧を控える（取得失敗時は `<unknown>` として安全側に警告する）。
4. **恒久 source からの本番適用**: `.chezmoi.workingTree` や `.chezmoi.sourceDir` を使うテンプレート（`ccd`・`chezmoi.toml` hooks 等）に使い捨てパスを焼き込まないよう、**本体 `source` ディレクトリ自身**を更新先 SHA に向けて `chezmoi init --force` → `chezmoi apply --no-tty --force`（注意: `--force` のため実機 `$HOME` 側の未 `re-add` 手動編集は上書きされる）を実行し、直後に実機 `$HOME` へ `check-dest` スモークを走らせる。
5. **成功時**: `last_good_sha` をアトミック更新して終了コード 0 で完了する。
6. **第 2 段（失敗時の自動ファイル切り戻し）**: 本番 `apply`（タイムアウト・中断を含む）または実機 `check-dest` が失敗した場合、本体 `source` を直前の正常 SHA（`last_good_sha`、未記録なら事前検証済みの更新前 `HEAD`）へ戻し、本体 `source` から `--exclude scripts,externals` で管理ファイル群を自動復元して終了コード 1 を返す。

### 自動では戻らない境界（chezmoi scripts・新規追加ファイル）

既存の管理ファイル（`~/.vimrc`・`~/.config/**`・`~/.pi/agent/**` 等）は上記の自動ロールバックで直前世代へ戻るが、**以下の変化は旧世代の単純再展開だけでは戻らない**。

- `run_once_` / `run_onchange_` / `run_` スクリプトが行った OS パッケージ導入・削除（apt / brew / winget / scoop / mise）、レジストリ変更、サービス再起動、システム設定変更
- `~/.config/chezmoi/chezmoistate.boltdb` に記録された `scriptState` / `entryState`
- 新しい世代でだけ追加された新規ターゲットファイル（旧世代の `.chezmoiremove` には載っていないため宛先に残る）
- `.chezmoiexternal` が初回取得した外部リポジトリ（`.zinit`・`.vim/colors/iceberg.vim` 等）

本番適用時に `run_*` スクリプトが予定されていた状態で失敗・切り戻しが起きた場合、CLI は JSON 出力の `side_effect_warning` と `pending_scripts` に該当スクリプト一覧を必ず明示する。

[仕様一覧へ戻る](index.md)
