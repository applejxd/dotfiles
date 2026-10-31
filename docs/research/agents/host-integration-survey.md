# ホスト（Orca・Zed・Herdr）の調査と、pi との分担

場所ごとに使うホスト（エージェントを置く端末・エディタ・IDE）が違っても、同じ pi を使うために、各ホストの機能と、pi が受け持つ範囲を調べた記録。
[CHG-0054](../../change/0054-containment-and-async-approval.md) の段 8 の根拠にする。

> 現在の総合判断は案件（CHG-0054）の候補比較表が正本。ここは、時点の事実と、それに対する推測を分けて残す。

## 記録 HO1 — 2026-10-31（公式資料と手元の実物の読み取り。ホストの実機の試験はしていない）

### 問い

1. 場所ごとにホストが違う（スマホ接続できるデスクトップ型ホストを使う場所と、常駐スキャンの負荷でそれが重く、軽量なエディタの端末スレッドだけを使う場所）。同じ pi を使うために、pi とホストの役割を、どう分けるか。
2. 端末の常駐層（tmux、Herdr）を挟むべきか。

### 対象と環境

- Orca 1.4.245（手元で動作）。Zed と Herdr は、公式 docs（取得日 2026-10-31）。pi 1.4.0（手元）。
- 実機: WSL。**ホストの実機の試験はしていない**。Windows ネイティブは未検証。
- 利用者の報告（未計測）: デスクトップ型ホストが、常駐スキャンの負荷で重い環境がある。Zed も、長く使うと少しずつ重くなる。実行は WSL が大半で、Windows ネイティブは少数。
- 外部の内容は信頼できない入力として扱った。**事実**（本文を読んだ）、**抜粋**（検索結果の抜粋だけ）、**推測**を分ける。

### Orca

| # | 事実 | 種別・出典 |
| --- | --- | --- |
| 1 | orchestration は、Settings → Experimental で有効にする**実験機能**。Run（名前空間と受信箱）・Task・Dispatch（1 回の試行）・Message・Gate で構成する | 事実。<https://www.onorca.dev/docs/cli/orchestration>、`orca skills get orchestration --full` |
| 2 | worker は、起動時に注入される指示に従い、自分の端末から Orca CLI で、heartbeat（既定 5 分）、`ask`（永続。1 回の待ちは最大 30 分。message ID で再開）、`worker_done` を送る。coordinator は `check --wait` で、FIFO の受信箱を、確認応答（ack）しながら読む | 事実。同上 |
| 3 | 「不在は証拠でない」規則。停止・放棄・再試行は、プロセスの終了の肯定的な証拠があるときだけ。受信箱の空や時間切れは、検査点にすぎない | 事実。同上 |
| 4 | `worker-start --agent` の例は claude、codex、cursor、antigravity、muse、zcode、opencode。pi は対応エージェント。pi への `--model` 指定は、現状は拒否される（Issue #26971・#36544。PR は open） | 事実（`--help`）。pi の対応と Issue は抜粋 |
| 5 | 権限の設定は Manual / Auto / Yolo。Auto は Claude と Codex だけ | 事実。<https://www.onorca.dev/docs/settings> |
| 6 | pi の**構造化チャット**（`pi --mode rpc`）の PR 本文: 「Pi は full access のみ。承認方針の拡張は注入しない。拡張の質問は既存の質問・承認カードを使う」。**この経路の話で、端末経由（WSL を含む）に当てはまるかは未確認** | 事実（PR #25851 本文）。適用範囲は推測 |
| 7 | 構造化チャットは、ローカルの macOS・Linux・ネイティブ Windows と、ペアリングした Orca Server だけ。**WSL・SSH は端末のまま** | 事実。<https://www.onorca.dev/docs/agents/native-chat> |
| 8 | 通知: エージェントの完了・入力待ちで通知し、スマホにも push する。構造化チャットの成功した完了は、未読の印だけで、システム通知も音も出さない。承認待ちの push の一般保証は、読んだ範囲に無い | 事実。<https://www.onorca.dev/docs/notifications>、<https://www.onorca.dev/docs/mobile> |
| 9 | WSL 内の `orca-ide` は、bash のランチャー。Windows の interop で `powershell.exe -ExecutionPolicy Bypass -File orca-wsl-bridge.ps1 … orca.exe` を呼ぶ。つまり、**CLI は境界（Fence）の外の Windows プロセス**になる | 事実（手元の実ファイル） |
| 10 | Orca CLI は、他のエージェントを起動できる（`agent launch --agent … --prompt …`）。手元の判定の規則に `orca-ide` は無い（allow・ask・deny のどれでもない） | 事実（`--help`、`common.toml.tmpl` の検索） |
| 11 | `pis` の Fence は、`ORCA_PANE_KEY` を内側へ渡さず、`~/.pi/agent` も読めない。Orca の状態表示の拡張は、Fence の内側では使えない | 事実（[pi の拡張](../../spec/guard/pi-extensions.md)、[pi のサンドボックス](../../spec/guard/pi-sandbox.md)）。内側から Orca CLI が動かないことは**推測（未試験）** |

