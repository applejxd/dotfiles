# CHG-0030: away-shift を pi（フルガード）で、無人でも止まらずに動く形にする

- **状態**: Exploring
- **更新日**: 2026-10-22
- **基準**: コミット 171cf25、pi 1.3.0。`away-shift` は Claude Code・Copilot CLI を前提に書かれ、`~/.claude/skills/` から pi にも読み込まれる

## 目的と非目的

- **目的**: 利用者が席を外している間、`pis`（フルガード）の上で `away-shift` が、
  (1) 確認の画面で止まらず、(2) 自分を起こし続け、(3) 戻ってきた利用者に止められ、(4) 作業を `.tmp/away-shift/` に閉じる、ように動く
- **非目的**: OpenCode 向けの最適化（[CHG-0016](0016-away-shift-opencode.md)。OpenCode は撤去の方向で、この案件は pi だけを扱う）。
  Claude Code・Copilot CLI の動作の変更。深層学習ジョブの再開の運用（CHG-0016 の段 2）。子エージェントへの作業の移譲（本体を fork しない方針は変えない）

## 実施計画

段ラベルは `P1`〜`P3`。状態は 2026-10-22 時点。

| 段 | 解決したいこと | 内容 | 状態 |
| --- | --- | --- | --- |
| P1 | pi が、スキルの「再開・停止・復帰の手段」の表に無い。`preflight.py` は Claude Code の hook にだけ問い合わせる | `resume.md` に pi の手段（`bg_run` / `bg_kill`）を足す。`preflight.py` に pi の判定器を使う方式を足す。`SKILL.md`・`unattended.md` に pi の記述を足す。境界は変えない | 完了（`test_preflight` 32 件通過） |
| P2 | pi では、スキル自身のコマンドがすべて確認になる。無人だと、最初の `init` で止まる | `[pi.skill_scripts.allow]` に `away_guard.py` と `preflight.py` を足す（書き込み先を `.tmp/away-shift/` に閉じる検査つき）。`sleep` を許可に足す。`log` が、`$(…)` と heredoc を使わずに記録を渡せる形を足す。**判定器の許可の境界を変えるので、実装の前に `review`** | 完了（`review` 2 回。P2a: `away_guard.py` の閉じ込め、P2b: 許可規則と上限つき `sleep` 。`test/agents/` 3945 passed。最終レビューの指摘を反映済み） |
| P3 | pi は `.tmp` の外でも `write` / `edit` が確認なしで通る。「リポジトリ本体を書き換えない」が指示だけになる | 専用の役割 `away`（`default = "deny"` で確認を出さず、書き込みを `.tmp/away-shift/` に限る）を検討する。判定器に、役割ごとの書き込み範囲を足す変更が要る | 保留（P2 の結果と、CHG-0029 の worktree の方針を見てから） |

状態: 未着手 / 進行中 / 完了 / 保留 / 見送り

## 現在地

実測（2026-10-22。`implementer` 役、`bypass` なし、判定器 `decide` に直接問い合わせた。`.tmp/probe_away.py` と `.tmp/probe_away2.py` は使い捨て）。

- **スキルのコマンドは、すべて `ask`（`default`: どの規則にも当たらない）**:
  `away_guard.py` の `init` / `check` / `log`、`preflight.py`、`uv run --no-project python …`、`timeout 20m pytest …`、`mkdir -p .tmp/away-shift/…`、`cp … .tmp/away-shift/…`、`sleep 600`
- **`write` / `edit` は、作業ツリーの中ならどこでも allow**（`.tmp/away-shift/` に限らない。`home/dot_config/pi/harness/index.ts` への `write` も allow）。
  Claude Code の hook にある「`.tmp` だけ免除」とは違い、pi では「リポジトリ本体を書き換えない」がスキルの指示だけになる
