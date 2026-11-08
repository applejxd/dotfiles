# CHG-0065: エージェント基盤の全面凍結と、公式既定の pi への切り替え（記録と再開の手引き）

- **状態**: Paused
- **凍結**: 2026-11-08。可逆。
- **基準**: [ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)
- **目的**: 自作したエージェント基盤を**動かさずに残し**、あとで再検討できるように、**何を・どこまで作ったか／何が未完か／何を学んだか／どう再開するか**を記録する。

## 経緯（決定ログ）

| 日付 | 出来事 |
| --- | --- |
| 2026-10 | pi に一本化し、フルガード（判定器・確認・承認の保留）・`pis`（Fence の境界）・作業台帳・PR ビューアを作る（ADR-0017〜0026） |
| 2026-11-05〜06 | 隔離方式の選び直し（microVM・Docker・nono の調査と試作。[記録](../research/agents/isolation-reselection-2026-11.md)）。ADR-0027（隔離の単位は開発環境） |
| 2026-11-07 | ADR-0028（リポジトリごとの Incus の箱）。WSL2 の Incus で実機の T1〜T7 に合格。kcage の実装 |
| 2026-11-08 | kcage を develop へ統合。実機でしか出ない不具合・設計の欠陥が続けて見つかる（下の「学び」）。coi・isx を調査して不採用。clone モード（箱専用の clone・複数 repo）の設計と第 1 波の実装。ツール隔離（pi はホストに残し、ツールだけ隔離）の実現性を調査。**利用者が疲れ、全面凍結を決定**（ADR-0030） |

## 凍結の一覧

「凍結」はソース・docs・試験を残して開発を止めること。stock プロファイルでは配備されない。

| 部品 | 場所 | 正本の文書 | 状態 |
| --- | --- | --- | --- |
| フルガード（判定器・確認・承認） | `home/dot_config/pi/harness/`・`scripts/agents/`・`home/dot_config/pi/commit-confirm/` | [guard](../spec/guard/index.md)・ADR-0017/0021/0022/0023/0024 | 凍結（custom プロファイルでだけ配備） |
| 境界（`pis`・`ocs`・Fence） | `home/dot_local/bin/executable_{pis,ocs,ocs-boundary-check,oc-utils}`・`home/dot_local/share/ocs/` | [pi-sandbox](../spec/guard/pi-sandbox.md)・[sandbox](../spec/sandbox/agent-sandbox.md)・ADR-0018/0019/0025 | 凍結（実行ファイルは残る） |
| 使い捨てコンテナ `pisd` | 枝 `feature/pisd`（46e8adfc。未統合） | [CHG-0064](0064-dev-environment-isolation.md) | 凍結（以前から） |
| 開発単位の環境（`dev-*`） | 枝 `feature/dev-env-front`（7e60d318。未統合） | CHG-0064 | 凍結（以前から） |
| 自作の拡張 | `home/dot_pi/agent/extensions/{activity,ask,btw,delegate-nudge,notify,plan,speed,subagents,todo}`・`prompts/` | [pi-features](../spec/pi-features.md) | 凍結（custom でだけ配備） |
| 作業台帳・`/goal`・並列・通知 | `home/dot_config/pi/harness/work/`・`scripts/work_stats.py` | [work](../spec/work/ledger.md)・ADR-0026 | 凍結 |
| PR ビューアと統合 | `apps/pr-viewer/`・`scripts/{pr_app,prs,feature_gate}.py` | [pr-viewer](../spec/pr-viewer.md)・ADR-0024 | 凍結 |
| 並列実装の運用 | `.agents/skills/feature-orchestration/`・`scripts/{bundle,wt_clean,wt_owner,parallel_check}.py` | [orchestration](../spec/orchestration.md)・[operation-modes](../spec/operation-modes.md) | 凍結（ただし git flow・worktree の運用自体は使ってよい） |
| **kcage**（Incus の箱） | `scripts/kcage/`・`test/kcage/`・`home/dot_local/bin/executable_kcage`（**develop に統合済み**） | [incus-box](../spec/sandbox/incus-box.md)・ADR-0028・CHG-0064 | 凍結（動かさない。片付けは下の手順） |
| kcage の clone モード（複数 repo 対応） | 枝 `feature/kcage-clone-*`（未統合・下の表） | [原本](../research/archive/2026-11-agent-stack/README.md) | 凍結（第 1 波まで実装） |
| **凍結しないもの** | `scripts/verify.py` と閉じたモジュールの規則・他の CLI（Claude・Codex・OpenCode・Copilot・Gemini）の設定生成・`common.toml.tmpl` の他 CLI 向けの部分・スキル群 | — | 継続 |