### Zed

| # | 事実 | 種別・出典 |
| --- | --- | --- |
| 12 | Parallel Agents は、Threads Sidebar で、複数のスレッドと Terminal Thread を**人が**並べて動かす UI。スレッドごとにエージェントを選べる。worktree の隔離は、人が選ぶ（新しい worktree は detached HEAD）。エージェント同士の調整・受信箱・DAG は、読んだ範囲に無い | 事実。<https://zed.dev/docs/ai/parallel-agents> |
| 13 | Terminal Thread は、CLI/TUI が、認証・モデル・ツール・スキル・MCP の設定を持つ。**Zed Agent の権限・プロファイルは自動では適用されない** | 事実。<https://zed.dev/docs/ai/terminal-threads> |
| 14 | Terminal Thread の通知は、端末の BEL を使う。公式 docs に、pi 用の例（`agent_end` で `\x07` を書く拡張）がある | 事実。同上 |
| 15 | External Agents（ACP）の権限は、Zed の転送の権限が適用され得る。pi は ACP Registry に載っている（pi-acp） | 事実。<https://zed.dev/docs/ai/external-agents> |
| 16 | Zed のサンドボックス（1.14〜）は、Zed Agent の terminal と fetch のツールだけ。External Agents と Terminal Thread には効かない | **抜粋**（docs 本文は URL の誤りで取得失敗）。<https://zed.dev/docs/ai/sandboxing> |
| 17 | 背景のサブエージェントの権限要求が、親のスレッドに出ず、無言で止まる報告（OpenCode を ACP で使った例） | 第三者の報告。<https://github.com/zed-industries/zed/discussions/49590> |
| 18 | 長時間使うとメモリが増えるという報告が多数あるが、原因は報告ごとに別 | 第三者の報告（抜粋）。このリポジトリの環境の原因は**未確認** |

### Herdr

| # | 事実 | 種別・出典 |
| --- | --- | --- |
| 19 | **Herdr TUI（端末アプリ。自前のサーバー）と、Herdr App（別のプログラム。herdr-core 上）は、別製品**。エージェントを共有しない | 事実。<https://herdr.dev/> の FAQ |
| 20 | TUI では、サーバーがパネルとプロセスを持ち、クライアントが attach する端末 UI。detach してもサーバーとエージェントは動き続ける。複数クライアントを同時に attach できる | 事実。<https://herdr.dev/tui/docs/concepts/> |
| 21 | サーバーを再起動すると、プロセスは消え、配置だけ復元される。対応するエージェントは、会話を再開できる（`[session] resume_agents_on_restore = false` で止められる） | 事実。<https://herdr.dev/tui/docs/session-state/> |
| 22 | pane の中の OSC のタイトルは Herdr で止まる。`[ui] window_title` に `{terminal_title}` を入れると、外側の端末に出せる | 事実。<https://herdr.dev/tui/docs/configuration/> |
| 23 | 制御用のソケットがあり、カスタムコマンドへ `HERDR_SOCKET_PATH` などを渡す。App の例では、エージェントが別のエージェントを起こせる（`hc run`） | 事実（configuration と App のホームページ） |
| 24 | Windows ネイティブは beta。ConPTY を使う。統合のインストール対象に Pi を含む | 事実。<https://herdr.dev/tui/docs/windows-beta/> |
| 25 | このリポジトリの導入（`run_after_140`）は、Herdr の統合を `copilot` か `claude` だけに入れる。Pi の統合は配備していない | 事実（スクリプトを読んだ） |
| 26 | tmux の中のエージェントは、tmux 越しに OSC 7501 を報告できない（App の FAQ。pi の docs も、tmux・screen は通さないと明記） | 事実 |

