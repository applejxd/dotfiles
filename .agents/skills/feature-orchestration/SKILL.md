---
name: feature-orchestration
description: "ai/* worktree を起票して worker に実装を切り出し、検証・監査後に scripts/ai_pr.py で PR 提出・Auto-Merge・片付けまで進める手順。「worker に任せて」「並列で進めて」「feature を切って実装して」「PR を出して統合して」「片付けて」で使う。調査・レビュー・計画だけの委譲 (scout / reviewer / oracle) や、単発の小さな変更には使わない。"
---

# `ai/*` の実装と PR 統合 (起票 → worker → 確認 → `ai_pr` → 片付け)

独立した実装を worker に切り出し、`scripts/ai_pr.py`（専用 GitHub App）と 3 OS CI の `ci-gate` を通して `develop` へ Squash Auto-Merge するまでの手順（[ADR-0044](../../../docs/adr/0044-github-app-auto-merge-and-3os-ci.md)）。運用は pi の `subagent` ツール。
ここは**手順と落とし穴だけ**。事実・雛形は資料へ（どれも SKILL.md から 1 段）:
[pi-facts.md](references/pi-facts.md)（権限・子の事実）・[worker-contract.md](references/worker-contract.md)（依頼の契約）・[bundle-and-stack.md](references/bundle-and-stack.md)（束ねる・積み重ねる）・[pi-subagents.md](references/pi-subagents.md)（子の起動の詳細）・[plan-contract.md](references/plan-contract.md)（計画から自走へ移る契約）。

## 使う条件

- 利用者が委譲を禁止した範囲では、起動条件やコミット前の監査手順より禁止を優先し、子を起動しない。別の規則で独立監査が必須なら、未監査のままコミットせず報告する。
- 最初の編集前に、常設の指示に沿って、親が直接実装するか、`worker` に 1 件だけ渡すか、並列で渡すかを決める。設計・担当範囲・禁止事項・合格条件が固まり、引き継ぎと再検証に見合う利点があるなら、1 件でも委譲する。
- 設計判断が連続する作業・利用者と対話で詰める設計は、親で行う。設計が固まった時点で残りを渡せるか再判定する。調査・レビュー・計画だけなら worktree を切らない。調査の担当と並列の可否、レビューや計画で子を呼ぶ条件は常設の指示に従う。

## 工程

1. **分ける**: 1 worktree = 1 `ai/<slug>` = 1 worker。並列は担当ファイルが重ならず、共有のインターフェースとテストの期待値が固まっている場合だけ。共有ファイル（docs の索引・`scripts/verify.py`・`pi-mcp-servers.toml`）は 1 人か親だけが触る。依存は契約の「前提」に書き、先行の成果がないと進められない作業は待つ。
2. **起票**: `uv run --no-project python scripts/ai_pr.py start <slug>`（名前は英小文字・数字・`.`・`_`・`-`）。`develop` 基点で `ai/<slug>` と `.tmp/worktrees/<slug>/` が作られる。未統合の `ai/<A>` の変更が要る B は、`--base ai/<A>` を指定する（[積み重ね](references/bundle-and-stack.md)）。
3. **依頼**: worktree を作った**あとで**、契約を worktree の `.tmp/keep/plan/<slug>.md` に書く（同時だと作成が失敗する）。続けて `subagent({ agent: "worker", cwd: "<worktree の絶対パス>", async: true, options: { timeoutMs, checkpointBeforeDeadlineMs }, task: "契約 … を読み、…" })`。`task` は契約のパスと 1〜2 行だけ。契約の中身は [worker-contract.md](references/worker-contract.md)。コミット前の監査が必要な変更は、子にコミットさせない。権限や境界を**緩める**変更は、反例の試験を先に足して現状で落ちることを確かめてから直し、前後で `reviewer` に見せる。
4. **確認**: 完了通知で再開する。**子の自己申告は信じず、親が同じコマンドを再実行する**（子が「確認していない」と書いたことは、未確認のまま）。複数ファイルの変更は、コミット前に新しいコンテキストの読み取り専用 `reviewer` に監査させる。挙動・設計・互換性・権限・安全に影響する変更は、数行の差分でも同じ手順で監査する。親は要件・差分ファイル・検査結果・未検証事項を渡し、実装者の自己評価は渡さない。担当外のファイルが変わっていないか `git diff --stat`。整形 hook が書き込み直後にファイルを空にすることがあるので、`git add -A` のあと `git diff --cached --numstat` で行数の急減を見る。
5. **登録の漏れを先に潰す**: 新しい試験ファイルは `scripts/verify.py` の該当の `Rule` へ（対象が実在するか確かめてから書く。ほかの枝と隣り合わない位置）。`uv run --with pytest --with pyyaml --no-project pytest test/test_verify.py -q`（2 秒）で確かめる。docs を触ったら `lint_docs.py`・`check_refs.py`（`home/dot_agents/skills/sdd-docs/scripts/`）。日付は `date '+%F %H:%M'` で確かめる。
6. **全件検査**: `bg_run` で `mise run verify:all` を**1 本ずつ**（完了通知を待つ。worker の試験が走っている間も重ねない。重なると負荷で時間依存の試験が落ちる。落ちたら、単独で再実行して確かめる）。
7. **コミット**: `commit` スキルの形式（Conventional Commits）。
8. **PR 提出と Auto-Merge**:
   - まず事前検査: `uv run --no-project python scripts/ai_pr.py submit --cwd .tmp/worktrees/<slug> --title "<Conventional Commits>" --summary "<1〜3行要約>" --dry-run`。保護パス判定と `.github/workflows/**` 非含有を確かめる。
   - 問題なければ `--dry-run` を外して本実行する。専用 GitHub App が `gitleaks` 検査・`ai/*` への非強制 push・`develop` 向け PR 作成・Squash Auto-Merge 予約まで行い、PR 作成後は `link_pull_request` でスレッドへ紐づける。
   - **通常 PR（保護パスなし）**: 3 OS CI と `ci-gate` 通過後に無承認で自動統合される。
   - **保護パス PR（`protected: true`）**: 3 OS CI 通過後に `protected-path-approval` が `waiting` になる。PR URL と承認リンクを利用者へ報告して承認を待つ（`gh run watch` は承認待ちの間終わらないため使わない）。
   - **`.github/workflows/**` を含む変更**: App の権限でサーバ側拒否されるため `ai_pr.py submit` は使えず、利用者へ人手 push を案内する。
   - **CI 失敗時の自動修正**: 失敗ログ（T3 Code の `ci_logs` ツールまたは `gh run view --log-failed`）で原因を特定し、同一 `ai/*` 枝で修正 → 検査 → 独立レビュー → 再 `submit` を行う。自動修正は **最大 2 ラウンド** までとし、2 回で原因を絞れない／保護パスや仕様判断が要る場合は止めて利用者に報告する。
   - **`main` への昇格**: ローカルでの `git flow feature finish` は廃止。`main` 昇格と `chezmoi apply` は利用者の明示指示があるまで実行しない。