## 未完の作業（凍結した枝）

枝は**ローカルだけにある**（push していない）。単一ファイルの bundle を `.tmp/keep/archive/frozen-branches-2026-11-08.bundle` に作った（`git bundle verify` 済み。履歴を含む。`.tmp` は git の管理外なので、必要なら利用者が別の場所へ保管するか、枝を push する）。復元は `git clone <bundle> <dir>` または `git fetch <bundle> 'refs/heads/*:refs/heads/*'`。

| 枝 | 先頭 | 内容 |
| --- | --- | --- |
| `feature/kcage-clone-base` | f4c01f8c | 型（`model.py` の clone 関連・`StatePaths`・`Manifest`・`SyncReport` など）と骨。他の枝の基 |
| `feature/kcage-clone-policy` | 7c7b19a3 | 許可表・`kcage.toml` の項目（`git`・`workdir`・`repos` など） |
| `feature/kcage-clone-plan` | 9abee00e | `plan.py`・`root_helper.py`（clone の作業ディレクトリ・ラベル・commondir を作らない） |
| `feature/kcage-clone-gitrun` | 5af2571d | ホストの硬化した git 実行器・共有試験ヘルパー（`LocalBox`・悪性 bundle/tar の作り方） |
| `feature/kcage-clone-view2` | 7886bc58 | `view` の安全な tar 展開器 |
| `feature/kcage-clone-boxtool` | 2f147829 | 箱の中の helper `kcage-box`（seed・feed・snapshot・`ws`） |
| `feature/kcage-clone-inbox` | 32afc1f8 | 箱の bundle の検査と取り込み（悪性 bundle 14 種を拒否） |
| `feature/kcage-clone-wip` | d664e632 | ホストの未コミット作業のスナップショット |
| `feature/kcage-clone-docs` | d2627f1d | 概要（`kcage-overview.md`）・ADR-0029（clone モード）の骨子 |

- 未着手の波: 波 2 の `repos`（repo の列挙）、波 3 の `seed`・`sync`、波 4 の `commands`・CLI・テンプレートの git-flow-next、波 5 の e2e。接続（枝どうしの merge）も未実施。
- **契約と設計**: [原本](../research/archive/2026-11-agent-stack/README.md)の `kcage-clone-mode/`（決定 D1〜D20・API 契約書・単一 repo と複数 repo の設計）。
- 空の枝・worktree（`feature/kcage-clone-repos`・`feature/kcage-clone-view`・`feature/remote-tools-spike`）は、片付けてよい。

## 切り替えの手順（利用者が実行する）

stock プロファイル（公式の既定＋人気の拡張）に切り替える:

```bash
mkdir -p ~/.config/chezmoi
printf 'stock\n' > ~/.config/chezmoi/pi-profile
chezmoi apply
```

custom（自作の基盤）へ戻す: `~/.config/chezmoi/pi-profile` を消して `chezmoi apply`（自作のファイルが再配備される）。拡張の追加・削除は `home/.chezmoitemplates/pi-stock-packages` を編集する。詳細は [agent-config-generation](../spec/agent-config-generation.md) の「pi のプロファイル」。

## この機械の kcage の片付け（任意・利用者が行う）

stock にしても kcage は残る。使わないなら次の順で片付ける（いずれも sudo が要るので AI は実行しない）。

1. 作った箱があれば `kcage rm`（箱ごと）。
2. `kcage uninstall --dry-run` で消える範囲を確かめ、よければ `kcage uninstall`（配備コピー・sudoers の雛形・許可表。Incus 本体は消さない）。
3. Incus 自体が不要なら、別途 apt で外す（この機械の他の用途を確かめてから）。

## 再開の手引き