### OSC 7501（Program Status Protocol）

| # | 事実 | 種別・出典 |
| --- | --- | --- |
| 27 | 端末のエスケープシーケンス。状態は `idle` / `working` / `blocked` / `done` / `error`。`blocked` は `kind=permission` などと、理由（base64）を伝えられる。公開は 2026-10-06。**記事は完全な規格本文ではない**（寿命・上限・機能検出などは別リンクで未取得） | 事実（記事）。<https://mitchellh.com/writing/program-status-osc7501> |
| 28 | **pi 1.4.0 は、これを内蔵している**。`working`（実行・圧縮中）、`blocked`（拡張のダイアログか、ログイン待ち）、`done`、`error`、`idle`。端末が対応の問い合わせに答えたときだけ送る。`PI_PROGRAM_STATUS=1` で強制し、`0` で止める | 事実（pi の `terminal-setup.md`）。コードも確認 |
| 29 | 拡張の `select` / `input` / `editor` は `kind=question`、`confirm` は `kind=permission` で `blocked` になる。**`custom()` は `blocked` にならない**（自作の `ask` の質問パネルと、確認の全文ビューアが該当） | 事実（pi の `interactive-mode.js` を読んだ）。実機の送信は**未検証** |
| 30 | 自作側には、完了時（`agent_settled`）・確認の前・質問の前に BEL がある（TUI のときだけ） | 事実（`notify` 拡張、`harness/index.ts`、`ask` 拡張） |

### 事実と推測の区別

- **取り下げた最初の案**: 「OSC 7501 を自作して足す」は、pi 本体の docs を先に見なかったための誤りで、取り下げた（事実 28）。ほかに、状態名（`failed` ではなく `error`）、Herdr TUI と App の混同、も直した。別系統の `review` の指摘を、実物で確かめて反映した。
- 推測: どのホストも pi のツール呼び出しを見られないので、**pi の判定と境界を強制できるのは、pi の中だけ**（事実 6・13・16 から）。調整・永続・通知はホストに寄せられるが、承認と実行結果の正本は、pi 側に残すのがよい。
- 推測: 常駐層を挟むと、環境変数と制御ソケットを通じた、外側の制御能力への到達が、新しい危険になる（事実 23 から）。承認画面へキー入力を送れる経路は、自己承認になり得る。
- 反例・限界: Orca は、永続した受信箱と通知で、自作の `guarded_task` より強い（事実 2・3・8）。ただし実験機能で、WSL の構造化チャットが使えず、CLI が境界の外を通る。

### 未検証

