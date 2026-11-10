# コーディングエージェントのオーケストレーターの横断調査（全体の上位互換はあるか）

観測日: 2026-10-22〜2026-11-01（出典ごとに取得日を併記）。依頼: 公開されているオーケストレーター・調整 UI・承認の中継・並列実行の仕組みを横断し、
このリポジトリの構成（pi + git-flow が調整の正本。Web UI は作らない）と比べる。Issue #132。
方法は、Web 検索と本文の取得だけ（**第三者のコードは実行・導入していない**）。原文は非公開の置き場に保存した。この記録の作成時に Web の再取得はしていない。

**結論の要点**: 全体の上位互換は、**確認できた範囲では見つからなかった**。部品ごとに上のものはある（[比較](#このリポジトリの構成との比較)）。

関連: [pi を AI オーケストレーターとして使う仕組みの調査](pi-orchestrator-survey.md)（O1・O2。pi の拡張と運用の型）、
[親を絞る設計](orchestrator-role-plan.md)、[CHG-0056](../../change/closed/0056-orchestrator.md)（非目的に Web UI・常駐の監督・台帳）、
[CHG-0055](../../change/closed/0055-async-approval.md)（非同期承認）、[CHG-0053](../../change/closed/0053-worktree-integration-gate.md)（統合の確認）。

## 種別と記号

- 種別: **事実**（本文を読んだ）、**抜粋**（検索結果の抜粋だけ）、**二次**（他者の要約・記事）、**推測**
- 取得日は、材料に残っていた日付。各行の最後の列

## 対象の一覧

### 調整 UI（複数のエージェントを並べて見る・動かす）

| 名前 | 種類 | できること | 出典 URL | 種別 / 取得日 |
| --- | --- | --- | --- | --- |
| Vibe Kanban | Web UI（かんばん） | 課題を板で管理。ワークスペースごとに worktree と分岐を作り、エージェントを起動。差分への行コメントを送る。公式サイトに「sunsetting（終了へ。OSS として継続）」の表示 | <https://github.com/BloopAI/vibe-kanban>、<https://www.vibekanban.com/> | 事実（README・サイト）/ 2026-11-01 |
| Claude Squad | TUI | tmux のセッションと worktree を 1 エージェントずつ割り当て、1 つの TUI で切り替える。`--autoyes`（experimental）で確認を自動承認 | <https://github.com/smtg-ai/claude-squad> | 事実 / 2026-11-01 |
| Conductor | デスクトップアプリ | 並列のエージェントを、タスクごとの worktree で動かす。Mac のみ・非公開ソース（比較記事の記述） | <https://superset.sh/compare/conductor-vs-crystal> | 二次 / 2026-11-01 |
| Crystal（現 Nimbalyst） | デスクトップアプリ | 並列の worktree で Claude Code・Codex を動かす。リポジトリの表題は「Crystal is now Nimbalyst」 | <https://github.com/stravu/crystal> | 抜粋 / 2026-11-01 |
| Orca | デスクトップ + モバイル | 複数エージェントの管理。orchestration（Run・Task・Dispatch・Message・Gate）、通知、モバイルの付属アプリ（beta） | <https://onorca.dev>（docs）、PR #25851 | 事実（docs・PR 本文）/ 2026-10-31 |
| Zed Parallel Agents | エディタ | スレッドの側面欄で、複数のスレッドと Terminal Threads を人が並べる。エージェント間の調整・受信箱は読んだ範囲に無い | <https://zed.dev>（docs） | 事実 / 2026-10-31 |
| herdr | 端末の多重化 | 端末をバックグラウンドのサーバで保持し、切断しても作業が続く。複数マシンを 1 つの窓で扱う | <https://github.com/herdrdev/herdr> | 事実（README）/ 2026-10-31 |
| Paseo | 自前ホストの Web UI | daemon がブラウザのアプリを配る。既定は `127.0.0.1:6767`。外へ出すときはパスワードとホストの許可リスト（DNS rebinding 対策）を設定する | <https://github.com/getpaseo/paseo/blob/main/public-docs/web-ui.md> | 事実 / 2026-11-01 |
| pi-web | pi 用の Web UI | ブラウザで pi のセッションを使う。複数マシンの登録。README の主張 | <https://github.com/jmfederico/pi-web> | 抜粋 / 2026-10-31 |
| Deska | GUI + モバイル | 端末・ブラウザのパネル。スマホから、中継経由で状況の確認と継続（ポートを公開しない、と記事が説明） | <https://deska.dev/blog/cli-vs-tui-vs-gui-agents> | 二次 / 2026-11-01 |

### ワークフロー基盤・タスク管理・取り込み

| 名前 | 種類 | できること | 出典 URL | 種別 / 取得日 |
| --- | --- | --- | --- | --- |
| Claude Code の Agent Teams | 公式の実験機能 | 1 つのセッションが lead になり、共有タスク表と仲間同士の連絡で、複数のセッションを調整。1 セッション 1 チーム、入れ子なし、lead は固定。無効が既定 | <https://code.claude.com/docs/en/agent-teams> | 事実（公式 docs）/ 2026-11-01 |
| Gas Town | 大規模な調整基盤 | 20〜30 体を並列に動かす。役割（Mayor・Refinery・Witness など）と、Refinery の bisecting merge queue。解説記事は「専門家向け・費用が大きい」と注意 | <https://rywalker.com/research/gastown>、<https://github.com/steveyegge/gastown> | 二次（解説の本文）/ 2026-10-31 |
| Beads（`bd`） | 依存つきの課題表 | git に紐づく課題表。`bd ready` が、未完了の依存が無い課題だけを出す | <https://beads.gascity.com/> | 抜粋 / 2026-10-31 |
| Raylabs の記事 | 運用の型 | ディスパッチ時にパスを予約し、重なるなら直列。取り込みは直列のキューで、衝突・失敗では止める（fail-closed） | <https://dev.to/raylabs/handling-git-merge-conflicts-in-multi-agent-worktrees-1em8> | 事実（2026-10-04 の記事）/ 2026-10-31 |
| Co-Coder（論文） | 研究 | 結合の強いファイルを同じエージェントに割り当てる。報告は [O2](pi-orchestrator-survey.md) の事実 6 | <https://arxiv.org/html/2606.00953> | 事実（論文の報告）/ 2026-10-31 |

### 承認・通知の中継

| 名前 | 種類 | できること | 出典 URL | 種別 / 取得日 |
| --- | --- | --- | --- | --- |
| Agent Approve（pi 用） | pi の拡張 | iPhone・Apple Watch から、ツール呼び出しを承認・拒否する（一覧の説明文） | <https://awesome-pi.site/extensions/> | 抜粋 / 2026-10-31 |
| Orca Mobile | 付属アプリ（beta） | エージェントの状態・直近の出力の確認、入力待ちへの短い返信。完了・入力待ち・承認待ちを push で通知 | <https://onorca.dev>（docs: mobile・notifications） | 事実 / 2026-10-31 |
| Omnara | 外部サービス | AG-UI の対応一覧に「Supported」として載るだけ。機能は読んでいない | <https://docs.ag-ui.com/introduction> | 抜粋 / 2026-11-01 |
| ntfy などの自前通知 | 通知の部品 | tmux のエージェントの待ちを、スマホへ push する構成の記事が複数 | <https://rogs.me/2026/02/claude-code-from-the-beach-my-remote-coding-setup-with-mosh-tmux-and-ntfy/> | 二次 / 2026-10-31 |
| 非同期の承認（CIBA） | プロトコル | 別の端末で承認する流れの標準（RFC 9126）。通知の配送が実装の大半、と解説 | <https://workos.com/blog/ciba-human-approval-ai-agents> | 二次 / 2026-11-01 |

## このリポジトリの構成との比較

自分たち: pi の親（`orchestrator` の役割）が `guarded_task` で `worker` を起動し、`feature/*` の worktree で並列に作業。調整の正本は git の ref・案件（`docs/change/`）・git-flow。
保護ブランチへの統合は必須確認（[CHG-0053](../../change/closed/0053-worktree-integration-gate.md)）。Web UI・常駐の監督・台帳は非目的（[CHG-0056](../../change/closed/0056-orchestrator.md)）。

| 観点 | 自分たち | 他 | **部品ごとに上のもの** |
| --- | --- | --- | --- |
| 調整の正本 | git の ref・案件・git-flow。外部の DB を持たない | Beads は git に紐づく課題表。Orca は Run・Task の状態を自前で持つ。Gas Town は Beads が制御面（二次） | 依存つきの課題表と `ready` の一覧は Beads が**上**（O2 の推測: 借りる候補） |
| 承認 | 構造化した操作の確認。保護ブランチへの統合は必須確認。非同期承認は設計中（[CHG-0055](../../change/closed/0055-async-approval.md)。Exploring） | Orca は pi を「full access のみ」で動かし、拡張の質問は既存の承認カードを使う（PR #25851）。Claude Squad は `--autoyes` | 自動承認でなく、操作ごとの確認と監査を持つ点は**自分たちが上**（推測。他の承認方式を網羅していない）。スマホからの承認は Agent Approve・Orca Mobile が**上** |
| 並列 | `worker` を 1 worktree = 1 feature で並列。3〜5 体を目安（O2） | Gas Town は 20〜30 体。Agent Teams は 3〜5 体が適切と案内（二次） | 規模は Gas Town が**上**。ただし費用と専門性の注意が付く（二次） |
| 保護ブランチ | 統合を必須確認。衝突の事前検査は計画（O2 の推測） | Gas Town の Refinery は bisecting merge queue（二次）。Raylabs は直列キューと fail-closed | 自動の取り込みキューは Gas Town が**上**（ただし自動化が目的で、人の承認ではない） |
| 並べて見る UI | 無い（非目的）。チャットと表 | Vibe Kanban・Claude Squad・Conductor・Orca・Zed・herdr | 一覧・差分レビューの UI は各ツールが**上** |
| スマホ | BEL・フッターの通知。承認の保留は設計中 | Orca Mobile（beta）、Paseo、Deska の中継、Agent Approve、ntfy 系 | 通知・承認・返信の入口は他が**上** |
| pi との相性 | 本体 | Orca: pi は対応エージェントだが、`--model` の指定は拒否される報告（Issue #26971・#36544、調査メモ経由）。Zed: ACP Registry に pi-acp。Agent Teams は Claude Code 専用 | 自分たちの構成は pi に合わせて作ってある。他は pi を「おまけの対象」として扱う（推測） |

## 確認した事実と推測

### 事実（出典あり）

1. **Vibe Kanban は終了へ向かっている**。公式サイトに「sunsetting。OSS として継続」とある（<https://www.vibekanban.com/>、2026-11-01）。
2. **Crystal は Nimbalyst に改名**された（<https://github.com/stravu/crystal>、2026-11-01。表題の記述）。
3. **Agent Teams は実験機能で、無効が既定**。1 セッション 1 チーム、入れ子なし、lead は固定、`/resume` で in-process の teammate は戻らない
   （<https://code.claude.com/docs/en/agent-teams>、2026-11-01）。
4. **Paseo の daemon は既定でローカルのみ**。外へ出すときは、パスワードと、DNS rebinding 用のホスト許可リストを設定する。パスワードは通信を暗号化しない。
   UI の静的ファイルは認証の前に配られる（<https://github.com/getpaseo/paseo/blob/main/public-docs/web-ui.md>、2026-11-01）。
5. **ローカルの Web UI が「localhost なら認証なし」だと危ない**: ある OSS（gptme）で、loopback への bind では認証を省いており、DNS rebinding でシェルが実行できる問題が出た
   （<https://timetobuildbob.com/blog/localhost-is-not-a-security-boundary/>、記事の日付 2026-08-04、取得 2026-11-01）。
6. **Orca は pi を full access のみで動かす**。承認方針の拡張は注入せず、拡張の質問は既存の承認カードを使う（PR #25851 の本文、2026-10-31）。
   構造化チャットは、ローカルの macOS・Linux・ネイティブ Windows と、ペアリングした Orca Server だけ。WSL・SSH は端末（docs、2026-10-31）。
7. **Zed の権限設定とサンドボックスは Zed Agent だけ**。外部エージェントと Terminal Threads には効かない（検索の抜粋。docs 本文の取得は URL の誤りで失敗。2026-10-31）。
8. **別のエージェントの承認が親へ届かず、無言で止まる報告**がある（OpenCode over ACP、2026-09-14、Zed の Discussion #49590。第三者の報告）。
9. 取り込みの運用: ディスパッチ時のパス予約、直列のキュー、衝突・失敗で止める。LLM に衝突を直させるのは危険（Raylabs、2026-10-04 の記事。取得 2026-10-31）。

### 推測（確かめていない）

- 自前の Web UI を作らず、pi + git-flow を正本に保つほうが、保守と攻撃面の費用が小さい。根拠は事実 1・4・5（終了・認証の注意）。**費用は測っていない**。
- スマホの入口は、通知（ntfy など）と、保留の承認（[CHG-0055](../../change/closed/0055-async-approval.md)）の組で足りる可能性がある。実機で試していない。
- Orca 経由の pi は、判定の境界の外で動く見込み。このリポジトリの設計との突き合わせは、調査メモの推測で、Orca の内側では**未試験**。

## 反例・弱点

| 項目 | 内容 |
| --- | --- |
| 検索の範囲 | 検索は Brave が中心。期間は 2026-10-22〜11-01。検索語は、調整の UI・TUI・worktree・承認・heartbeat・merge queue・ACP・AG-UI・スマホ通知など（各 `s-N.txt` の見出し） |
| 取得できなかったもの | Claude Code の dynamic-workflows のページ（404）。Zed のサンドボックスと Orca の対応エージェントのページ（URL の誤りで空）。Claude Code の Agent view・cross-session messaging・worktrees のページは、保存したが精読していない |
| 精読していない | Conductor・Crystal・Gas Town・Beads は、公式でなく比較記事・解説・検索の抜粋に頼る。ツールを**動かしていない** |
| 出典の質 | 比較記事の多くは、ツールの販売元・宣伝（自社製品との比較）。独立した再現は無い |
| 読み切れていない | Paseo の docs は、先頭の一部だけを取得（9000 字で切れる）。AG-UI は Omnara の記載のみ使った |
| 同じ構成で直らなかった報告 | 承認が親に届かず止まる（事実 8）。Agent Teams の再開・停止の限界（事実 3） |
| 私物の環境の偏り | Linux・WSL・Windows の混在での使いやすさは、ツールごとに差がある（Orca の構造化チャットは WSL で使えない、事実 6）。他の環境では結論が変わりうる |

## 将来案（任意・補助のみ）

- 保存した保留の承認（[CHG-0055](../../change/closed/0055-async-approval.md)）に合わせて、**スマホへ push 通知**（ntfy など）。通知は手段で、正本は git の ref という方針は変えない。
  材料: ntfy を自前で動かしてスマホへ通知する構成の記事（<https://rogs.me/2026/02/claude-code-from-the-beach-my-remote-coding-setup-with-mosh-tmux-and-ntfy/>、2026-10-31）、
  tmux のエージェントの待ちを通知する <https://github.com/flavio87/tap-to-tmux>（検索の抜粋）
- 導入する前に、通知の本文へ何を載せるか（コマンドの全文・パス）を決める。公開の通知サービスへ流すと、内容が外へ出る（推測。配送の経路は実装時に確認）
- 親が feature の表と `ready` の一覧を機械的に出す案は、[O2](pi-orchestrator-survey.md) の推測にある。ここでは繰り返さない

## 書かなかったもの（材料に出典が無い）

- GitHub の Agent HQ・mission control、HumanLayer、保護ブランチの ruleset の機能比較、Agent Orchestrator という名前の個別の製品: 材料に一次の出典が無い（「Agent Orchestrator」は一般名詞や別の記事の語としてのみ出現）
