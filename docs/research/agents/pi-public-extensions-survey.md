# pi の公開拡張の調査と、使えないことの不利益

<!-- 現在の運用の正本は docs/spec/pi-guard.md。ここは「いつ何を調べ・測ったか」を積む場所 -->

## 記録 P1 — 2026-10-20

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

## 記録 P4 — 2026-10-20: ask-user 系拡張の方式（自作 `ask` の設計の参考）

- **方法**: README と docs を読んだだけ（取得・実行・コード複写なし。コード本体は未読）。README の主張は未検証
- **出典**: `juicesharp/rpiv-mono` の `rpiv-ask-user-question`（README・`docs/tool-schema.md`・`docs/hosts.md`）、`edlsh/pi-ask-user` の README、
  同リポジトリの issue #291・#301・#310・#313、`Gentleman-Programming/gentle-shell` #1277（検索語: `pi-ask-user pi coding agent extension ask_user tool README`、`rpiv-ask-user-question issue bug`）
- **方式**: どちらも 1 回の呼び出しで 4 問まで尋ねる。`rpiv` の RPC 経路は 1 問ずつの `select` / `input` で、タブ画面は TUI だけ。
  非対話では `before_agent_start` でツールを外す。自由記述の行を自動で足し、`Other` などのラベルを予約する。`pi-ask-user` にはタイムアウトがある
- **反例・注意**: 空の自由記述が記録される (#301)、部分回答で飛ばした問が見分けられない (#291)、codemode `only` で呼ばれない (#310。原因は推測)、
  同名ツールの二重登録で起動が失敗する (gentle-shell #1277)
- **自作への反映**: 名前は `ask`（衡突回避）、予約ラベル、空入力は選択肢へ戻す、`unanswered` を返す、待ち上限 5 分。タブ画面・プレビュー・メモ・BEL は後回し

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