9. **後始末**: ① **片付けの前**（消える worktree で）: `git -C <worktree の絶対パス> clean -ndX` を見て、残したい資料があれば `.tmp/keep/` から本体の `.tmp/keep/<slug>/` へ写す（`.venv`・`__pycache__`・`.pytest_cache`・`.ruff_cache` は無視。再利用するスクリプトはコミットし、調査結果は `docs/research/` に書く。[経緯](../../../docs/research/agents/worktree-lifecycle-2026-11.md)）。② **マージ後**: `uv run --no-project python scripts/ai_pr.py cleanup --verify-github` を実行する（`origin` prune・本体 `develop` の `ff-only` 更新・GitHub で `merged` かつローカル先端 SHA 一致の `[gone]` 枝と worktree の自動削除。未 push コミット・dirty・open PR・未マージ close 枝は保護される）。未マージ close 枝を手動確認後に消す場合は `--branch ai/<slug> --allow-squashed` を指定する。
10. **止まらずに次へ**: PR 提出（または保護パス承認待ち報告）まで済ませたら、別件の独立作業があれば進めてよい。

## 落とし穴

- **worktree の中だけで完結させる**: 本体と他の worktree は作業ツリーの外で、`cd`・`ls`・`cat` に確認が出る（子は拒否される）。本体の内容は `git show develop:<パス>`、ほかの枝は `git show ai/<slug>:<パス>`。子へ渡す資料は worktree の中へ写す（[理由](../dotfiles-conventions/SKILL.md#feature-の-worktree-で作業するとき本体のパスへ出ない)）。
- **統合のあとの反映は `chezmoi apply`**（`chezmoi update` は使わない。事実は [pi-facts](references/pi-facts.md#取り込み反映)）。sudo が要るスクリプトで止まったら、`chezmoi apply --exclude=scripts` でファイルだけ反映し、スクリプトは利用者の端末に任せる。
- **App 秘密鍵を直接読まない**: `~/.config/dotfiles-ai` は権限ポリシーで deny。認証や PR 操作は必ず `scripts/ai_pr.py` 経由で行う。
- **`develop` の取り込み**: Ruleset は最新 base を要求する。PR が `develop` より遅れた場合は worktree 内で `git fetch origin develop && git rebase origin/develop`（または `git merge origin/develop`）してから再検査・再 `submit` する。