- **`bg_run` は bash と同じ判定を通る**（`docs/spec/guard/pi-guard.md`）。`sleep` は既定で確認になる（`guarded_bash` は 10 秒を超える `sleep` を拒むが、`bg_run` の中は許される）
- **再開**: `bg_run` で `sleep` を起動して応答を終えると、完了でアイドルのまま自動再開する（実際のモデル 4 つで確認。[記録](../research/agents/pi-bg-experiments.md)の s1）。
  **停止**: `bg_kill` は再開を起こさない（同 s2）。**復帰**: 利用者のメッセージで新しいターンが始まる。このセッションでも、`bg_run` の完了通知でターンが再開することを何度も確認した。
  **未確認**: TUI での見え方、`sleep` を数十分にしたときの上限
- **確認の待ち**: RPC クライアント（Zed など）は 5 分で拒否になる。TUI の汎用の確認の期限は、読んだ範囲では見当たらない（コミットの確認は 15 分）。TUI で離席すると、確認で止まりうる
- **子エージェント**: pi の `guarded_task` には、`abort`（現在のラウンドの停止）と `close` がある。`unattended.md` の「サブエージェントを終了させる手段が無い」は、pi には当てはまらない。
  子は利用者に質問できない（確認は `blocked` として親へ返る。応答を待ち続けない）
- **`away_guard.py` の呼び方の差**: スキルは `uv run --no-project python <script>` を案内するが、pi の許可規則の runner は `python3`（`uv run` を runner にしない理由は `common.toml.tmpl` のコメント）。
  `log --text "$(cat <<'EOF' … EOF)"` は、`$` と heredoc を含むので、判定器が allow にしない

## 未解決点

- `away_guard.py` の書き込みが、`.tmp/away-shift/` の外へ出ないか（run_id・シンボリックリンク・`--goal` などの文字列）。許可に載せるには、書き込み先の閉じ込めを確かめる必要がある
- `preflight.py` の判定を、pi では何に合わせるか。pi の判定は `default = ask`（規則に無い＝確認）で、Claude Code の hook（規則に無い＝沈黙＝許可）と意味が違う。pi では「`ask` を実行しない」だけで、スキルの普段の操作（`mkdir`・`cp`・テスト）の多くが「実行しない」になる
- 無人で動かす実行形態: `pis --bypass`（確認を出さない。deny と誘導は効く）で動かすなら、確認で止まらない。ただしスキルの「承認の有無に関わらず、不可逆・外部・環境変更はしない」は、スキルの指示と `preflight.py` だけが守る
- P3 の役割 `away` と、役割ごとの書き込み範囲（CHG-0029 で見送った編集範囲の強制と同じ機構）

## 次の調査・実験