- 軽量なエディタの端末スレッドで、pi の内蔵 OSC と BEL が通知になるか（端末が問い合わせに答えるか）。
- tmux・Herdr が、pane の BEL を外側へ通すか。Herdr の OS 通知が、WSL の中から Windows に届くか。pane の環境変数が、サーバー由来かクライアント由来か。
- 境界の中の pi から、外側の制御ソケット（tmux・Herdr）に届かないこと。**既定の置き場では、[HO2](#記録-ho2--2026-10-31境界の内側から外側の制御ソケットに届くか) で届かないことを確かめた**。置き場を変えた場合、環境変数の継承、実際のサーバーへの接続は未検証。
- ホストの実際の負荷（常駐スキャンの負荷の原因が、ホストなのか作業自体なのかも不明）。
- Fence の中の worker が Orca と話せるか。WSL を Orca Server にしたときの構造化チャット。
- Windows ネイティブの全部。pi の内蔵 OSC と自作 UI の組み合わせの実際の送信。

## 出典

- Orca: <https://www.onorca.dev/docs/cli/orchestration>、<https://www.onorca.dev/docs/settings>、<https://www.onorca.dev/docs/agents/native-chat>、<https://www.onorca.dev/docs/notifications>、<https://www.onorca.dev/docs/mobile>、<https://github.com/stablyai/orca/pull/25851>
- Zed: <https://zed.dev/docs/ai/parallel-agents>、<https://zed.dev/docs/ai/terminal-threads>、<https://zed.dev/docs/ai/external-agents>、<https://zed.dev/docs/ai/sandboxing>（抜粋のみ）、<https://github.com/zed-industries/zed/discussions/49590>
- Herdr: <https://herdr.dev/>、<https://herdr.dev/tui/docs/concepts/>、<https://herdr.dev/tui/docs/session-state/>、<https://herdr.dev/tui/docs/configuration/>、<https://herdr.dev/tui/docs/windows-beta/>
- OSC 7501: <https://mitchellh.com/writing/program-status-osc7501>。pi のターミナル設定のドキュメント（手元の 1.4.0 の `terminal-setup.md`）
- 関連: [Zed・Orca から `pis` を使う方法の調査](zed-orca-pis-integration.md)、[pi をオーケストレーターとして使う調査](pi-orchestrator-survey.md)、[承認の設計と封じ込め](approval-containment-survey.md)

## 記録 HO2 — 2026-10-31（境界の内側から、外側の制御ソケットに届くか）

### 問い

`pis`（Fence 付き）の内側の pi から、外側の tmux・Herdr の制御ソケットに届くか。届くなら、別のペインの読み取りや、承認画面へのキー入力（自己承認）の経路になり得る（CHG-0054 の未解決点 9）。

### 方法・条件

- 対象: pi 1.4.0、Herdr 0.9.1（手元。`herdr status` が示す既定のソケットは `$HOME/.config/herdr/herdr.sock`）、tmux（mise で導入）。WSL。
- 外側（Fence の外）に、3 つのダミーのリスナー（作業ツリーの中のファイルのソケット = 対照、抽象ソケット、127.0.0.1 の空きポート）を、Python で立てた。**実際の tmux・Herdr のサーバーは起動していない**。
- 内側では、`pis -p` で、検査スクリプトを 1 回だけ実行させた。パスの有無、環境変数の有無（値は出さない）、各ソケットへの接続の試行だけで、何も送らない。同じスクリプトを外側でも走らせ、基準にした。

### 観測（出力の抜粋。ホームは `$HOME`）

| 項目 | 外側（基準） | 内側（Fence） |
| --- | --- | --- |
| `$HOME/.config/herdr`（Herdr の既定のソケットの置き場） | exists | **absent** |
| `/tmp/tmux-<uid>`（tmux の既定の置き場） | exists | **absent** |
| `/run/user/<uid>` | exists | **absent**（`XDG_RUNTIME_DIR` は、内側用の `/tmp/fence-runtime-…`） |
| `tmux`・`herdr` のバイナリ | 見える | 見える |
| `ORCA_PANE_KEY` | set | unset |
| 対照: 作業ツリーの中のファイルのソケット | CONNECTED | CONNECTED |
| 抽象ソケット | CONNECTED | **ConnectionRefusedError** |
| 127.0.0.1 の空きポート | CONNECTED | **ConnectionRefusedError** |

リスナーの記録は、外側の基準で 3 件（ファイル・抽象・TCP）、内側の試験で対照の 1 件（ファイル）だけが accepted。内側の `pis` は、検査の前に境界チェックを走らせ、合格した。

### 結論

- **既定の置き場（Herdr、tmux、`/run/user`）と、抽象ソケット、127.0.0.1 の任意のポートには、境界の内側から届かなかった。** 対照は届いたので、検査自体は有効。
- 限界（推測を含む）:
  - `TMUX` と `HERDR_*` は、この試験のセッションで未設定だった。**環境変数の継承は試していない**（コードの読みでは、`pi.py` はこれらを除外していない）。
  - ソケットの置き場を、作業ツリーの中や許可した場所へ設定すると、届く（対照のとおり）。
  - 内側で、別の tmux・Herdr を起動することはできる（バイナリが見える）。それは内側に閉じる。
  - 実際の Herdr・tmux のサーバーへの接続と、承認画面へのキー入力は試していない。Windows は未検証。

### 採用条件への反映

- 層を挟むときは、制御ソケットを既定の置き場に置く。作業ツリーの中や、許可した場所へ置かない。
- 念のため、`HERDR_*` と `TMUX` を内側へ渡さない（多層防御。置き場の設定ミスと、将来の置き場の変更への備え）。
