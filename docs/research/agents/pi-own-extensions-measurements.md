# 自作の拡張（todo / plan / btw / activity / ask / notify / delegate-nudge）の実測と未確認

> `docs/spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw` から移した記録。移設時点で再測定していない。

## 記録 — 観測日は各文に記載（移設 2026-10-26）

- **対象バージョン**: 各文に記載（pi 1.3.0 前後）
- **環境**: 各文に記載

### 問い

自作の拡張の動作を、どの環境・版でどこまで確かめたか。何が未確認か。

### 根拠

元の文にあるコマンド・試験名（`test_pi_harness.py`・`test_pi_harness_extensions.py`・`test_btw_view.py`）と、Zed の Terminal Threads の文書。

### 結果（元の文）

- notify 行: `（[Terminal Threads](https://zed.dev/docs/ai/terminal-threads)、2026-10-21）`（Zed の Terminal Threads はフォーカス外の端末の BEL を通知にする、の出典日）
- ask 行: 「試験は `test_pi_harness.py` に足したが未実行。」（移設時点の spec の表現。試験の実行結果は未確認）
- activity 行: （2026-10-25。`sleep 9; sleep 9; …` の連結や `bg_log` の連打で待った実例から。連結はガードの既知の限界のまま）
- delegate-nudge 行: 「`own_extensions` に登録済み（`common.toml.tmpl`、N1a のコミット d8d0769）」
- delegate-nudge 行: 「試験は `test_pi_harness_extensions.py` の `test_delegate_nudge_*`（5 件。2026-10-25 の同ファイルの実行で通過）」

- `activity` の実測（Linux、偽の pi API でツールを直接動かした）: `bg_run` で ID を返し、`🤖 2 subagents / ⚙️ 1 jobs` が出る。`bg_log` が出力の末尾を返し、`bg_kill` でジョブが消えて通知が出て、子もジョブも 0 になると表示が消える。**未確認**: 実機の TUI でのフッター表示、フルガード（`pis`）の下での `bg_run` の確認（拡張のツールなので既定で確認になる想定だが未実測）、Windows の `taskkill` での停止、終了通知が実機の TUI で見えること（RPC の実モデルでは、通知でターンが再開することを確認済み。[B1](../../research/agents/pi-bg-experiments.md)）
- 実測: `btw` は print モードで、直前の会話の内容（合言葉）を踏まえて答え、セッションファイルの行数が増えないことを確認した（オーバーレイ表示は TUI でしか出ず未確認）。Git Bash では `/btw` が `C:/Program Files/Git/btw` に変換されるので、試すときは `MSYS_NO_PATHCONV=1`
- 実測: `todo` は、書き換え前の版（`toggle` 方式）で実際のモデル（`claude-sonnet-5.5`）の add / toggle / list が通った。書き換え後の版は偽のモデルでの試験（`test_pi_harness.py` の `test_todo_*`・`test_todos_*`。圧縮と再開をまたぐ復元、旧形式の読み込み、利用者の操作の永続化、フッター）までで、**実際のモデルが `set` / `texts` / `cancelled` を使い分けるかと、TUI の表示は未確認**。`plan` は読み込みまで（切り替えと確認画面は TUI でしか動かず、未確認）
- `btw` の子の入口の bullet から: **実測**（2026-10-21、tmux の pi 1.3.0）: 窓なし（全文を Container に入れる）だと、120 行の返信で画面に収まる約 28 行だけが表示され、末尾と閉じる案内が見えなかった。窓を入れたあとは 130 行を「1-32 / 130 行」で表示し、`End` / `G` で末尾に届く。**PgUp / PgDn はこの端末では効かなかった**（pi 本体が先に取ると見られる。理由は未確認）ので、Space / b を当てた。**未確認**: Windows の素の `pi` での子の起動、全画面モード、端末幅の変更時の再描画

### 考察

現在の仕様は ../../spec/guard/pi-guard.md の該当節。ここの数値・日付は観測時点のもので、再測定していない。
