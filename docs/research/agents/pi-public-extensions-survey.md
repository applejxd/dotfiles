# pi の公開拡張の調査と、使えないことの不利益

<!-- 現在の運用の正本は docs/spec/guard/pi-guard.md。ここは「いつ何を調べ・測ったか」を積む場所 -->

> **後の観測への案内（2026-10-22）**: P1〜P5 は当時の記録で、本文はそのまま残している。その後の実装で古くなった主張（質問機能の欠落・通知・P2 の不満・`btw` の比較・P3 の行数）の訂正と、worktree 隔離の先行例は、
> [記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)。

## 記録 P1 — 2026-10-20

> 2026-10-22 の訂正: 「不足している 4 つ」のうち、構造化した質問は実装済み。通知もローカルの BEL と子の完了通知がある。[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)

- **対象バージョン**: pi 1.3.0（`pi --version`）
- **環境**: Ubuntu（WSL）。公開情報の閲覧だけで、**拡張のインストール・実行はしていない**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)、
  [safe-acquisition](../../../home/dot_claude/skills/oss-research/references/safe-acquisition.md)）
- **問い**: 著名な pi の公開拡張・スキルを、このハーネス（自作のみ・`-ne` 固定）では使えない。使えないことで、何を失っているか
- **方法**: 公開されている一覧から、月間ダウンロード数の上位 150 件を取り、機能で分類した。分類ごとに、代表的な README を読み
  （18 件。残りは説明文だけ）、今のハーネスの状態と比べた

### 結論

- **失っているものは、多くない。** 上位 150 件の主要な機能は、すでに自作で持っている（サブエージェント・ToDo・計画・`/btw`・バックグラウンドジョブ・
  権限とサンドボックス・MCP・Web 検索・圧縮の指示）。同種の拡張が複数あること自体が、これらの需要を裏づける
- **実際に不足している機能は、4 つに絞れる**（下の「不利益」）: 構造化した質問（ask-user）・永続する記憶・LSP などの診断のフィードバック・
  サブエージェントの worktree 隔離。いずれも自作の候補で、導入の理由にはならない
- **「試す手間」の不利益は、種類で大きく違う。** スキルは、今回の変更（`.agents/skills` の `--skill` 追加、`~/.agents/skills`）で軽くなった。
  拡張は ADR-0016 の例外の手順（審査・版の固定・試験・配備・記録）が要り、軽く試せない。**これは意図した制約**で、この調査でも
  「はやりの拡張を軽く試したい」という要求に対する代替は見つからなかった（参考実装を読んで設計だけ借りる運用が、現実的な落としどころ）
- **導入を避けたほうがよいものが、上位にある**（下の「危険な形」）。人気だけでは、導入の理由にならない

### 調べ方と限界