- P1 は、境界を変えないので、すぐ実装できる（スキルの文書と `preflight.py`、試験）
- P2 の許可規則は、`imozuru` の許可規則（[docs/spec/imozuru.md](../spec/imozuru.md#pis-の許可規則)）と同じ作り方にする。実装の前に `review`
- 実機（TUI の `pis`）で、`bg_run` の `sleep` による自己ペースのループが、数サイクル回ること（利用者の端末）

## 評価基準

- **必須**: 確認の画面で止まらない（無人）。実行中の実験を除き、期限と STOP ファイルで新しい実験を始めない。書き込みが `.tmp/away-shift/` に閉じる（P2 の許可規則で、スクリプトの書き込みが）。許可の境界を、`away-shift` のためだけに広げない
- **望ましい**: pi で、スキルの既存の手順がほぼそのまま通る。Claude Code・Copilot CLI の動作を変えない

## 候補比較

| 論点 | 候補 | 支持する根拠 | 不利な点・反証 | 未検証点 | 扱い | 次の確認 |
| --- | --- | --- | --- | --- | --- | --- |
| 再開の手段 | `bg_run` で `sleep <NEXT_WAKE_SECONDS>` を起動し、応答を終える。完了で自動再開 | 実際のモデルで確認済み。追加の仕組みが要らない | 数十分の `sleep` の上限、TUI での見え方が未確認。1 件ごとに 1 ターン | `sleep` の長さの上限 | 有望（推奨） | 実機 |
| 再開の手段 | 外部のスケジューラ（cron など） | 確実 | 環境を変える。スキルの制約に反する | — | 見送り | — |
| 事前判定 | `preflight.py` が pi の判定器（`decide`、役割 `implementer`）に問い合わせる | 実際の判定と同じ。予測がずれない | `default = ask` が多く、「実行しない」が増える | 許可に載せる範囲 | 有望（推奨） | P2 |
| 確認で止まらない方法 | スキルのスクリプトと `sleep` を許可に足す（P2） | 確認が出なくなる。境界の変更は最小 | 許可の追加。`away_guard.py` の閉じ込めの確認が要る | `away_guard.py` の書き込み | 有望（推奨） | `review` |
| 確認で止まらない方法 | `pis --bypass` で起動する | 仕組みが要らない | 確認がすべて通る。スキルの指示だけが守りになる | — | 保留（併用は可） | — |
| 確認で止まらない方法 | 専用の役割 `away`（`default = "deny"`、書き込み範囲を限る） | 確認が出ず、書き込みも判定器が閉じる | 判定器に、役割ごとの書き込み範囲を足す変更が要る | 判定器の変更の大きさ | 保留（P3） | CHG-0029 の結果 |
| 記録の渡し方 | `away_guard.py log` に、run ディレクトリの中のファイルを読む形（`--note-file`）を足す | `$(…)` と heredoc が不要。`write` ツールでファイルを作れる | スクリプトの変更。任意のパスを読まない検査が要る | — | 有望（推奨） | P2 |

扱い: 未評価 / 検証中 / 有望 / 採用 / 保留 / 見送り

## 仕様への変更案

| 変更対象 | 変更前 → 変更後 | 理由・証拠 | 適用結果 |
| --- | --- | --- | --- |
| `references/resume.md` | CLI の表に pi の行を足す。`bg_run` の手順（予約・停止・復帰）を書く | 実測（上の「現在地」） | 未適用（P1） |
| `scripts/preflight.py` | `--judge pi`（`decide.py` を使い、役割・bypass を指定できる）を足す。既定は Claude Code の hook のまま | 判定器の差 | 未適用（P1） |
| `SKILL.md`・`references/unattended.md` | pi の記述（呼び方は `python3`、`guarded_task` の `abort`、確認の待ち）を足す | 実測 | 未適用（P1） |
| `common.toml.tmpl` の `[pi.skill_scripts.allow]` と `[pi.shell] allow` | `away_guard.py`（`init` `check` `log` `status`）、`preflight.py`、`sleep` を足す | 無人で止まらないため | 未適用（P2。`review` が先） |
| `scripts/away_guard.py` | `log --note-file`（run ディレクトリの中に限る）。書き込み先の閉じ込め | P2 | 未適用 |

## 重要な更新

- **2026-10-22**: 案件を起こした。`away-shift` を pi で動かすための差を、判定器への問い合わせと記録で確かめた（スキルのコマンドがすべて確認になる、`write` が `.tmp` に限られない、`bg_run` で再開できる）。
- **2026-10-22（実装）**: レビュー 1 回目の BLOCKER 2 件（`away_guard.py` の書き込み先が未固定、Python の `decide` は実際の TS 判定器と違う）を反映し、開始前に閉じ込めを直した。`sleep` は全体の許可ではない上限つきのサブコマンドにした。最終レビューで、読み取り専用の役割からも到達できる点を受け入れ、停止済みの run の `check` を拒否し、`init --force` を廃止することにした。
- **見送りと限界**: 同じ作業場を変更できる敵対的な並行プロセス（親ディレクトリの差し替えの競合）は防いでいない（`O_NOFOLLOW` は最終要素だけ）。`--note-file` は work/ 内の秘密をログへ複写できる（内容の秘匿検査は無い）。実際の pis（TS 版）と Windows、長時間の `bg_run` は未確認。