| 再開したいこと | 入口 |
| --- | --- |
| 自作の基盤へ全部戻す | `~/.config/chezmoi/pi-profile` を消して `chezmoi apply`。ソース・docs・試験は残っている |
| kcage の clone モードを続ける | 原本の `kcage-clone-mode/contract-and-decisions.txt`（決定・段階）→ `api-contract.txt`（署名・担当・波）。枝は上の表。第 2 波（`repos`）から。基は `feature/kcage-clone-gitrun`（`policy` の枝との merge が要る）。**先に S0**（導入済みの箱で、悪性 bundle の拒否・転送・性能の実機確認）。接続の注意: 枝どうしの merge は確認が要る |
| ツール隔離（pi はホストに残し、ツールだけ隔離）を試す | [実現性の調査](../research/agents/tool-isolation-feasibility-2026-11.md)と、原本の `tool-isolation/spike-brief.txt`（最小プロトタイプの依頼文。未着手）。鏡写し cwd・`PI_REMOTE_EXEC`・フェイルクローズ |
| 同種の OSS を再評価する | [評価](../research/agents/oss-sandbox-evaluations-2026-11.md)と原本 |
| 隔離の線引きを考え直す | ADR-0030 の「設計の原則」（3 つの問い・4 段階・データの流れの向き） |

## 学び（実測・調査で確かめたこと）

- **制限つき Incus プロジェクトでは足りない**: デバイス作成権限があれば、`proxy` デバイスで管理ソケットを箱へ出せて完全に脱出できた（[実測 T10](../research/agents/incus-dev-environment.md)）。利用者を `incus-admin` に入れない制御面（root の補助＋sudoers＋許可表）が要った。
- **リポジトリを rw で重ねる設計は、ホストの git が箱の書いた設定を実行する経路を生む**: `.git/hooks`・`config`・`commondir`・`mv .git`（bubblewrap で再現。`.git` を自分自身へ bind して封じた）・入れ子の `.git`・worktree の gitdir。**ホストの `.git` を箱に見せなければ、この種類は構造的に消える**（clone モードの動機）。
- **`git fetch <bundle>` は、git 2.43 では `fetch.fsckObjects=true` でも fsck しない**（`.git`・`.GIT`・`git~1` の tree と `.gitmodules` の symlink が通る）。取り込み後の `git fsck --strict` と独自の走査が要る（inbox の実装と試験）。
- **WSL2**: 全ディストロが VM とループバックを共有する（専用ディストロの隔離は弱い）。WSL の中の Incus の箱は netns が別で、ホストの `127.0.0.1` に届かない（T4）。入れ子の Docker の GPU は CDI 方式で通る（T3）。FORWARD の DROP・`/run` の tmpfs・`incus exec` の補助グループなど、実機でしか出ない不具合が 12 件以上あった。**WSL2 は Microsoft が隔離境界とみなさない**。
- **主ディストロに Incus を入れたあと、2 つ目の WSL ディストロで Incus を初期化すると、`incusbr0` が衝突して箱が通信できなくなる**（ネットワークの共有）。
- **同種の OSS**（coi・isx）は、制御面の分離・GPU・WSL2 の要件を満たさず、規模は kcage の 9〜17 倍で、保守者は実質 1 人。ただし、coi の「親ディレクトリの固定」は kcage の欠陥（`mv .git`）の発見につながった。
- **ツール隔離**は pi の公式の型で実現可能（7 ツールの `operations`。grep だけ自作。判定は実行より先）。ハーネスのローカル前提（判定器の文字列比較・git・worktree・台帳・子エージェント）は「鏡写し cwd」で大半を回避できる見込み。
- 試験の登録漏れ・並列 worker・全件検査の排他など、**並列実装の運用の知見**は [orchestration](../spec/orchestration.md) に残っている。

## 未検証の一覧（実機で確かめなかったこと）

kcage の実機（導入済みの箱）での次の項目。Incus が disk デバイスを浅い順にマウントするか・`.git` の pin が効くか／箱の root 相当（`docker` グループ）が重ねを外せるか／箱の中のフルガード（`kcage pi`）／WSL 側へ届かない確認／`idmap_isolated` と資源上限／ブローカー `aws`・`hf-cache`・本物の Copilot トークン／認証つきプロキシ・TLS 検査のある環境／再起動後の復帰／`kcage init`・`kcage uninstall` の実機／Windows 側。clone モード全体（seed・collect・take・feed・view・ws の箱での動作と性能）は**実機で一度も動かしていない**（単体・実 git の試験のみ）。

## 関連

[ADR-0030](../adr/0030-freeze-agent-stack-return-to-stock-pi.md)・[ADR-0028](../adr/0028-per-repo-agent-container.md)・[CHG-0064](0064-dev-environment-isolation.md)・[同種の OSS の評価](../research/agents/oss-sandbox-evaluations-2026-11.md)・[ツール隔離の実現性](../research/agents/tool-isolation-feasibility-2026-11.md)・[原本（archive）](../research/archive/2026-11-agent-stack/README.md)