| データ源 | 内容 | 限界 |
| --- | --- | --- |
| [awesome-pi.site/extensions](https://awesome-pi.site/extensions/) | npm の `pi-package` 全 12,747 件を月間ダウンロード数の順に並べたもの。上位 1,332 件を取得し、上位 150 件（月間 8.8k 以上）を分類した | ダウンロード数は npm 由来。順位の付け方は未確認 |
| npm レジストリの検索 API（`keywords:pi-package`） | 取得を試みた。`total` は 12,343 件 | **ページを重ねると同じ項目が返り、50 ページで 5,249 件しか取れなかった**（上位の `pi-acp` も欠けた）。**網羅には使えない** |
| 各リポジトリの README（GitHub の raw） | 18 件を、冒頭の数十行まで読んだ | 全文・コードは読んでいない。README の主張は未検証 |

- **月間ダウンロード数は、人気の目安にすぎない。** 品質・安全性・実際の利用者数の証拠ではない。`@agimon-ai/*`（上位 150 件の中に 14 件。npm から取れた範囲で 111 件）は、
  上位の多くが同じ週間 3、4k 台で並ぶ。同じモノレポの部品が、まとめて取得されている形に見える（**推測**）。1 位の `billion-context` も、
  月間 1.35M だが、週間 650k と偏りがある
- 分類は筆者の判断で、境界は曖昧（説明文だけで決めたものがある）。件数は概数
- 調査日は 2026-10-20。拡張の人気は数週間で入れ替わる

### 上位 150 件の分類

| 分類 | 件数 | 月間合計 | 代表 |
| --- | ---: | ---: | --- |
| MCP | 6 | 2,002k | `pi-mcp-adapter`、`pi-mcp-extension` |
| コンテキスト圧縮・記憶 | 14 | 1,704k | `billion-context`、`context-mode`、`pi-memory` |
| 計画・目標・ToDo・質問 | 12 | 896k | `rpiv-ask-user-question`、`rpiv-todo`、`pi-goal-x` |
| サブエージェント・並列・背景実行 | 11 | 887k | `pi-subagents`、`pi-background-tasks` |
| Web 検索・取得 | 4 | 830k | `pi-web-access`、`pi-web-search` |
| 別の入口・連携（ACP・Web UI・通知） | 7 | 621k | `pi-acp`、`pi-web-ui` |
| 観測・計測 | 8 | 535k | `@langfuse/pi-observability-plugin`、`pi-otel` |
| プロバイダ・モデル・認証 | 18 | 472k | `pi-claude-bridge`、`pi-provider-litellm` |
| スキル集・ワークフロー一式 | 14 | 383k | `@postman/postman-plugin`、`bigpowers` |
| UI・フッター・表示 | 10 | 280k | `pi-powerline-footer`、`pi-pretty` |
| コード理解・編集支援 | 7 | 201k | `pi-lens`、`@ff-labs/pi-fff`、`pi-hashline-edit-pro` |
| 安全（権限・サンドボックス・ガード） | 6 | 163k | `@gotgenes/pi-permission-system`、`cc-safety-net` |
| その他 | 33 | 678k | `/btw`（4 件）、ブラウザ操作、`pi-simplify`、画像、i18n など |

全件の一覧（分類と順位）は、本記録の末尾の「付録」。

### 今のハーネスとの対比

| 分類 | 今のハーネス | 使えない不利益 | 補い方 |
| --- | --- | --- | --- |
| MCP | `-e builtin:mcp` と `[[mcp]]`。ツールは `mcp__*` として判定・伏字化される。`mcp.json` は拒否 | **小**。`pi-mcp-adapter` は、使う分だけサーバを起動し、遅延・アイドル停止でメモリと常駐トークンを減らす（README の実測）。サーバが少ない間は効果が小さい。**互換性の問題もある**: アダプタは `mcp` という 1 つの中継ツールを通すので、ガードからは中継ツールの呼び出しとしか見えず、ツールごとの判定ができない（README が明記） | サーバを増やしたくなったら、`exposure` の調整と、必要なものだけ登録する運用 |
| 圧縮・記憶 | 圧縮の依頼に引き継ぎの指示を足す。**永続する記憶は無い**（`AGENTS.md`・`docs/`・skill で代用） | **中**（記憶）。`pi-memory` は `MEMORY.md` に事実と決定を、日次ログと一緒に書く。`billion-context` は、エージェントとモデルの API の間に入って、通信を書き換えるプロキシ型。**第三者のコードが全通信を見る形で、方針と相性が悪い** | 記憶は、skill とファイルで足りる範囲が大きい。アルゴリズム圧縮（`pi-vcc`）は、設計だけ参考にできる |
| 計画・ToDo・質問 | `todo`・`plan`（自作）。構造化された質問は**無い** | **中**（質問）。`rpiv-ask-user-question`・`pi-ask-user` は、選択肢つきの質問で、モデルが推測せずに聞ける。`/goal` 系（`pi-goal-x` など）の自律ループも**無い** | 質問は小さな拡張で自作できる（`ctx.ui` の選択）。`/goal` は、必要になったときに設計 |
| サブエージェント | `guarded_task`（役割・`keep`・`job`・bypass の継承）、`/fleet` | **小〜中**。`pi-subagents` は、組み込みの役割（scout・reviewer など）、チェーン・並列・保存したワークフローを持つ。`@gotgenes/pi-subagents-worktrees` は、git worktree で隔離する。**隔離は無い** | worktree 隔離は設計だけ借りて自作できる |
| Web 検索・取得 | skill + CLI（`web-search`。brave・exa・tavily・duckduckgo・openalex、秘匿チェックつき） | **小**。`pi-web-access` は、動画・PDF・GitHub のクローンまで持つ。多くの用途は、今の検索で足りる | 不足が出た分だけ、CLI に足す |
| 観測 | **無い**（セッションのファイルのみ） | **小〜中**。Langfuse・LangSmith・Braintrust・Raindrop・OpenTelemetry。**プロンプト・ツール呼び出し（秘密を含み得る）を外部の SaaS へ送る形**で、伏字化の方針と衝突する | 自前の OpenTelemetry で、送り先を自分で持つなら、設計できる。当面は不要 |
| コード理解・編集 | 編集後の整形（ruff・markdownlint）。**LSP の診断は無い** | **中**。`pi-lens` は、書くたびに LSP・linter・型検査の結果を返す。`pi-hashline-edit-pro` は、行にアンカーを付けて編集の失敗を減らすとする（README の主張。未検証） | linter の実行は skill と CLI で足りる。LSP は大きいので、需要が確かめられてから |
| 安全 | フルガード（判定器・伏字化・役割）＋サンドボックス | **無し**。`@gotgenes/pi-permission-system`・`cc-safety-net`・bwrap の守り・コンテナのサンドボックス・LLM の判定（`pi-warden`）など、同じ課題を別の形で解いている | 参考実装として読む。`pi-permission-model-judge` の「拒否を先に」の判定は、設計の参考になる |
| 別の入口 | Zed・Orca は素の `pi`（RPC）。通知・Web UI は無い | **小**。`pi-acp`（ACP）は、今の使い方では要らない。Web UI（`pi-web-ui` など）・Telegram・通知は、エージェントを HTTP やチャットに公開する形で、**サンドボックスとの相性が悪い** | 当面は不要 |
| プロバイダ・モデル | Copilot・Bedrock など pi 組み込み | **小**。LiteLLM・NVIDIA NIM など。`pi-claude-bridge`・`pi-anthropic-auth` は、Anthropic の方針変更（README に「発表して撤回された」とある）に左右される | 必要になった提供元だけ |
| スキル集 | `home/dot_claude/skills/`、今回から作業先の `.agents/skills`、`~/.agents/skills` | **小**。`bigpowers`（73 スキル）などは、**スキルとして試せる**。ただし、本文・同梱のスクリプトの審査は要る | 下の「試す手間」 |
| UI・フッター | `activity` のフッター | **小**（見た目の好み） | 自作で足りる |
| その他 | `/btw` は自作済み（同種 4 件） | **無し〜小** | — |

### 危険な形（導入を避ける理由）

- **通信を中継する**: `billion-context` は、エージェントとモデルの API の間に入る（README）。プロンプト・コード・認証の流れ全体が、第三者のコードを通る
- **外部の SaaS へ送る**: 観測系の拡張は、プロンプトとツールの入出力を送る。ツールの結果に秘密が含まれ得る
- **ローカルでサーバを公開する**: Web UI・Telegram・遠隔操作の拡張は、エージェントを外から操作できる入口になる
- **依存の連鎖が長い大きなモノレポ**: 上位にも、`@agimon-ai/*` のように、同じ作者の大きなモノレポの部品が多数ある。
  審査の範囲が広く、費用が大きい（ADR-0016 の「供給網の危険」）

### 試す手間

| 種類 | 試す手段 | 手間 |
| --- | --- | --- |
| スキル | `~/.agents/skills/<名前>/` に置いて `/reload`（**新たに実機で確認**: `--no-approve` の `pis` と同じ条件で読まれる）。作業先の `.agents/skills/` も可（今回の変更） | **軽い**。本文と同梱のスクリプトの審査だけ。実行は判定器とサンドボックスが決める |
| 拡張 | `-e <パス>` で明示するか、`own_extensions` に取り込む。審査・版の固定・偽のモデルでの試験・配備・記録（ADR-0016） | **重い**。意図した制約 |
| MCP | `[[mcp]]` に足して `chezmoi apply` | 中。ローカルのサーバは、拡張に近い審査が要る |

### 自作の候補（決定ではない）

優先度は、不利益の大きさと、実装の小ささの両方で見た筆者の推定。実装の要否は、別に決める。

1. **構造化した質問**（ask-user）: 小さな拡張で足りる。モデルの推測を減らせる
2. **永続する記憶**: skill とファイルで足りる範囲から始める
3. **サブエージェントの worktree 隔離**: 設計だけ参考にする
4. **LSP などの診断のフィードバック**: 大きい。需要を確かめてから
5. **`/goal` の自律ループ**: 必要になったとき

### 未確認

- 拡張の README の主張（性能の数値・機能）は、実測していない
- 月間ダウンロード数の質（自動取得の混入）
- awesome-pi.site の順位の付け方
- 全 12,343 件のうち、上位 150 件より下に、重要な拡張があるか（npm の検索 API が使えず、awesome-pi.site の上位 1,332 件までを取得した）
- 今のハーネスの MCP のサーバの数・`exposure` の設定（比較に使った記述は、`pi-guard.md` に依る）

## 記録 P2 — 2026-10-20: subagents / todo を公開拡張へ置き換えられるか

> 2026-10-22 の訂正: 「自作を実際に使って見えこと」の不満は一部解消、一部は残る。[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)

- **問い**: 自作の `subagents` / `todo` は、Claude Code の同種の機能に遠く及ばない。公開拡張（ユーザーが多い）を審査して導入したほうが、保守と使い勝手の両方でよいか
- **方法**: 実際にこのセッションで自作の `guarded_task` と `todo` を使い（エージェント側の使い勝手）、`@tintinweb/pi-subagents`
  v0.22.0 の README・`package.json`・`src/agent-runner.ts`（子のセッションの作り方）を読んだ。**コードは実行していない**。特殊な経路（TUI の表示）は、利用者の画面でしか確かめられない

### 自作を実際に使って見えたこと（エージェント側）

- `guarded_task`: `explore` 3 件を同じメッセージで起動し、約 17 秒で戻った。`keep` の子への追加依頼も、文脈を保って答えた。
  **誤り**: `explore` に `bash` が無いため、子が「範囲外のオフセットで読んで総行数を得る」迂回をし、行数が全ファイル 1 行多くなった
  （実際は 198/121/120/87/182、子の報告は 199/122/121/88/183）。さらに、子のツールエラーが結果の本文に混じった。
  　子の途中経過は親から見えず、途中での指示（steering）もバックグラウンド実行も無い（結果まで待つ）
- `todo`: `add` は複数項目を 1 回で足せるが、`set` は 1 件ずつ。この会話で、取り消しだけのために十数回呼んだ。
  毎回リスト全体が戻り、繰り返しがノイズになる。Claude Code の `TodoWrite`（リストを 1 回で置き換える）に相当する操作が無い

### `@tintinweb/pi-subagents` が言うことと、読んで分かったこと

| 項目 | 内容 | 出典 |
| --- | --- | --- |
| 機能（README の主張） | Claude Code と同じツール名（`Agent` など）、常時表示のウィジェット、`FleetView`、会話ビューア、`.agents/agents/*.md` の役割定義、バックグラウンド実行と `ctrl+b`、steering、再開、worktree 隔離、スキルの事前読み込み、cron のスケジュール、イベントバス | `README.md` |
| 規模・依存 | MIT、依存は `croner` と `nanoid` の 2 つ。**ソース 59 ファイルで約 1 MB**（`index.ts` だけで 208 KB）。自作は `subagents/index.ts` が約 120 行、`children.ts` が約 12 KB | `package.json`、GitHub API |
| 子の作り方 | **親のプロセス内**に `createAgentSession` で子のセッションを作る。子は独自の `DefaultResourceLoader`・`SettingsManager` を持ち、**組み込みのツール（`BUILTIN_TOOL_NAMES`）を `tools:` で絞って渡す**。拡張は、子のローダーが自動発見するもの（明示の `-e` で親に足したものではない）を、定義ファイルの `extensions:` で絞る | `src/agent-runner.ts` |
| pi の内部への依存 | `createAgentSession`・`DefaultResourceLoader`・`SettingsManager`、組み込み拡張のファクトリ。コードのコメントに、pi の非公開のフィールド（「private facade field」）を読む互換の誤魔化し（shim）がある。バージョンごとの間合いの分岐が多い | `src/agent-runner.ts` |
| 信頼 | 子は親の project trust を引き継ぐ（`--no-approve` の親の子は信頼なし） | `src/agent-runner.ts` |

### go / no-go

- **`@tintinweb/pi-subagents`: no-go（そのままの導入）。** 理由は、1 MB の審査の重さより、**ガードとの構造的な衝突**。
  1. 子は親と同じプロセスで、組み込みのツールを持つ。このハーネスは `-nbt` で組み込みを外し、`guarded_*` を通す。
     子が組み込みの `bash` を持つと、**判定を通らない経路**になり得る（箇所 1 の実測: [pi-upstream 表 B の 1](../../spec/pi-upstream.md#b-明示が無いここに書く)）。これは読んだ構造からの推測で、**実機では確かめていない**
  2. 役割（`reader` / `implementer`）は、プロセス起動時の環境変数（`PI_HARNESS_ROLE`）で決まる。同じプロセスの子は、親の役割を共有し、子ごとに役割を分けることができない
  3. pi の内部 API（`createAgentSession` など）に深く依存し、pi の版を上げるたびに壊れやすい。保守の負担は、自作と同じかそれ以上になり得る
  4. 修正して子の起動部分を入れ替えると、結局 fork になる（自作と同じ保守）
- **`nicobailon/pi-subagents`、`@gotgenes/pi-subagents` も、前景の子はこのプロセス内で動く設計**（どちらも README の記述。ソースは未読）。
  **「子を別プロセス（`pi --mode rpc`）で起動し、フルガードを子も連れて行く」という自作の構造は、公開拡張と違うセキュリティ上の利点**で、これを捨てると、ガードの前提が変わる
- **`todo`**: 公開拡張への置き換えは、当面見送る。自作は約 180 行で小さく、差は、一括置換と表示（オーバレイ）だけ。自作で直せる

### 変えるとすれば（候補。決定ではない）

自作の構造（子 = 別プロセス）の、上に、公開拡張の**使い勝手だけを借りる**。設計だけを参考にする（コードは写さない）。

1. `todo`: リストを 1 回で置き換える操作（`replace`）、戻り値の縮約、常時表示のオーバレイ
2. `guarded_task`: **バックグラウンド実行**（ID をすぐ返し、完了は `activity` と同じように `pi.sendMessage` の followUp で通知）
3. 子の進捗表示: 子は RPC で動いているので、イベント（ツールの活動・トークン数）を受け取って、ウィジェットに出せる。steering も RPC 経由で可能と見込む（**未確認**）
4. 役割ごとの道具の見直し: `explore` で行数を数えられない問題。読み取り専用のコマンド（`wc` など）をどう扱うか
5. 子のエラーを結果の本文と分ける

### 未確認

- 公開拡張のバグの領度（週から月単位の実施でしか分からない）
- `@tintinweb/pi-subagents` をフルガードの下で実際に動かしたときの挙動（コードを実行していない）
- RPC の子への steering を実際に送れること

## 記録 P3 — 2026-10-20: 自作拡張の採点（公開の標準像との比較）

> 2026-10-22 の訂正: **この採点は現行の点ではない**。拡張の構成・行数・質問の有無・通知が変わった。[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)

- **対象**: `home/dot_pi/agent/extensions/` の自作 5 個（activity 276 行・btw 121・plan 87・subagents 120・todo 342。計 946 行）と、
  フルガード（`home/dot_config/pi/harness/`）。比較の標準像は、本ファイルの P1（上位 150 件の分類）
- **方法**: 構成・行数・各拡張の冒頭と、P1・P2・ADR-0016 を読んで、AI が採点した。**コードの全行読み・試験の実行・ネットの再検索はしていない**。
  点は筆者の判断で、再現できる測定ではない

| 観点 | 点 | 要旨 |
| --- | ---: | --- |
| 安全性（権限・サンドボックス・伏字化） | A (95) | 公開の安全系（約 6 件）は判定だけの形が多い。判定器・役割・Fence・伏字化・`--no-approve` まで揃う |
| 基本機能の網羅 | B+ (82) | 主要機能は自作済み。組み込みの役割・チェーン実行・ワークフロー保存は無いか小さい |
| 供給網の方針（ADR-0016） | A- (90) | 中継型・外部 SaaS 送信型を避ける。ただし拡張を軽く試せない（意図した制約） |
| 機能の幅 | C+ (68) | 不足は構造化した質問・永続する記憶・LSP 診断・worktree 隔離。`/goal` 型の自律ループと観測も無い |
| UI・体験 | C+ (65) | フッターは `activity` のみ。通知・powerline・Web UI は無い |
| 保守性・文書化 | A- (90) | ADR・仕様・調査記録・コメント規約がある |
| 1 拡張の完成度 | B (75) | 小さく読みやすい。`subagents`（Windows の素の pi 用）とフルガード側の `task` が二重構造 |
| **総合** | **B+ (78)** | 安全は標準を明確に超える。機能の幅と UI は標準より狭い |

- **減点の主因**: (1) 質問ツールが無く推測で進みがち (2) 記憶・診断が無い (3) 素の `pi`（Orca・Zed・Windows）はガード無しで、保護が運用依存
- **改善の優先（自作で小さい順）**: ask-user → 編集後の LSP・linter 診断 → worktree 隔離の `task`
- **未確認**: コードの品質（全行）、試験の通過状況、公開拡張の README の主張
- **訂正（同日・読んで確かめた後）**: 「1 拡張の完成度」で減点した `subagents` と `guarded_task` の「二重構造」は過大評価だった。
  重なるのは約 50 行で、目的と実行方式が違う（Windows にはフルガードが無いため、読み取り専用の最小の代替）。統合は見合わないと判断し、
  宣言のずれだけ試験で止めた（[理由](../../spec/guard/pi-subagents.md#二つの-task-を別物にしている理由)）。この観点の採点は B (75) より高い（A- 相当）と見直し、総合は B+ のまま

## 記録 P4 — 2026-10-20: ask-user 系拡張の方式（自作 `ask` の設計の参考）

> 2026-10-22 の訂正: 「後回し」のうち、問ごとのタブと BEL は実装済み。推奨の事前チェックを足した。[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)

- **方法**: README と docs を読んだだけ（取得・実行・コード複写なし。コード本体は未読）。README の主張は未検証
- **出典**: `juicesharp/rpiv-mono` の `rpiv-ask-user-question`（README・`docs/tool-schema.md`・`docs/hosts.md`）、`edlsh/pi-ask-user` の README、
  同リポジトリの issue #291・#301・#310・#313、`Gentleman-Programming/gentle-shell` #1277（検索語: `pi-ask-user pi coding agent extension ask_user tool README`、`rpiv-ask-user-question issue bug`）
- **方式**: どちらも 1 回の呼び出しで 4 問まで尋ねる。`rpiv` の RPC 経路は 1 問ずつの `select` / `input` で、タブ画面は TUI だけ。
  非対話では `before_agent_start` でツールを外す。自由記述の行を自動で足し、`Other` などのラベルを予約する。`pi-ask-user` にはタイムアウトがある
- **反例・注意**: 空の自由記述が記録される (#301)、部分回答で飛ばした問が見分けられない (#291)、codemode `only` で呼ばれない (#310。原因は推測)、
  同名ツールの二重登録で起動が失敗する (gentle-shell #1277)
- **自作への反映**: 名前は `ask`（衡突回避）、予約ラベル、空入力は選択肢へ戻す、`unanswered` を返す、待ち上限 5 分。タブ画面・プレビュー・メモ・BEL は後回し

## 記録 P5 — 2026-10-21: 人気の拡張のうち未導入のものと、既存の機能との比較

> 2026-10-22 の訂正: 「`btw`（ツールなしの 1 回きりの応答）」は当時の説明。現行の既定は `explore` の子で、`--plain` だけがツールなし。[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正)

- **対象バージョン**: pi 1.3.0。**拡張のインストール・実行はしていない**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)）。コードは読まず、README と説明文だけを読んだ。README の主張は未検証
- **問い**: 月間ダウンロード数の上位の拡張のうち、取り入れていないものは何か。`pi-memory`・`pi-btw`・`pi-advisor-flow`・`@ff-labs/pi-fff` は、今の仕組み（`sdd-docs`・自作 `btw`・`review`・`rg` / `fd` / `fzf`）で足りているか
- **出典**（いずれも 2026-10-21 に取得）: <https://awesome-pi.site/extensions/>（順位。取得は 6,000 文字で打ち切ったので、上位約 40 件まで）、
  <https://pi.dev/packages/pi-memory>、<https://pi.dev/packages/pi-btw>、<https://pi.dev/packages/pi-advisor-flow>、<https://pi.dev/packages/@ff-labs/pi-fff>、
  <https://pi.dev/packages/pi-cc-extensions>。検索語: `pi-memory pi coding agent extension qmd MEMORY.md github`、`pi-advisor-flow pi extension Executor Advisor github`、`@ff-labs/pi-fff pi extension fuzzy file search github`、`pi-btw pi extension side conversations github`
- **順位の変化**: P1（2026-10-20）から入れ替わっている（`pi-mcp-adapter` が 2 位、`pi-subagents` が 5 位）。全体は 12,845 件。順位の付け方は未確認のまま

### 比較の結果

| 拡張（順位・月間 DL） | 今の仕組み | 差と判断 |
| --- | --- | --- |
| `pi-memory`（28 位前後・44.9k） | `sdd-docs`（構造化した記録）・checkpoint 相当の圧縮の指示・`AGENTS.md` | 差は「エージェントが自動で書き、毎ターンのシステムプロンプトへ注入する」ことだけ（長期記憶 4K・当日ログ 3K・scratchpad 2K、計 16K 文字まで。README）。自動で書いた内容が永続的に注入される点は、誤った記憶やツール結果に紛れた指示が残る危険がある（**推測**）。**利用者の判断（2026-10-21）: `sdd-docs` の構造化した形のほうがよい。`AGENTS.md` も肥大化させたくない。導入しない** |
| `pi-btw`（32 位・42.6k） | 自作 `btw`（ツールなしの 1 回きりの応答） | `pi-btw` は、本物のサブセッションで `read` / `bash` / `edit` / `write` を持ち、スレッドが続き、`/btw:ask`（読み取り専用）・`/btw:tangent`（会話を引き継がない）・`/btw:inject`（本体へ戻す）・専用モデルを持つ。ツール付きのセッションは、P2 の `pi-subagents` と同じ構造的な衝突になり得る（**推測**）。**導入しない。自作 `btw` は `explore` の子を既定にした**（[pi-guard](../../spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw)） |
| `pi-advisor-flow`（24 位前後・70.2k） | `guarded_task` の `review` | `review` は親が明示して呼ぶ別プロセスの読み取り役。`pi-advisor-flow` は、実行役の `ask_advisor` に加えて自動のゲート（計画の前・失敗の連続後・完了宣言の前）と、同じツール呼び出しの繰り返しの検出（ツールの実行を止めることがある）を持ち、会話を自動で再構成して渡す。助言役はツールを使わない。約 1 MB で版の動きが速い（0.14.2）。**導入しない。自動ゲートは設計の参考にする（別の話題として後日）。会話をそのまま渡さない、読み取りツールを持たせる、は自作の方針として維持** |
| `@ff-labs/pi-fff`（34 位・39.1k） | 組み込みの `grep` / `find`（README によれば `rg` / `fd` を起動）と、`fzf` | `rg` 14.1.1・`fd` 10.5.0・`fzf` 0.53.0 が手元にある。正規表現・OR の複数パターン（`rg -e a -e b`）・`.gitignore` の尊重は足りる。足りないのは、frecency とクエリ履歴での順位づけ、git の変更ファイルを上位にする機能、事前インデックス、カーソルによるページ送り。frecency の DB を `~/.pi/agent/fff/` に書くので、`pis` の起動ごとの agent 置き場・書き込み制限と衝突し得る（表 B の 7・12 と同種。**推測**）。ネイティブのバインディングを持ち、依存は 2 つ。**導入しない** |

### 訂正

- 同日の会話で、`pi-cc-extensions` を `/btw` と同種として分類したのは**誤り**だった。これは Claude Code 風の TUI 表示・フッター・`/context` 検査・`@` でのセッション参照で、`/btw` の機能は持たない

### 反映したこと

- `review` を `explorer` 役（`wc` と読み取り専用の git を持つ）にし、依頼は「意図と問い」を書く形に改めた。差分や対象は子が自分で読む（[review への依頼の書き方](../../spec/guard/pi-subagents.md#review-への依頼の書き方)）
- `btw` の既定を `explore` の子にした。`--plain` は従来どおり（[btw](../../spec/guard/pi-extensions.md#自作の拡張-todo--plan--btw)）

### 未確認

- 順位は上位約 40 件までで、それ以下は見ていない。README の主張（性能・機能）は実測していない
- `guarded_grep` / `guarded_find` が `rg` / `fd` を呼ぶか（`harness/index.ts` に直接の言及が見つからなかった）。`pis` で `fzf -f` が確認なしで通るか。実際のリポジトリでの検索の速度
- `pi-advisor-flow` の「自動ゲート」の詳細（README の後半は、取得が 7,000 文字で打ち切られて読めていない）

## 記録 P6 — 2026-10-22: worktree 隔離の先行例と P1〜P5 の訂正

- **対象バージョン**: pi 1.3.0。**拡張のインストール・実行・展開はしていない**（[ADR-0016](../../adr/0016-pi-extensions-own-first.md)、
  [safe-acquisition](../../../home/dot_claude/skills/oss-research/references/safe-acquisition.md)）
- **問い**: (1) P1・P2 が「設計だけ借りて自作できる」とした worktree 隔離は、先行例でどう作られているか。
  (2) P1〜P5 の主張のうち、その後の実装で古くなったものはどれか
- **方法**: npm レジストリから配布物を直接取得し、`dist.integrity`（sha512）と照合し、`tar -xzO` で必要なファイルだけを標準出力へ出して読んだ。
  取得物は調査の後に削除した。訂正は、独立の `review`（子エージェント）に、リポジトリの現状と照らして点検させた
- **出典**（いずれも 2026-10-22 に取得）:
  - `@gotgenes/pi-subagents-worktrees` 0.3.3（レジストリの更新 2026-09-05）:
    <https://registry.npmjs.org/@gotgenes/pi-subagents-worktrees/-/pi-subagents-worktrees-0.3.3.tgz>、
    integrity `sha512-5s7DIYm9Ge/2+/APnk9f9e5QAlq5u/xL1j0DKe/lXURE0/l8q031vqqEZVkCFjxUVnkFPebsOHKdTVrd4xeVzA==`（取得物を計算した値と一致）、
    リポジトリ <https://github.com/gotgenes/pi-packages>。読んだ: `README.md`（全文）と `src/worktree.ts` の先頭 9,000 バイト
  - `@tintinweb/pi-subagents` 0.22.0:
    <https://registry.npmjs.org/@tintinweb/pi-subagents/-/pi-subagents-0.22.0.tgz>、
    integrity `sha512-vkpH930uAi/Y8KOyc4+D7bSNgrL8xX4TAdMF6AWTqFjs2BTxuSobZ4ViA5jcL87FmyKb7O1X+r6ZPiEVTk3GQg==`（一致）。
    読んだ: `README.md` の worktree に関する行と、`src/worktree.ts` の先頭 7,000 バイト
  - Claude Code の公式 docs <https://code.claude.com/docs/en/worktrees>: **取得を試したが失敗し（`network: 取得できない`）、未読**。迴回していない。
    検索（`websearch.py search`、Brave）の要約だけが手元にある（**二次情報**）: `isolation: worktree` をサブエージェントの定義に書ける、
    `.worktreeinclude` で git 管理外のファイルを持ち込める、変更が無ければ自動で消し、あれば定期的な掃除まで残す、という。裏となる一次資料で確かめていない

### worktree 隔離の先行例

| 論点 | `@gotgenes/pi-subagents-worktrees` 0.3.3 | `@tintinweb/pi-subagents` 0.22.0 |
| --- | --- | --- |
| 対象の選び方 | エージェントの種類ごとの opt-in（`worktreeAgents`） | frontmatter の `isolation: worktree`。全体の切り替え `worktreeIsolation` |
| 作成 | `os.tmpdir()` の下に `pi-agent-<id>-<uuid8>`、HEAD から `--detach` | 同じ。モノレポのサブディレクトリを保つ `workPath` |
| 作成の失敗 | **子の実行を失敗にする**（隔離なしで黙って動かさない） | 隔離なしの通常 cwd へ黙って落とす |
| 完了時 | 変更なし→削除。あり→`git add -A` とコミット、ブランチ `pi-agent-<id>`（衡突時は時刻を付ける）→削除 | 同じ |
| コミットの hook | 失敗したら `--no-verify` で 1 回だけ再試行し、結果に警告を付ける | 常に `--no-verify` |
| 後片付けの失敗 | **消さずに残し**、結果にパスを示す | 最善努力で強制削除（作業を失いうる） |
| 取り残しの発見 | 起動時の警告、`/subagents-worktrees` で一覧と削除（確認つき） | 読んだ範囲では見当たらない |
| 統合 | 対象外（「ブランチの先は利用者の仕事」） | 同様（README の説明の範囲） |
| 破壊的操作 | モデルには渡さない（スラッシュコマンドだけ） | 読んだ範囲では見当たらない |
| 検証 | — | `gate: "npm test"` で、モデルでなくコマンドで子を検証する（README の記述。実装は未読） |

- **共通の弱点（このリポジトリにとって）**: どちらも起点が HEAD で、親の未コミットの変更が子に見えない。このリポジトリは作業中は常に未コミット（コミットは承認制）。
  さらに、どちらもコミットの hook を飛ばす（このリポジトリは `--no-verify` を禁じている）
- **設計への示唆**（詳細は [CHG-0029](../../change/0029-worktree-isolation.md)）: `@gotgenes` の「作成失敗は失敗」「未確定なものは消さない」「取り残しの警告」「破壊的操作をモデルに渡さない」は取り入れる。
  起点をスナップショットにし、回収を hook の走らないプラミングにする点は、先行例に無いこのリポジトリ固有の設計
- **限界**: 実機での挙動は未確認。`src/` のこれ以外のファイル（設定・起動時の警告・スラッシュコマンドの実装）は未読。README の主張は未検証

### P1〜P5 の訂正

現状は 2026-10-22 時点の作業ツリーを読んだもの。点数の再採点はしていない。

| 記録 | 当時の主張 | 現状 | 判断 |
| --- | --- | --- | --- |
| P1（結論・対比表・自作の候補）、P3（機能の幅・改善の優先） | 構造化した質問（ask-user）が無く、不足の 4 つのうちの 1 つ | 自作 `ask` がある（`home/dot_pi/agent/extensions/ask/index.ts`。選択肢・最大 4 問・自由記述・複数選択）。さらに推奨の選択肢を先頭に置く事前チェックを足した（171cf25）。**子から利用者への質問の中継は未実装**（[CHG-0026](../../change/0026-specialist-agents-with-skills.md)） | 質問は実装済み。不足は 3 つ（記憶・LSP 診断・worktree 隔離）。中継は別の問題 |
| P1（対比表の「通知・Web UI は無い」）、P3（UI・体験「通知は無い」） | 通知が無い | `notify` 拡張の BEL、ジョブと子の完了通知（通番・時刻・結果の保存）がある。Web UI・外部チャットの入口は無い | ローカルの通知はある。HTTP・チャットへの公開は無い（この点は当時のまま） |
| P2（「自作を実際に使って見えたこと」と「変えるとすれば」） | `todo` の `set` が 1 件ずつ・返り値が長い、`guarded_task` に背景実行・steering が無い、子のエラーが本文に混じる、`explore` で行数を数えられない | `todo` に `batch` と `replace` と結果の縮約、子の `background`・`steer`・状態照会、エラーと回答の分離、`explorer` の `wc` と読み取り専用の git がある。**子の逐次の進捗ウィジェットは完成したとは言えない**（確認していない） | 一括で「全部解消」とは言わない。進捗ウィジェットは未確認 |
| P3（拡張の行数 946 行） | activity 276・btw 121・plan 87・subagents 120・todo 342 | `wc -l`（レビューで確認）: 当時の 5 拡張だけで 1,068 行（activity 276・btw 215・plan 87・subagents 146・todo 344）、現在の 7 拡張で 1,520 行（さらに ask 439・notify 13） | P3 の行数と点数は現行のものではない。点数は「筆者の判断で再現できる測定ではない」（P3 自身の限界）。再採点が要る |
| P4（後回しの範囲） | タブ画面・プレビュー・メモ・BEL は後回し | 問ごとのタブと確認タブは実装済み（`ask/index.ts`）。BEL は `notify` にある。プレビュー・メモは実装していないと読める（未確認）。「推奨の事前チェック」は、**推奨を先頭に置くことを送信前に検証する**もので、画面で推奨を自動で選ぶものではない | P4 の「後回し」は範囲ごとに覆った |
| P5（`btw` の比較） | 自作 `btw` はツールなしの 1 回きりの応答 | 現行の既定は読み取り可能な `explore` の子。`--plain` だけがツールなし（P5 の同じ表の判断欄の後半と、「反映したこと」もこの現状を述べている） | P5 の表の前半は当時の説明。現行は `pi-guard.md` |
| このセッションの実装（P1〜P5 の「自作の候補」を実現したもの） | — | `guarded_task` の `todo` 必須化は、`explore` / `review` / `worker` の**単独の新規依頼**で、`todo` ツールが有効なときだけ。`tasks` の一括形と `commit` は対象外 | 無条件の仕様として読まない |

### 未確認

- P1 の順位・ダウンロード数・分類件数、P2 の外部拡張の規模や安全性は再検証していない
- 現行の TUI での通知・質問の体験。worktree の先行例の実機での挙動
- P1・P2・P4 の出典は、節ごとに追跡性が違う（配布物の固定 URL・ハッシュが無い節がある）。ここでは新しい観測だけに版・取得日・URL を付けた

## 記録 P7 — 2026-10-22: worktree 隔離の先行例の比較 (Claude Code・Codex・Cursor)

- **問い**: pi の拡張以外の、広く使われるエージェント（Claude Code・Codex アプリ・Cursor ほか）は、worktree の起点・取り込み・隔離の強制・後始末をどう作っているか。
  [CHG-0029](../../change/0029-worktree-isolation.md) の設計に、取り入れる点と避ける点は何か。pi の拡張 2 つ（`@gotgenes/pi-subagents-worktrees`・`@tintinweb/pi-subagents`）は、[記録 P6](#記録-p6--2026-10-22-worktree-隔離の先行例と-p1p5-の訂正) のとおりで、ここでは再掲しない
- **方法と限界**: 公式 docs を取得して読んだ。**実機では動かしていない**。取得日はすべて 2026-10-22。
  `.worktreeinclude` は、ignored のファイルを worktree へコピーする対象を選ぶ設定ファイル。`filter driver` は、git が `add` などでファイルの内容を変換するために呼ぶ外部コマンドの設定

| 対象 | 根拠の種類 | 出典 |
| --- | --- | --- |
| Claude Code | **一次**（公式 docs を取得して読んだ） | <https://code.claude.com/docs/en/worktrees> |
| Cursor | **一次**（公式 docs を取得して読んだ） | <https://cursor.com/docs/configuration/worktrees> |
| Codex アプリ | **二次**。公式ページ <https://developers.openai.com/codex/app/worktrees> は本文が動的描画で取得できず、検索結果の要約が根拠。詳細は、コミュニティの解説記事 <https://codex.danielvaughan.com/2026/04/11/codex-app-worktree-lifecycle-local-environments/> を読んだ（**公式でも未検証**） | 左の 2 つ |
| Conductor・vibe-kanban・claude-squad | **二次・未確認**。解説記事の検索結果の断片だけで、一次情報は未読 | 検索結果 |

### 比較

| 論点 | Claude Code（一次） | Codex アプリ（二次） | Cursor（一次） | 今回の設計（CHG-0029。**案**） |
| --- | --- | --- | --- | --- |
| 起点 | 既定はリモートの既定ブランチ（`worktree.baseRef: "fresh"`）。`"head"` はローカルの HEAD（コミット済みの追跡ファイルだけ。未コミットは持ち込まない） | 選んだブランチの未コミットの変更も適用する（detached HEAD） | 本調査では未読 | 親の未コミット・未追跡（ignored を除く）を含むスナップショット |
| 取り込み | 自動でない。ブランチ `worktree-<name>` を利用者がマージ | Handoff で worktree の変更を本体のチェックアウトへ移す（逆も可。同じブランチを 2 か所で開くと失敗する） | `/apply-worktree` で本体へ適用 | W1: 回収した patch を利用者が手動で `git apply`。自動の取り込みは W2 以降 |
| 隔離の強制 | ツール呼び出しの 4 つの検査: 本体への Edit/Write/NotebookEdit、本体を指す cwd の Bash、git の迂回（`git -C`・`--git-dir`・`GIT_DIR`・`GIT_WORK_TREE`・`cd`）、コマンド形が検証できないもの。**`cp` やシェルのリダイレクトによる書き込みは追跡せず**、権限とサンドボックスの設定に任せる（docs が明記） | 未読 | 未読 | OS レベル: Landlock が子の書込可を worktree と共有 `.git` の一部に絞る（Fence の入れ子は不可。Landlock は実測済み） |
| ignored・未追跡 | ignored は `.worktreeinclude`（`.gitignore` の書式。ignored のものだけコピー）で選ぶ | ignored は Handoff で移らない。セットアップのスクリプトで補う | `.cursor/worktrees.json` のセットアップのスクリプト | 未追跡は持ち込む（`add` の前に秘密のパスを検査し、容量で拒否）。ignored は持ち込まない |
| 後始末 | 終了時、変更なしなら自動削除（名前付きは確認）、変更ありは保持して確認。サブエージェントの worktree は、変更なしで自動削除、変更ありは定期の掃除（`cleanupPeriodDays`）が、変更・未追跡・未 push のコミットがあるものを消さない。作成した worktree の git メタデータに**目印**を書き、無いもの（利用者が `git worktree add` で作ったもの）は掃除しない。実行中は `git worktree lock` を取り、掃除と `git worktree remove` を拒む。killed なセッションの lock は掃除が解放する。状態が検証できないとき（サブモジュールを調べられないなど）は、自動削除せず確認する | 管理下の worktree は約 15 個を上限に自動削除し、**削除の前にスナップショットを保存する** | `/delete-worktree` で削除。3.5 以降、機械全体で最大 25 個（既定、`cursor.worktreeMaxCount`）。**`git worktree add` で作った外部のものも削除の対象** | 未取り込みの成果物は掃除しない。取り残しは起動時に警告し、利用者が確認して破棄 |
| 作成の拒否条件 | 4 つの拒否条件の 1 つが、リポジトリの設定の **filter driver** が把握できない・切れない場合 | 未読 | 未読 | 秘密のパスの検査と容量で拒否（filter driver は未対応。CHG-0029 で決める） |
| コミットの hook | docs から読み取れた記述なし（**未確認**） | 未確認 | 未確認 | 走らせない（プラミングで ref を作り、`--no-verify` は使わない） |

Conductor・vibe-kanban・claude-squad は、解説記事の断片（各 worktree を分ける、レビューしてマージする、衝突で止まる、など）だけで、**二次情報・未確認**。表には入れていない。

### 今回の設計との違い

- **起点**: Claude Code の既定は、利用者の未コミットを持ち込まない。このリポジトリは作業中ずっと未コミットなので、`"head"` でも足りない。Codex だけが未コミットの変更を適用する（二次情報）
- **隔離の強制の層**: Claude Code は、ツール呼び出しの検査（アプリ層）で隔離し、`cp` やリダイレクトは追跡しない。今回は、子の書込可を OS（Landlock）で絞るので、コマンドの形に依らない。ただし、Claude Code の検査は、実機ではなく docs の記述で比べた
- **取り込み**: 先行例は、利用者が操作する形（ブランチのマージ・`/apply-worktree`・Handoff）で、自動で親へ書かない。W1 の手動の `git apply` と同じ方向
- **後始末**: Cursor は、`git worktree add` で作った外部のものまで削除の対象にする。Cursor・Codex は、上限を超えると自動で削除する（Codex は削除の前にスナップショットを保存する）。今回は、未取り込みの成果物を自動で消さない

### 分かったこと

1. **実行中の worktree は `git worktree lock` で守る**（Claude Code）。`git worktree remove` を拒むことは、先行例の記述で、このリポジトリでは未実測 → CHG-0029 に取り入れた
2. **自分が作ったものだけを扱う**（Claude Code の目印）。Cursor の失敗（外部のものも削除）を避ける → 取り入れた
3. **同時に持つ数の上限**は、先行例にある（Cursor 25・Codex 約 15）。ただし先行例は自動で削除する。今回は、上限を超えたら新しい子の起動を拒否する → 取り入れた
4. **filter driver の確認**（Claude Code が作成を拒む）。clean filter は `git add -A` の間に任意のコマンドを実行しうる → 起動前の確認に足す案として取り入れた
5. **状態を検証できないときは自動で削除しない**（Claude Code）→ 取り入れた
6. **`.worktreeinclude` 相当**（ignored のファイルを選んでコピー）は、Claude Code と Cursor（セットアップのスクリプト）にある → W2 以降の候補
7. **Codex の「削除の前にスナップショット」**は、今回の「未取り込みの成果物は消さない」で足りるため、取り入れない

### 未確認

- Codex・Conductor・vibe-kanban・claude-squad の一次情報。Cursor の起点と隔離の強制の記述（本調査では読んでいない項目）
- Claude Code の `git worktree lock` が、`git worktree remove` を実際に拒むか（このリポジトリの git 2.43.0 では未実測）
- 各ツールのコミットの hook の扱い
- 実機での挙動。docs の記述と実装のずれ

## 記録 P8 — 2026-10-31: tok/s の拡張（`speed` の測り方の比較）

- **問い**: 応答ごとの TTFT・decode 速度をステータス行に出す拡張 `speed` の測り方は、公開の拡張と推論側の議論に照らして妥当か
- **方法と限界**: 公開の README・issue を読んだだけ。**拡張は導入しておらず、実コードは読んでいない**（README の記述が根拠）。取得日は 2026-10-31。実機の TUI・Orca での見え方、Copilot 経由の reasoning の出方は未確認

| 対象 | 方式（README・議論から） | 出典 |
| --- | --- | --- |
| `pi-tps` | 応答ごとに tok/s を出す表示系の拡張 | <https://github.com/monotykamary/pi-tps> |
| `pi-token-speed`（上位 150 件の「観測・計測」にある） | トークン速度の表示。時刻の取り方の詳細は未読 | <https://github.com/gsanhueza/pi-token-speed> |
| 推論側の議論 | TTFT を「thinking を含む最初のトークン」までとする定義の議論 | <https://github.com/kubernetes-sigs/inference-perf/issues/559> |

- **採った点**: TTFT の定義は、thinking を含む最初のトークンまで（上の議論に揃えた）。1 回のモデル呼び出し（1 つの assistant メッセージ）を単位にし、ツール実行の時間を入れない
- **自作で決めた点（事実は 1.4.0 の型・文書による）**: 最初のトークンは `provider_stream_event` ではなく `message_update` の `*_delta` で取る。前者の `data` は提供元ごとの生の値（`unknown`）で、最初の 1 件が内容のデルタか接続開始のような別種かを、型からは区別できないため。出力 30 トークン未満・decode 区間 0.3 秒未満は `—`。reasoning が出ない経路の過小は `~` で示す
- **未確認**: 公開の 2 つの実コード、実機の TUI・Orca の見え方、Copilot 経由で reasoning がストリームに出ないこと（`usage.reasoning` と thinking のデルタの有無の食い違いで検出する設計の実測）

## 付録: 上位 150 件の分類

括弧内は月間ダウンロード数の順位（2026-10-20 時点）。

- **MCP**（6 件）: `pi-mcp-adapter`(1)、`pi-mcp-extension`(6)、`@agimon-ai/log-sink-mcp`(25)、`@datadog/pi-plugin`(79)、`donsetch`(102)、`@agimon-ai/doompi-mcp`(137)
- **Web 検索・取得**（4 件）: `pi-web-access`(3)、`pi-web-search`(26)、`@ollama/pi-web-search`(107)、`@juicesharp/rpiv-web-tools`(114)
- **サブエージェント・並列実行・背景実行**（11 件）: `pi-subagents`(4)、`pi-background-tasks`(15)、`@tintinweb/pi-subagents`(36)、`gentle-pi`(37)、`@akagilnc/pi-workflow-roles`(38)、`@henryqw/pi-subagent`(55)、`@quintinshaw/pi-dynamic-workflows`(65)、`@henryqw/pi-task-models`(73)、`pi-gauntlet`(86)、`@chankov/agent-fleet`(89)、`@agimon-ai/doompi-team`(134)
- **コンテキスト圧縮・記憶**（14 件）: `billion-context`(2)、`context-mode`(14)、`pi-memory`(28)、`billion-context-pi`(31)、`@moyai/pi-session-hoarder`(41)、`gentle-engram`(46)、`pi-hermes-memory`(60)、`@d3ara1n/pi-context-include`(82)、`pi-blackhole`(106)、`@sting8k/pi-vcc`(117)、`@cortexkit/pi-magic-context`(120)、`@astrosheep/pi-context`(126)、`pi-observational-memory`(144)、`@pi-unipi/compactor`(149)
- **観測・計測**（8 件）: `@langfuse/pi-observability-plugin`(7)、`@langchain/langsmith-pi-extension`(18)、`@raindrop-ai/pi-agent`(34)、`@braintrust/pi-extension`(44)、`@agimon-ai/doompi-telemetry`(61)、`pi-otel`(93)、`pi-context-view`(135)、`pi-token-speed`(140)
- **計画・目標・ToDo・質問**（12 件）: `@juicesharp/rpiv-ask-user-question`(8)、`@juicesharp/rpiv-todo`(9)、`pi-goal-x`(10)、`@plannotator/pi-extension`(11)、`@schovest/pi-goal`(24)、`@narumitw/pi-goal`(49)、`@narumitw/pi-plan-mode`(52)、`pi-interview`(62)、`@mjasnikovs/pi-task`(74)、`pi-until-loop`(88)、`pi-ask-user`(94)、`pi-goal-list-loop-audit`(95)
- **UI・フッター・表示**（10 件）: `pi-powerline-footer`(16)、`pi-cc-extensions`(21)、`@heyhuynhgiabuu/pi-pretty`(64)、`@agimon-ai/doompi-ui`(78)、`pi-markdown-preview`(80)、`pi-open-tui`(83)、`pi-zentui`(85)、`@herbertgao/pi-cc-extensions`(113)、`pi-pigment`(124)、`@pi-unipi/info-screen`(128)
- **プロバイダ・モデル・認証**（18 件）: `pi-claude-bridge`(19)、`@narumitw/pi-usage`(20)、`pi-advisor-flow`(22)、`@narumitw/pi-retry`(53)、`pi-provider-litellm`(54)、`pi-muse-msp`(57)、`pi-ollama-cloud-link`(58)、`@howaboua/pi-codex-conversion`(69)、`@gotgenes/pi-anthropic-auth`(72)、`pi-antigravity`(77)、`pi-fireworks`(87)、`pi-nvidia-nim`(90)、`pi-bifrost`(98)、`pi-cursor-sdk`(99)、`pi-extension-nvidia-nim`(109)、`pi-fireworks-quota`(111)、`pi-commandcode-provider`(123)、`pi-llama-cpp`(141)
- **安全（権限・サンドボックス・ガード）**（6 件）: `@gotgenes/pi-permission-system`(23)、`cc-safety-net`(27)、`@trim21/personal-pi-extensions`(59)、`pi-better-harness`(118)、`@agimon-ai/doompi-sandbox`(119)、`pi-warden`(132)
- **コード理解・編集支援**（7 件）: `pi-lens`(17)、`@ff-labs/pi-fff`(33)、`pi-hashline-edit-pro`(67)、`@agimon-ai/doompi-hashline`(81)、`@narumitw/pi-lsp`(112)、`opencode-codebase-index`(148)、`pi-rtk-optimizer`(96)
- **別の入口・連携**（7 件）: `pi-acp`(5)、`pi-web-ui`(70)、`@awebai/oats-pi`(91)、`@llblab/pi-telegram`(92)、`@pi-unipi/notify`(103)、`@vincenthanxiaodu/pi-web`(108)、`@jmfederico/pi-web`(121)
- **スキル集・ワークフロー一式**（14 件）: `@postman/postman-plugin`(12)、`bigpowers`(13)、`@mutmutco/pi-plugin`(43)、`@jwilger/pi-development-system`(75)、`@selesai/code`(97)、`rolebox`(100)、`pi-claude-marketplace`(110)、`bestony-pi-preset`(115)、`pi-code`(116)、`@difflab/pi`(131)、`@brainervirus/workit-pi`(139)、`@maxiaochao/pi-toolkit`(142)、`@pi-unipi/unipi`(143)、`@agimon-ai/doompi`(147)
- **その他**（33 件）: `pi-simplify`(29)、`pi-harness-runtime`(30)、`pi-btw`(32)、`pi-fabric`(35)、`@juicesharp/rpiv-i18n`(39)、`pi-cache-optimizer`(40)、`@narumitw/pi-btw`(42)、`@onkernel/browser-loop`(45)、`pi-intercom`(47)、`pi-agent-browser-native`(48)、`@goofansu/pi-stuff`(50)、`pi-prompt-template-model`(51)、`@agimon-ai/doompi-web-components`(56)、`@cratis/pi`(63)、`@pi-unipi/core`(66)、`agent-simple-english`(68)、`@agimon-ai/doompi-extension-contracts`(71)、`@a5c-ai/babysitter-pi`(76)、`@getpipher/vision`(84)、`pi-typesafe`(101)、`@agimon-ai/doompi-cache`(104)、`@henryqw/pi-add-dir`(105)、`@agimon-ai/doompi-model-guidance`(122)、`pi-autocontext-sports`(125)、`@amaster.ai/pi-image-gen`(127)、`@hypabolic/pi-hypa`(129)、`pi-quiver`(130)、`@agimon-ai/doompi-hook`(133)、`@juicesharp/rpiv-btw`(136)、`@juicesharp/rpiv-advisor`(138)、`@agimon-ai/doompi-voice`(145)、`@pi-unipi/utility`(146)、`@pi-unipi/btw`(150)
