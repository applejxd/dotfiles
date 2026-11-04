# `/goal`（目標を 1 回設定して自走する機能）の先行実装の調査

<!-- 現在の総合判断は docs/change/ の候補比較表が正本。
     ここは「いつ何を観測したか」を積む場所。設計の決定はしない（取り入れ候補・見送り候補までが範囲） -->

## 記録 G1 — 2026-11-05

- **観測日**: 2026-11-05（すべて公開情報の読解。**どの実装も手元で実行していない**）
- **対象の版**: Claude Code 2.1.139 で導入（公式 docs の記述は 2.1.269〜2.1.293 の時点を含む）/ Codex CLI 0.128.0 で導入
  （2026-04-30）/ Hermes Agent の PR #18262 / OpenCode 2.2.1（2026-10-29）で内蔵 / pi の拡張は各 npm 版（下の表）
- **原文の置き場**: 作業ツリーの `.tmp/research/goal-command/sources/`（コミットしない）。以下の「原文」欄は
  `sources/<ファイル名>:<行>` の形。**公開の再確認は出典 URL から行う**

### 問い

pi（このリポジトリで拡張・フルガードを自作）に `/goal`（利用者が完了条件を 1 回設定すると、満たされたと評価されるまで、
または予算・停止条件まで、利用者の入力なしに自走する機能）を足すとき、先行実装から何を取り入れ、何を見送るか。
この記録は**事実と比較と候補**までで、設計の決定は別の段で行う。

### 要旨

1. `/goal` 類は 2026-04〜10 に急速に広まり、**公式実装 8 件・pi 向け拡張 10 件超・OpenCode 向け外部 plugin 4 件超**を確認した
   （Claude Code・Codex CLI・Hermes・OpenCode 2.2.1+・Cursor・Kimi Code・Copilot CLI の autopilot（`/goal` は別名）・
   Antigravity CLI〈二次情報のみ〉）。祖先は Ralph ループ（2025）。
2. **共通の骨格**は「目標を 1 つ・セッション（スレッド）に紐づけて保存 →ターン終了（アイドル）で続行の可否を判定 →
   続行なら非表示の継続メッセージを注入」。差は**誰が完了を判定するか**・**続行をどの層で起こすか**・**状態をどこに持つか**。
3. 完了判定は 3 方式に分かれる: (a) 別の小型モデルが評価（Claude Code・Hermes・OpenCode 内蔵）、(b) 作業役自身が
   証拠つきで自己申告（Codex・pi 拡張の多数）、(c) 決定的な検査コマンド／独立の検証役（Hermes の gate・pi-goal-x・OpenCode plugin）。
4. **最も多い失敗は費用の暴走と止まらないこと**: Codex は目標のあるセッション 1.4% が入力トークンの 49% を消費（実測の報告）、
   Claude Code は利用者の「stop」を評価役が無視して 3 日続けた報告、Ralph プラグインは `--max-iterations=5` の書式で
   無視され 462 反復。**上限・無進捗の検知・利用者の停止の優先**が全実装で後から足されている。
5. 評価役は**作業の記録（transcript）しか見ない**のが普通（Claude Code は明記）。そのため「評価役が見える形で証拠を出させる」
   完了条件の書き方（検証コマンド・証拠・制約・停止条件）が各社の docs の中心の助言になっている。
6. pi 向けには、`agent_settled` を使う実装（`@schovest/pi-goal`・`@hank-warren/pi-loop`）が、再試行・圧縮・キューが落ち着いた
   境界でだけ続行する設計を共通に採っていた。**このリポジトリの pi 1.4.0 の実験記録（`agent_settled` からの `triggerTurn` が連鎖する）と整合**。
7. 未確認の主な点: 各実装の評価役プロンプトの全文・実機の挙動（動かしていない）、Antigravity は二次情報のみ、
   Kimi の詳細 docs は取得できず（ヘルプ・スラッシュコマンド一覧のみ）、Cline・Aider・Amp・SWE-agent・Continue は
   `/goal` 類を確認できなかった。

### 対象の一覧と確認状況

「確認済み」= 公式 docs・ソース・README・issue の原文を取得して読んだ。「一部」= 一部の面だけ。「未確認」= 取得できず。

| # | 対象 | 種別 | 確認状況 | 主な出典 |
| --- | --- | --- | --- | --- |
| 1 | Claude Code `/goal`（2.1.139〜） | 公式 | 確認済み（docs・changelog・issue 7 件。実装ソースは非公開） | [docs](https://code.claude.com/docs/en/goal) |
| 2 | Codex CLI `/goal`（0.128.0〜） | 公式 | 確認済み（cookbook・use case・5 PR の解説〈二次〉・issue）。ソース本体は issue 内の行リンクのみ | [cookbook](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) |
| 3 | Hermes Agent `/goal` | 公式 | 確認済み（docs 全文・PR #18262） | [docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/goals) |
| 4 | OpenCode 内蔵 `/goal`（2.2.1〜） | 公式 | 確認済み（PR #59437 の説明） | [PR](https://github.com/anomalyco/opencode/pull/59437) |
| 5 | Ralph ループ（Huntley）と ralph-loop プラグイン | 手法・公式 plugin | 確認済み（README・原典・issue）。`stop-hook.sh` 本体は URL が 404 で未取得 | [原典](https://ghuntley.com/ralph/) |
| 6 | Cursor `/goal` | 公式 | 一部（docs の数行のみ。「展開中」の注記） | [docs](https://cursor.com/docs/agent/overview) |
| 7 | Kimi Code `/goal` | 公式 | 一部（スラッシュコマンド一覧。詳細 guide は 404） | [docs](https://moonshotai.github.io/kimi-code/en/reference/slash-commands.html) |
| 8 | GitHub Copilot CLI autopilot（`/goal` は `/autopilot` の別名） | 公式 | 一部（autopilot の docs は確認。別名は検索結果の抜粋のみ） | [docs](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot) |
| 9 | Antigravity CLI（agy）`/goal` | 二次 | 一部（個人サイトの解説のみ。公式未確認） | [解説](https://neurals.ca/tech/gemini/antigravity/goal-mode/) |
| 10 | pi 向け: `@schovest/pi-goal` | 拡張 | 確認済み（README 全文） | [pi.dev](https://pi.dev/packages/@schovest/pi-goal) |
| 11 | pi 向け: `pi-codex-goal` | 拡張 | 確認済み（README） | [pi.dev](https://pi.dev/packages/pi-codex-goal) |
| 12 | pi 向け: `pi-goal-x`（独立の auditor） | 拡張 | 確認済み（README） | [pi.dev](https://pi.dev/packages/pi-goal-x) |
| 13 | pi 向け: `@zhushanwen/pi-goal` | 拡張 | 確認済み（README） | [pi.dev](https://pi.dev/packages/@zhushanwen/pi-goal) |
| 14 | pi 向け: `pi-better-goal` | 拡張 | 確認済み（README の前半） | [pi.dev](https://pi.dev/packages/pi-better-goal) |
| 15 | pi 向け: `@hank-warren/pi-loop` | 拡張 | 確認済み（README） | [pi.dev](https://pi.dev/packages/@hank-warren/pi-loop) |
| 16 | pi 向け: `@tmustier/pi-ralph-wiggum` | 拡張 | 確認済み（README） | [pi.dev](https://pi.dev/packages/@tmustier/pi-ralph-wiggum) |
| 17 | pi 向け: `@derogab/pi-goal`・`pi-goal`・`@pi-unipi/long-horizon` | 拡張 | 一部（README の冒頭。unipi は goal/ralph/swarm/graph の 4 モード） | [pi.dev](https://pi.dev/packages/@pi-unipi/long-horizon) |
| 18 | pi 向けの他（`@narumitw/pi-goal`・`@signalridge/pi-goal`・`@amaster.ai/pi-goal`・`pi-goal-list-loop-audit`・`pi-braid`・`pi-warden`・`kijek` など） | 拡張 | **未確認**（一覧の説明文のみ） | [awesome-pi](https://awesome-pi.site/extensions/) |
| 19 | OpenCode 向け外部 plugin（`opencode-goal-plugin`〈保守のみ〉・`@prevalentware/opencode-goal-plugin` など） | plugin | 確認済み（README の前半） | [GitHub](https://github.com/william-ricchiuti/OpenCode-goal-plugin) |
| 20 | OpenHands の stuck 検知（`/goal` ではない。反復上限の側の知見） | 公式 | 確認済み（docs） | [docs](https://docs.openhands.dev/sdk/guides/agent-stuck-detector) |
| 21 | Goose の recipe の retry・`max_turns` | 公式 | 一部（docs の見出し行のみ） | [docs](https://goose-docs.ai/docs/guides/recipes/recipe-reference/) |
| 22 | Gemini CLI・Cline・Aider・Amp・Continue・SWE-agent | 公式 | **未確認**（`/goal` 類は見つからず。Gemini CLI はコミュニティ製の autoresearch skill のみ。Amp は Ralph の原典のシェルループに登場） | — |

`/goal` 類似として 1 件だけ**無関係**と判定したもの: `pi-until-loop`（README は外部の SaaS「Until」への接続で、目標つき自走ではない）。

### 実装ごとの表（観点 ①〜⑧）

凡例: 「原文」は `sources/` 内のファイル名と行。行は取得時のもの。

#### 1. Claude Code `/goal`（2.1.139〜、公式）

| 観点 | 内容 |
| --- | --- |
| ① 面 | `/goal <条件>`（設定。既存は置換。すぐ 1 ターン開始）、`/goal`（状態: 条件・経過時間・評価済みターン数・トークン・最後の理由）、`/goal clear`（別名 stop/off/reset/none/cancel）。条件は最大 4,000 字。一時停止・再開・編集のコマンドは**無い**。`-p` でも動く（`claude -p "/goal …"` は完了まで 1 回で走る）。`◎ /goal active` の表示。原文 `claude-goal-doc.md:95,111,127-` |
| ② 完了判定 | **別の小型の高速モデル**（既定は haiku 系。`ANTHROPIC_DEFAULT_HAIKU_MODEL` で変更。他の用途と共有）が**ターンごと**に、条件と**会話の記録だけ**を見て 3 値: 未達 / 達成 / 不可能。ツールは呼ばず、コマンド実行もファイル読みもしない。評価の費用は主ターンに比べ「無視できる」と docs。`claude-goal-doc.md:102,175-181,241-245` |
| ③ 続行 | `/goal` は**セッション単位の prompt 型 Stop hook のラッパー**。評価が「未達」なら理由を次ターンの指針にして続ける。バックグラウンドの subagent・シェルが動いている間は評価を飛ばし、30 分で check-in（以降 1 時間・2 時間と間隔を伸ばす。`CLAUDE_CODE_GOAL_CHECKIN_MINUTES`、0 で無効）。アイドル時の check-in は最大 3 回。`claude-goal-doc.md:175,223-` |
| ④ 保存 | セッションの記録（transcript）内のみ。`--continue`/`--resume` で**条件は復元**されるが**ターン数・時計・トークンの基準は 0 に戻る**。達成・クリア済みは復元しない。`/clear` で消える。`claude-goal-doc.md:146-` |
| ⑤ 停止条件 | 達成・不可能判定・認証失敗／クレジット枯渇／圧縮で戻せない文脈あふれ／使えないモデル（この 4 種は目標を**消す**）・過負荷等は 3 回まで自動再試行して**一時停止**・レート制限・利用上限は**一時停止**（上限解除で自動再開）。**ターン数・時間・費用の上限は無い**（条件の文に「20 ターンで止める」と書くと評価役が会話から判定）。ツール未使用が数ターン続くと停止して制御を返す（無進捗の検知）。Stop hook の連続ブロックは既定 9 回で打ち切る。`claude-goal-doc.md:109-113,183,196-215`、`cc-issue-101528.md` |
| ⑥ 介入 | 利用者のメッセージで即座に次ターン。manual 権限モードでは許可されていないツール呼び出しで確認が出る（auto モードと併用が前提）。非対話は Ctrl+C。評価理由は Ctrl+O で見られる。**エージェントが目標を一時停止・消去する手段は無い**（issue #101528）。`claude-goal-doc.md:91-95,166-` |
| ⑦ 問題 | 後述「失敗談」。issue #101528（利用者の停止を無視）・#93744（評価役が `/goal` の引数を見られない）・#58348（未登録のスキルを参照する目標で無限ループ）・#85594・#67665・#68911（無限ループ報告）。changelog に、文脈あふれ・圧縮後の目標の消失・API エラーでの黙った停止の修正（`claude-code-changelog.md:7237,7239,7864`） |
| ⑧ 版・根拠 | 導入 2.1.139（`claude-code-changelog.md:14226`）。docs 取得 2026-11-05。出典 <https://code.claude.com/docs/en/goal> 、<https://code.claude.com/docs/en/changelog> |

#### 2. Codex CLI `/goal`（0.128.0〜、公式。2026-04-30 導入）

| 観点 | 内容 |
| --- | --- |
| ① 面 | `/goal <目標>`、`/goal`（表示）、`/goal pause` / `resume` / `clear`。トークン予算は**モデルが `create_goal` の引数で設定**（CLI に予算の選択 UI は無く、機能要望 #36590）。ChatGPT デスクトップ・IDE 拡張にもある。`codex-cookbook-goals.md:31,60-84` |
| ② 完了判定 | **作業役（同じモデル）が自己申告**。`update_goal` は `status: complete` にしかできず、継続プロンプトが**「完了前に目標を具体的な証拠（ファイル・テスト・ログ・成果物）と突き合わせる監査」を要求**。別モデルの評価役は**無い**。`codex-cookbook-goals.md:168,188,192`、`codex-impl-gist.md`（PR 3） |
| ③ 続行 | ランタイムのイベント（`TurnStarted`/`ToolCompleted`/`TurnFinished`/`TaskAborted`/`ThreadResumed`/`MaybeContinueIfIdle` など）が、**スレッドがアイドルで、目標が active かつ予算内のときだけ**継続ターンを開始。計画だけのモードは対象外。**ツール呼び出しが 0 の継続ターンは次の自動継続を抑止**（無限空回りの防止）。排他は Semaphore(1)。`codex-impl-gist.md`（PR 4）、`codex-cookbook-goals.md:167,184` |
| ④ 保存 | **SQLite の `thread_goals` テーブル（スレッド 1 件に目標 1 つ）**: goal_id・objective・status（active/paused/budget_limited/complete）・token_budget・tokens_used・time_used_seconds。置換のたびに新しい goal_id（遅れて届く古い集計を無視する版管理）。app-server に `thread/goal/` の set・get・clearと更新通知。スレッド再開で paused を active に戻す。`codex-impl-gist.md`（PR 1・2） |
| ⑤ 停止条件 | 完了・予算超過（`budget_limited`・終端）・割り込みで pause・連続 3 回の実行失敗で blocked。予算に近づくと**収束用の steering を注入**し、完了ターンには出さない。トークン予算は**既定なし**。時間は記録のみ。`codex-impl-gist.md`（PR 4）、`codex-issue-44909.md:63-`（`token_budget` 既定 None、3 回失敗で blocked） |
| ⑥ 介入 | 割り込みで自動 pause、`pause`/`resume`/`clear`。**モデルは pause/resume できない**（意図的な非対称）。目標の作成は「利用者・system/developer が明示したときだけ」とツール説明に明記。`codex-impl-gist.md`（PR 3） |
| ⑦ 問題 | #44909（目標のあるセッションが入力トークンの約半分を消費、空の継続が 0.03 秒で再起動）、#41831（人間時間の一時停止を無視して 12 ターンで 126 万トークン）、#23003（圧縮の失敗の連続で 5 時間分の枠を 45 分で消費）、#19910（圧縮の途中で継続プロンプトと監査要件が失われる）、#24629（利用者が頼んでいない予算をモデルが自分で設定）、#34215（予算超過後に上げて再開できない）、#56927（早すぎる完了と過剰なトークン） |
| ⑧ 版・根拠 | 0.128.0（2026-04-30）。cookbook 2026-05-09、5 PR の解説 gist（二次、2026-06-04 更新）。issue は 0.144〜0.154 時点。出典 <https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex> 、<https://gist.github.com/patleeman/b1b5768393f9bf2f60865b1defeeb819> |

#### 3. Hermes Agent `/goal`（Nous Research、公式）

| 観点 | 内容 |
| --- | --- |
| ① 面 | 最も広い。`/goal <text>`・`status`・`pause`・`resume`（ターン数を 0 に戻す）・`clear`・`show`・`draft <text>`（目標から**完了契約**を生成）・`wait <pid>`/`unwait`・`gate add/list/remove/clear`・`/subgoal`（実行中に基準を追加）。インラインの契約（`verify:`・`constraints:`・`boundaries:`・`stop when:`）。CLI・TUI・Desktop・メッセージングで共通のハンドラ。`hermes-goals-doc.md:50-80,100-132` |
| ② 完了判定 | **補助モデル（`goal_judge`）がターンごと**に、目標と**直近の最終応答（末尾約 4 KB）**を見て JSON 1 行で `done`/`blocked`/`continue`/`wait`。既定は主モデル、安いモデルに差し替え可。**契約があると「検証基準が具体的な証拠で満たされたときだけ done」**。さらに**決定的な品質ゲート（シェルコマンドが exit 0）を判定役より先に実行**し、失敗ならジャッジを呼ばず出力の末尾約 3 KB を継続プロンプトにする。`hermes-goals-doc.md:136-152,200-` |
| ③ 続行 | 継続プロンプトを**同じセッションにふつうの user メッセージとして追記**（system prompt を変えず prompt cache を壊さない）。CLI は `_pending_input`、gateway は adapter の FIFO で、**利用者の実メッセージが常に先に**走る。`hermes-goals-doc.md`（Behavior details） |
| ④ 保存 | `SessionDB.state_meta` の `goal:<session_id>` に目標・契約・サブゴール・ゲート・待ちの柵を保存。`/resume` で復元、**圧縮を跨いで残る**。`hermes-goals-doc.md:119,152,175` |
| ⑤ 停止条件 | **ターン予算（既定 20、`goals.max_turns`）で自動 pause**（`/goal resume` で 0 に戻して続行）。ジャッジの異常は **fail-open（continue 扱い）**でターン予算が真の防壁。`blocked`（達成不能・利用者の入力待ち）は pause。ゲートは既定 3 回の再試行・5 分で pause。待ちは pid で最大 30 分。`hermes-goals-doc.md`（Turn budget・Fail-open・Quality gates）、`hermes-pr-18262.md:75` |
| ⑥ 介入 | 実メッセージが継続に優先。実行中の `status`/`pause`/`clear`/`wait` は安全、**実行中の新しい目標の設定は拒否**（`/stop` を先に）。上限到達時は `⏸ Goal paused — 20/20 turns used` と次の手を表示。 |
| ⑦ 問題 | docs 自身が、偽陰性（done なのに continue）はターン予算で止まり、偽陽性（done と誤判定）は利用者が気付くしかないと明記。ジャッジを保守的にして偽陽性を減らす設計（`hermes-goals-doc.md` の「When the judge gets it wrong」） |
| ⑧ 版・根拠 | PR #18262（teknium1）。Codex 0.128.0 に**着想を得た独立実装**と明記（Ralph ループの自分たちの版）。docs の main を 2026-11-05 取得。出典 <https://hermes-agent.nousresearch.com/docs/user-guide/features/goals> 、<https://github.com/NousResearch/hermes-agent/pull/18262> |

#### 4. OpenCode 内蔵 `/goal`（2.2.1〜、公式。2026-10-29）

| 観点 | 内容 |
| --- | --- |
| ① 面 | `/goal <目標>`（最大 4,000 字）・`pause`・`resume`・`clear`・素の `/goal` で状態。TUI に `◎ goal`/`paused`/`met` の表示とダイアログ。`opencode run` では未対応。`opencode-pr-59437.md:233-265` |
| ② 完了判定 | **セッション自身のモデルが reviewer として**（`ctx.session.generate`。履歴全体とキャッシュ済みの接頭辞を共有）JSON 1 行で `done`/`continue`/`blocked`/`paused`（利用者が止めた）/`wait`。**評価役モデルの指定は未実装**（PR の「Not in this PR」）。`opencode-pr-59437.md:203,277` |
| ③ 続行 | 新設の **Session idle plugin hook** で、セッションがアイドルになる地点に**同じ実行の内側で**非表示の継続メッセージ（`<untrusted_objective>` で目標を包む）を投入。利用者の入力が先。`opencode-pr-59437.md:99-131,205` |
| ④ 保存 | セッションの metadata（`opencode.goal`: id・objective・status・reason・rounds・maxRounds・boot・updatedAt）。**プロセスの boot ID で、前のプロセスの active な目標を起動時に pause**。圧縮後は目標の短い注意書きを注入。書き込みは再読込のうえ「変わっていなければ」だけ適用（利用者の `/goal pause` が勝つ）。`opencode-pr-59437.md:211-230` |
| ⑤ 停止条件 | **無進捗**（直近の起動以降ツール呼び出しなし、または reviewer が前と同じ理由）が 3 ラウンド続くと pause。**隠れた 50 ラウンドの上限**（UI に出さない）。実行終了後 30 分何も動かなければ pause。reviewer が文脈あふれなら圧縮して再質問、同ラウンドで 2 回目なら pause。**トークン予算は無し**（PR で未実装と明記）。`opencode-pr-59437.md:209-219,277` |
| ⑥ 介入 | 実行中でも `/goal` コマンドは即時。reviewer の理由は UI に出さない（Codex・Claude Code と同じ）。 |
| ⑦ 問題 | 取り込み直後（2 日前）で実運用の報告は未確認。外部 plugin 作者は「内蔵は独立 verifier・複数目標・ターン／時間／トークン／費用の上限を持たない」と明記して保守のみにした |
| ⑧ 版・根拠 | 2.2.1（2026-10-29、PR #59437）。出典 <https://github.com/anomalyco/opencode/pull/59437> |

#### 5. Ralph ループと ralph-loop プラグイン

| 観点 | 内容 |
| --- | --- |
| ① 面 | 原典は `while :; do cat PROMPT.md を claude-code へ渡す; done`（パイプのシェルループ）（毎周**新しい文脈**で同じプロンプトを再投入）。公式プラグイン: `/ralph-loop "<prompt>" --max-iterations N --completion-promise "<text>"`、`/cancel-ralph`。`huntley-ralph.md:25`、`ralph-loop-plugin-readme.md` |
| ② 完了判定 | **作業役の自己申告**: 出力に `<promise>COMPLETE</promise>` を含めると終了。**文字列の完全一致**で、複数の条件（SUCCESS/BLOCKED）は表せない。原典の手法では決定的な「背圧」（コンパイラ・テスト・型検査）が実質の判定。`ralph-loop-plugin-readme.md`（Escape Hatches の注記） |
| ③ 続行 | プラグインは **Stop hook が終了を阻止し、同じプロンプトを再投入**（同じセッション内。ループは状態ファイル＋hook）。原典は外側のシェルループ（毎周**別の文脈**）。 |
| ④ 保存 | プラグインは Markdown の状態ファイル（frontmatter）。原典はファイル（`PROMPT.md`・`fix_plan.md`・git 履歴）に進捗を持ち、文脈には持たない。 |
| ⑤ 停止条件 | `--max-iterations`（**既定は無制限**）・合言葉・手動の取り消しのみ。README は「必ず `--max-iterations` を安全網にせよ」と助言。 |
| ⑥ 介入 | 取り消しコマンド。Esc で止められる（pi 版）。 |
| ⑦ 問題 | #18646: `--max-iterations=5`（`=` 付き）を引数解析が**黙って無視**し、無制限で 462 反復。HumanLayer の記録は、プラグインを「hook が分かりにくい場所に入り、状態の Markdown を消すと repo の claude が壊れる」「Ralph の要点は永遠に走らせることではなく**小さな仕事を独立した文脈に切り出すこと**」と批判。原典自身が `overbaking`（走らせすぎると奇妙な創発的挙動）を述べる。`ralph-issue-18646.md:63-101`、`humanlayer-history-of-ralph.md:21,135-137` |
| ⑧ 版・根拠 | 原典の公開 2025-07（ghuntley.com/ralph）、2025 年末に流行。プラグインは anthropics/claude-plugins-official の `ralph-loop`（取得 2026-11-05）。出典 <https://ghuntley.com/ralph/> 、<https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop> |

#### 6. その他の CLI

| 対象 | ① 面 | ② 完了判定 | ③ 続行 | ④ 保存 | ⑤ 停止 | ⑥ 介入 | ⑦ 問題 | ⑧ 根拠 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Cursor | `/goal <目標>`（「展開中」）、CLI は Ctrl+C で pause、`/loop` と併用 | 不明（docs に記述なし） | 不明 | 不明 | 不明 | Ctrl+C | 未確認 | <https://cursor.com/docs/agent/overview> （`cursor-agent-overview.md:148-156`）。長時間エージェントの別の知見は下の「設計の知見」 |
| Kimi Code | `/goal`・`status`・`pause`・`resume`・`cancel`・`replace`・`next`（**目標のキュー**）・`next manage`。`-p` で作成のみ。終了コード 0=完了・3=blocked・6=paused | 不明（docs の guide は未取得） | 自動継続ターン | 不明 | 例: 「20 ターン後も blocked なら止める」を目標文に書く | manual 権限では承認で止まる | 未確認 | <https://moonshotai.github.io/kimi-code/en/reference/slash-commands.html> （`kimi-slash-commands.md:103-130`） |
| Copilot CLI | `/autopilot [目的]`（`/goal` は別名と二次情報）、Shift+Tab のモード、`--autopilot -p` | モデルが完了と判断（docs。「継続の制御」と「承認」と「質問抑止」を**3 つの別の軸**として分離） | 自動継続メッセージ | 不明 | `--max-autopilot-continues N`・`--max-ai-credits`（ソフト上限）・`/limits` | Esc 2 回で中断、Shift+Tab で次の prompt を通常に。権限は「全許可を推奨」だが sandbox を勧める | 未確認 | <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot> （`copilot-autopilot-doc.md`）。「sticky」な autopilot（`stayInAutopilot`） |
| Antigravity CLI（二次） | `/goal` で**計画の承認を飛ばして**完了まで実行（計画は内部の `.gemini` に自動承認で書く）。ツール分類ごとの 1 回限りの許可は残る | 「目標が満たされるまで」（機構の詳細なし） | 不明 | 不明 | 不明 | 人の確認点を「計画前」から「完了後」へ移す | 未確認 | <https://neurals.ca/tech/gemini/antigravity/goal-mode/> （二次。`antigravity-goal.md:131-168`） |
| OpenHands | `/goal` ではない。stuck 検知（既定で有効） | — | — | — | 同じ行動＋観測の繰り返し 4 回以上・同じ行動＋エラー 3 回以上・独白 3 メッセージ以上・交互のパターン 6 周以上・文脈あふれのループ。`max_iteration_per_run` | 検知で自動停止 | issue #6104: 文脈あふれのループは検知できず上限まで繰り返す／#6277: 検証ループの見落とし | <https://docs.openhands.dev/sdk/guides/agent-stuck-detector> （`openhands-stuck-detector.md`） |
| Goose | `/goal` ではない。recipe の `retry`（成功基準を満たさないと再試行）・`settings.max_turns` | 成功基準（recipe の定義） | 再試行 | 不明 | `max_turns`・timeout | — | issue #13186: PreToolUse hook が `final_output` を拒否すると継続メッセージが拒否文を上書きして上限まで再試行 | <https://goose-docs.ai/docs/guides/recipes/recipe-reference/> （`goose-recipe-reference.md:67,440`、一部） |

#### 7. pi 向けの拡張（npm・2026-11-05 時点の pi.dev の記載）

pi.dev の `awesome-pi` 一覧で `goal`・`loop`・`ralph`・`autopilot` を含む名前・説明を機械的に拾って**約 40 件**。そのうち下の 8 件は README を読んだ。
**一覧は網羅ではなく、中身を読んでいないものは未確認**（月間ダウンロードは一覧の値で、人気の目安にすぎない）。

| 拡張（版・公開日） | ① 面 | ② 完了判定 | ③ 続行 | ④ 保存 | ⑤ 停止 | ⑥・⑦ 備考 |
| --- | --- | --- | --- | --- | --- | --- |
| `@schovest/pi-goal` 0.2.1（2026-10-08・月 3.2 万） | `/goal <目標>`・`--tokens 100k`・`status`・`pause`・`resume`・`edit`・`clear`。素の `/goal` は TUI の管理画面。登録ツール `goal_complete`・`goal_blocked`・`goal_wait`（最初の目標までは**非アクティブ**） | **作業役の自己申告** ＋ 現在の goal_id 必須・矛盾する要約（「まだ未完」「テスト失敗」）の機械的拒否・全プロンプトに証拠つきの完了監査。`goal_blocked` は同じ障害が**3 ターン連続**＋証拠が要る | **pi の `agent_settled`（再試行・圧縮・steering・follow-up が落ち着き、`isIdle()` かつ保留メッセージ無し）でだけ 1 回**続行。意図は `agent_end` で記録し settle で配送 | **pi のセッション状態**（`/reload`・再開で復元。新しいセッションは引き継がない）。圧縮を跨いで保持 | **自動応答 25 回で pause**（既定、変更・無制限可）・**3 回連続の空/同一のツール無し出力で pause**・トークン予算（任意）・状態 6 種（active/paused/blocked/usage_limited/budget_limited/complete）。予算到達で収束の指示を 1 回だけ注入し以降の実質的なツールを遮断 | 古い goal_id の遅延した完了呼び出しを無効化（編集・再開で id を回す）。`pi.events` の信頼された他拡張向けプロトコル（既定オフ）。`schovest/pi-goal` README の注記: 「他拡張が idle チェック後に先に走る競合は避けられない」（`pidev-schovest-pi-goal.md:306`） |
| `pi-codex-goal` 0.7.7（2026-11-03） | `/goal`・`<目的>`・`pause`・`resume`・`copy`・`clear`、`/create-goal`（目的に**完了チェックを足して展開**）。Esc で止めて pause。モデル用ツール `create_goal`/`get_goal`/`update_goal` | 作業役の自己申告（Codex 方式） | 非表示のカスタムメッセージ。**waiting 状態**（バックグラウンドの結果が自分で届くものを待つ間は継続しない） | セッション（再開・fork・tree 移動・圧縮を跨ぐ） | **既定は予算なし**、モデルが `token_budget` を指定（最小既定 50 万）。プロバイダの利用上限は自動再試行を予約 | `-p` では turn が終わる前に抜けて pause のまま残ることがある（README） |
| `pi-goal-x`（月 2.7 万・`@fan92rus/` と `@xzzpig/` の派生あり） | `/goal [案]`（対話で目標・タスク計画・完了要件を**利用者が確認してから**開始）・`/goal-direct`・`/sisyphus`（順序つきの計画）・`/goal-pause`・`resume`・`tweak`・`focus`（複数目標）・`settings` | **独立の completion auditor（別のエージェント）**が目標・タスク・記録した証拠・ワークスペースを見て承認／未達の差し戻し。モデルと思考レベルを選べる。Ctrl+Shift+A で切替 | 自動継続。`maxAutonomousRuns`（拡張が始めた run の回数上限。未設定は無制限） | セッションを跨いで目標・タスク・進捗を保存（複数の開いた目標、1 セッション 1 フォーカス） | 自律 run 数・Esc で pause・ブロックは利用者の解決後に再開 | ダッシュボード（タスク木・証拠・経過時間・トークン）。`strictExecutionContract` は既定オフ |
| `@zhushanwen/pi-goal` 0.16.6（2026-11-03） | `/goal <目的> --tokens N`・`status`・`resume`・`pause`・`update`・`history`・`clear`。**`/goal` は提示語のトリガーで、実体は `goal_control` ツール（create/complete/report_blocked）** | 作業役が**成功基準ごとに具体的な証拠**を付けて complete。空の完了は拒否 | 作業役の `report_blocked` のみで阻害を宣言（**自動検知は無い**） | セッション entries（append-only。最新の goal-state から復元） | token の予算のみ（70% で警告、90% で収束の steering、100% かつ通知済みで `budget_limited`）。時間は記録のみ | 6 状態・純粋な状態機械（`engine/` は pi 非依存）・ポート／アダプタ分離 |
| `pi-better-goal`（月 2.7 万の一覧値） | `/goal` の pause/resume/complete/clear・`/goal settings`・Esc で pause・`alt+g` で再開。コーディネータ **skill に目標を束縛**（`/goal /skill:name`） | モデルが `update_goal complete`。**スケジューラ型のゲート**（skill が持つ `next-actions` が finish を返すまで完了を拒否） | アイドル・バックグラウンドの**ドレイン**で起こす。**進捗なしの再試行は同一 10 回・60〜600 秒の線形バックオフ**のあと「保留」で停止（`/goal resume` で解除） | 設定は pi の `settings.json` | 無進捗の失速状態・保留 | **圧縮のたびに skill を再注入**（`session_compact`。再注入しないと圧縮の要約から規則が落ちる） |
| `@hank-warren/pi-loop` 1.8 系（2026-10） | 目標の「ループ」（`/goal` ではないが同種）。**台帳（ledger）・適応的な待ち・無進捗の遮断・証拠ゲート付きの完了**・スケジューラ | 証拠ゲート付きの完了（台帳） | **`agent_end` で続行の意図を記録し、完全に settled した idle 境界で配送**。間隔は settle の補助の heartbeat | 台帳（耐久）。システム prompt に目標を byte 単位で同一に載せて **prompt cache を守る** | **`maxTurns` の既定は無制限**（1.0.0 で 25 から変更。理由: ターン予算は費用の代理で進捗の代理ではなく、作業の途中で理由なく止まる）。期限 7 日・無進捗の遮断。期限時は最後の 1 ターンで状態を台帳に書かせてから止める | 設計理由が詳しく書かれた珍しい README |
| `@tmustier/pi-ralph-wiggum`（月 3.4 千） | `/ralph` の start・resume・stop・status・`--max-iterations`（既定 50）・`--reflect-every N`。モデルが`ralph_start`・`ralph_done` | 自己申告（`<promise>COMPLETE</promise>`）。**最終検証を外から再実行できる形で記録**してから出すよう指示 | `ralph_done` が次のプロンプトをキューに入れる（**同じセッション内**の新しいターン。文脈は新しくならない） | `.ralph/<name>.md` と `.state.json`。複数ループ同時可。セッションが所有 | 反復 50 回・Esc | 古いプロンプトが完了後に届く場合の**stale prompt guard**（状態ファイルを読み直して無視） |
| `@pi-unipi/long-horizon` | goal/ralph/swarm/graph の 4 モード | **独立の verifier が受理するまで** | 自動 | 不明 | blocked・stalled・予算超過 | 進捗の推定を利用者にだけ表示（モデルには見せない） |

OpenCode 向け外部 plugin（`opencode-goal-plugin` 0.11.4〔保守のみ〕）の面白い点: **独立 verifier（`read`/`glob`/`grep` だけの子セッションが `[audit:approved]` を返す）**・
ターン／時間／トークン／**費用（USD）**の上限・`agentGoalAuthority: "status"`（エージェントが目標の中身を変えられないようにする）・状態の fail-closed な永続化・
94 件の変異試験（`opencode-goal-ricchiuti.md:17,279-289,415,439`）。

### 横断の比較

| 軸 | Claude Code | Codex | Hermes | OpenCode 内蔵 | Ralph（公式 plugin） | pi の拡張（多数派） |
| --- | --- | --- | --- | --- | --- | --- |
| 誰が完了を判定 | 別の小型モデル | 作業役（証拠の監査を要求） | 補助モデル＋決定的ゲート | 同じモデル（reviewer） | 作業役の合言葉 | 作業役の証拠つき自己申告。独立 auditor は少数 |
| 評価の入力 | 会話の記録全体 | 作業役の文脈 | 直近の最終応答の末尾約 4 KB（＋契約・ゲート結果） | 履歴全体 | 出力の文字列 | 作業役の文脈 |
| 続行の層 | Stop hook（セッション） | コアのランタイム（アイドルのイベント） | CLI/gateway の入力キュー | plugin の idle hook | Stop hook / 外側のシェルループ | `agent_settled`／カスタムメッセージ |
| 状態の保存先 | セッションの記録 | SQLite（スレッド単位） | セッション DB の meta | セッション metadata | 状態ファイル | pi のセッション状態・`.ralph/` など |
| 圧縮・再開 | 条件を復元（指標は 0 に戻る） | 再開で paused を active に。圧縮の途中で継続プロンプトが失われる不具合 | 圧縮・再開を跨ぐ | 目標の注意書きを注入。boot ID で前プロセスを pause | プラグインは同一セッション | 保持（拡張による）。skill の再注入 |
| 予算 | なし（目標文に書く） | トークン（任意・既定なし） | ターン 20（既定） | 隠れ 50 ラウンド | `--max-iterations`（既定無制限） | 応答数 25・トークン・無進捗など（実装ごと） |
| 無進捗の検知 | ツール未使用が数ターン | ツール 0 の継続は次を抑止・3 回失敗 blocked | なし（ターン予算のみ） | 3 ラウンド | なし | 同一出力 3 回・同一 10 回など |
| 利用者の割り込み | 次の入力で即・Ctrl+C | 割り込みで pause | 実メッセージが優先 | 即時コマンド | `/cancel-ralph` | Esc で pause が多い |
| 承認待ち・判断待ち | auto モードと併用が前提 | blocked（利用者の入力が要るとき） | blocked／gate で pause | blocked | なし（向かないと README） | blocked／waiting 状態 |

### 共通の設計パターンと分かれ目

1. **評価を誰がするか**（最大の分かれ目）。
   - *別の小型モデル*（Claude Code・Hermes）: 作業役が「できた」と思い込む早期完了宣言を、独立の目で減らせる。代償は、**評価役は記録しか見えず**（Claude Code は明記）、
     検証の実行はできない。Claude Code の issue #93744 は、評価役が `/goal` の引数を見られず、目標を満たせないまま「不可能」と宣言した例。
   - *作業役の自己申告＋監査プロンプト*（Codex・pi の多数）: 追加の呼び出しが無く安いが、評価が作業役と同じ偏りを持つ。補う手段は、現在の goal_id の要求・矛盾した要約の拒否・
     証拠の必須化・`blocked` を 3 ターン連続の証拠つきに絞る（`@schovest/pi-goal`）など。
   - *決定的な検査・独立の検証役*（Hermes の gate・pi-goal-x・OpenCode plugin・unipi）: 最も強いが、検査コマンドの用意や追加の費用が要る。
     Hermes は「ゲートがジャッジより先」という順序を採った。
   - 研究は、LLM 判定は明白な不正の検出に有効で、保持した（隠した）テストとの併用がよいとする（EvilGenie）。生成者が採点者を兼ねる構造が reward hacking の根という記述もある（二次）。
2. **続行をどの層で起こすか**。Stop hook（Claude Code・Ralph plugin）／コアの idle イベント（Codex・OpenCode）／入力キュー（Hermes）／`agent_settled`（pi）。
   共通の落とし穴は **「アイドルになった瞬間に空の継続を連打する」**（Codex #44909）。対策は、継続ターンのツール呼び出しが 0 なら次を抑止（Codex）・無進捗の遮断・バックオフ（pi-better-goal）。
3. **状態をどこに持つか**。セッションの記録／DB（Codex の SQLite・Hermes の `state_meta`）／ファイル（Ralph）／pi のセッション状態。**置換のたびに id を回す**
   （Codex の goal_id・pi-goal の guard id）ことで、遅れて届く古い呼び出しが新しい目標を壊すのを防ぐ。
4. **続行の起点を 1 つにする**。pi の拡張は「`agent_end` で意図を記録し settled で 1 回だけ配送」（pi-goal・pi-loop）で、保留メッセージ・再試行・圧縮の最中の二重配送を避ける。
5. **利用者の優先**。Hermes（実メッセージが先）・OpenCode（pause/clear が mid-review でも勝つ）・Codex（割り込みで pause）。一方 Claude Code は評価役が利用者の stop を無視できた（#101528）。
6. **エージェントの権限の非対称**。Codex は「作成と完了だけがモデルに見え、pause/resume/予算の遷移は system」。OpenCode plugin は `agentGoalAuthority` で目標の中身の変更を禁止できる。
   Claude Code の「モデルが止める手段が無い」は逆方向の欠陥として報告された。
7. **予算の種類**。ターン（Hermes・pi）／トークン（Codex・pi）／時間（記録のみが多い）／費用 USD（OpenCode plugin・Copilot のクレジット上限）。
   pi-loop は「ターン予算は費用の代理で進捗の代理ではない」と、既定を無制限へ戻した（無進捗の遮断と期限で守る）。
8. **完了条件の書き方**が docs の中心の助言: 測れる 1 つの終了状態・証明の方法・守る制約・範囲・止める条件（Claude Code・Codex cookbook・Hermes の「完了契約」）。
   Hermes と pi-codex-goal は、**目標から契約を下書きさせる**（`/goal draft`・`/create-goal`）。

### 失敗談と対策

| 失敗 | 出典（要旨） | 対策として各実装が採ったもの |
| --- | --- | --- |
| 利用者が何度 stop と言っても目標が再投入され 3 日続いた（Stop hook が 74 回発火、73 回ブロック。評価役が停止の発言を引用しつつ「未達」と判定。9 連続ブロックの上限は次の入力で再開） | Claude Code issue #101528（open） | pause を強い状態にして上限到達後も再開しない／**評価役の入力に利用者の停止を優先**（OpenCode は reviewer に `paused` 値を持つ）／モデルが止める手段（ただし権限の非対称に注意） |
| 評価役が `/goal` の引数を見られず、目標を満たせないまま 9 回止まり、「不可能」と宣言 | Claude Code #93744（open）。目標が transcript の `<command-args>` にしか無い | 継続メッセージで毎回目標を**再掲**（OpenCode・Codex）／目標を評価の入力に明示的に含める |
| 目標が未登録のスキルを参照すると評価が永遠に未達 | Claude Code #58348 | 評価役が確認できない条件を弾く／ブロック上限 |
| 目標のあるセッション（全体の 1.4%）が入力トークンの 49% を消費。0.03 秒で空の継続が再起動し、1 時間の待ちで 83〜188M トークン。最悪は 48 分で 173 継続・1.49 億トークン | Codex #44909（著者の実測。3,808 セッション。再現用スクリプトあり）。ブログ <https://relux.works/en/blog/codex-goal-token-burn/> | 継続前の**バックオフ**・N 回連続の無ツール継続で blocked・待ちをターン消費なしで行うツール（`clock.sleep`）・待ちの正規の形を継続プロンプトに書く（著者の要望）。pi では `goal_wait`・waiting 状態 |
| 「人間の勤務時間を超えたら pause」と明示したのに無視、12 の no-op ターンで 126 万トークン | Codex #41831 | 条件の形式化（Hermes の契約の `stop_when`）・無進捗の遮断 |
| 圧縮の失敗の連続で 5 時間分の枠を 45 分で消費 | Codex #23003 | 同じエラーの連続で停止（Claude Code は「圧縮で戻せない文脈あふれ」で目標を消す）・OpenCode は圧縮して再質問、同ラウンドで 2 回目なら pause |
| 圧縮の途中で継続プロンプトと監査要件が失われる | Codex #19910 | 圧縮後の再注入（OpenCode・pi-better-goal の skill 再注入・pi-loop の再アンカー） |
| 利用者が頼んでいない予算をモデルが自分で設定／予算超過後に上げられない | Codex #24629・#34215 | 予算の遷移を system/利用者の権限にする |
| `--max-iterations=5` が黙って無視され 462 反復 | Claude Code #18646（ralph-wiggum） | **上限の既定を有限にする**／引数の厳格な検証。上限なし既定の Ralph プラグイン自体が批判された（HumanLayer） |
| 空回り（同じコマンドの繰り返し・独白・往復）で永遠に続く | OpenHands の StuckDetector | パターンの検知（4 回同一・3 回同エラー・6 周の往復）で停止。ただし文脈あふれのループは検知できなかった（#6104） |
| 完了後も目標が続く・利用者に戻っても評価が走り続ける | Claude Code #85594・#104957（open の報告。再現条件は未確認） | 完了の記録を状態に残し、評価を完了後に呼ばない |
| 走らせすぎて奇妙な創発的挙動（overbaking）。文脈のロット | Ralph 原典・HumanLayer | 毎周新しい文脈（外側ループ）・小さな 1 仕事・長いときは定期の fresh start（Cursor の長時間実験も同様） |
| 完了の誤判定（偽陽性）は利用者が気付くしかない | Hermes docs | 保守的なジャッジ・決定的ゲート・独立 auditor |
| 隠した 50 ラウンドの上限など、**UI に出ない上限**は利用者が理由を探せない | OpenCode PR の設計（上限は非表示と明記）／Claude Code #101528（「どこにも hook が無い」と設定ファイルを探した） | 状態表示に「上限・残り・理由」を出す（pi-goal の automatic 12/25 表示・Claude Code の評価理由） |

### 設計の知見（一次・二次の区別つき）

- **一次**: Claude Code・Codex・Hermes・OpenCode の docs／PR（上の表）、EvilGenie（arXiv 2511.21654。LLM 判定は明白な不正の検出に有効、保持テストと併用がよい。方式ごとに長短あり）、
  OpenHands の docs、Cursor の長時間エージェントの実験（`cursor-scaling-agents.md:58,98,214`: **各周の終わりに judge が続行を決め、次の周は新しい文脈で始める**・「時折の fresh start が drift とトンネル視を防ぐ」・「プロンプトが harness やモデルより効く」）。
- **二次・伝聞**: Codex の 5 PR の解説 gist（実装の層の把握に有用だが一次ではない）、個人ブログ・Reddit（9 時間の自走の体験談。本文は取得できず未確認）、reward hacking の解説記事（Springer の概説・Medium など。検索結果の抜粋のみで本文未取得）。
- **完了判定の長短**（上記の分かれ目の整理）。LLM の評価役は柔軟で何でも判定できるが、見えるのは記録だけで偽陽性を残す。テスト・検証コマンドは決定的で強いが、書ける目標にしか使えず、
  テスト自体の改変（reward hacking）への備えが要る（EvilGenie はテストファイル編集の検知を併用）。自己申告ツールは安いが、同じ偏りを共有する。
- **長時間の自走と圧縮**: 目標を文脈にだけ置くと圧縮で落ちる。各実装は、状態を外（DB・meta・ファイル）に持ち、続行ごとに目標を再掲する／圧縮後に再注入する。
  Hermes は continuation を user ロールで追記して prompt cache を壊さない設計、pi-loop は目標を system prompt に byte 単位で固定する。
- **利用者の承認待ち・判断待ち**: `blocked`（Hermes・Codex・pi）／`waiting`（pi の拡張・OpenCode・Hermes の `wait`）／Kimi は終了コード 3（blocked）・6（paused）で非対話に通知。
  manual 権限では承認で止まる（Claude Code・Kimi）。Copilot は「継続」「承認」「質問抑止」を独立の軸にした。Antigravity は人の確認点を完了後へ移した（二次）。

### pi への取り入れ候補と見送り候補（設計の決定ではない）

#### 取り入れ候補

| 候補 | 理由 |
| --- | --- |
| 目標は**セッション単位**で保存し、置換のたびに id を回して古い呼び出しを無効化（Codex・pi-goal） | 遅れて届く継続・完了呼び出しが新しい目標を壊す競合を避けられる。コストが小さい |
| 続行は **`agent_settled` で、意図を記録して 1 回だけ**配送（pi-goal・pi-loop） | 本リポジトリの実験（`agent_settled` からの `triggerTurn` が連鎖する）と整合。二重配送を防ぐ |
| **無進捗の遮断**（ツール呼び出しなしの継続・同一出力の繰り返し）と、有限な既定の上限（応答数・時間） | Codex #44909・Ralph #18646 の暴走を直接防ぐ。上限は必ず**状態に表示**する |
| 完了判定は**証拠の必須化＋独立の評価（任意）**。まず自己申告ツール＋矛盾要約の拒否、次に別系統のモデル（既存の `review` 役）を評価役に | 作業役の早期完了宣言を減らす。評価役の入力に記録だけでなく**目標の原文と利用者の停止**を必ず含める（#93744・#101528 の再発防止） |
| 決定的な**検査コマンド（gate）を判定より先に**（Hermes） | 最も強い完了判定。既存の `mise run verify` 系と相性がよい |
| 利用者の入力・停止を最優先（Hermes・OpenCode）。**Esc で pause**（pi の拡張で多数） | #101528 の失敗を避ける |
| **モデルに pause/resume/予算変更を持たせない**（Codex の非対称）。完了とブロックの申告だけ | 目標の乗っ取り・無断の予算設定（#24629）を避ける。フルガードの方針と整合 |
| `blocked`（3 ターン連続・証拠つき）と `waiting` の**2 つの停止状態**、承認待ち・判断待ちは blocked として利用者へ通知 | 判断待ちで空回りしない（Codex #44909 の待ちの空回り） |
| 目標文に「何が完了か・どう証明か・守る制約・範囲・止める条件」を書かせる型と、**下書きの生成**（Hermes の draft・pi-codex-goal の `/create-goal`） | 評価の質は目標の質で決まる（各社の docs の共通の助言） |
| 圧縮後の目標の**再掲**（毎継続で再掲＋圧縮後に再注入） | Codex #19910 の失敗を避ける |
| 自動のターンに**ガードの確認が絡む**扱い（確認が必要なツールで止まるのは仕様として表示） | Claude Code・Kimi の manual 権限の挙動と同じ。pi のフルガードの `ask` との関係を設計で決める必要がある |

#### 見送り候補

| 候補 | 理由 |
| --- | --- |
| 評価役に小型モデルを**常用**し、判定を完全に任せる（Claude Code 方式） | 記録しか見えず、停止の無視・目標の見落としの失敗が出ている。補助の位置づけなら可 |
| 予算なしの既定（Codex のトークン無制限・Ralph の `--max-iterations` 既定なし） | 暴走の報告が最も多い。ただし pi-loop は「ターン予算が進捗を測らない」ため無制限＋無進捗遮断を選んだので、**有限な既定にするかは決定が要る** |
| Ralph の**毎周新しい文脈**（外側ループ） | pi のセッションを使い捨てて続けることになり、フルガード・セッション状態と合わない。HumanLayer の指摘する要点（小さな仕事を独立した文脈へ）は目標の分解で取り入れる |
| 複数目標・順序つきの目標（pi-goal-x・Kimi の `next`・OpenCode plugin） | 機能が大きい。最初の版は 1 セッション 1 目標（schovest も queue を後で削除した） |
| 目標を提示語のトリガーにし、実体をモデルのツール呼び出しにする方式（`@zhushanwen/pi-goal`） | 目標の作成をモデルに委ねる。Codex の「利用者が明示したときだけ作成」と逆で、無断の目標設定を招く |
| 評価役が目標の中身を変えられる構成 | `agentGoalAuthority` のような禁止を要する。最初から持たせない |
| 外部 SaaS に接続するもの（`pi-until-loop`）や、実行者・検証者を複数のサブエージェントで動かす大きな枠組み | 目標つき自走の本題から外れる／このリポジトリの方針（外部送信を避ける）と合わない |

### 未確認・限界

- **どの実装も動かしていない**。評価役のプロンプト全文（Claude Code は非公開・Codex は `continuation.md` の行リンクのみ・Hermes の judge prompt）は読んでいない。
- Codex の実装の層は**二次の解説（gist）**。一次のソース（`codex-rs/ext/goal/`）は issue 内の行リンクで言及を確認しただけ。
- Antigravity の `/goal` は個人サイトの解説のみ（公式未確認）。Copilot の `/goal` が `/autopilot` の別名というのは検索結果の抜粋のみ（docs 本文では未確認）。
- Cursor の `/goal` の機構は docs に記述が無い。Kimi の guide は取得できず（404）、完了判定・予算の記述は未確認。
- pi 向けの約 40 件のうち README を読んだのは 8 件。**拡張のソースは読んでいない**。月間ダウンロードは一覧の値で、品質の指標ではない。
- Claude Code の issue #85594・#67665・#68911・#104957 は検索結果の抜粋だけ（本文未取得）。再現条件・修正状況は未確認。
- npm.com は 403 で取得できず、pi.dev の記載（README の写し）を使った。更新が速いため版・数値は 2026-11-05 時点。
- Reddit の「9 時間の自走」の体験談（取得失敗）・reward hacking の概説記事（Springer・Medium）は本文未取得で、結論の根拠にしていない。
- Cline・Aider・Amp・Continue・SWE-agent の `/goal` 類は、検索で見つからなかった（存在しないとは断定しない）。Gemini CLI は公式にはなく、コミュニティの autoresearch skill が見つかった。
- 検索語: 「Claude Code /goal」「Codex CLI /goal」「Hermes Agent /goal judge」「Ralph Wiggum loop」「ralph-wiggum plugin stop hook」「pi coding agent goal loop ralph」
  「OpenCode /goal plugin」「Copilot CLI autopilot」「Kimi /goal」「OpenHands StuckDetector」「Goose recipe retry」「reward hacking LLM judge」ほか。

### 次の問い

- pi の `agent_settled`・`triggerTurn` と、フルガードの `ask`（確認）が自動ターンの中でどう絡むか（確認待ちの扱い）。
- 評価役を `review`（別系統のモデル）にした場合の費用と、記録のどこまでを渡すか（実測が要る）。
- 有限な既定の上限（応答数・時間）を何にするか。Hermes の 20 ターン・pi-goal の 25 応答・OpenCode の隠れ 50 は参考値で、このリポジトリの実測は無い。

### 参照（出典と取得日はすべて 2026-11-05）

一次（公式 docs・PR・README・issue）:

- Claude Code docs `/goal`: <https://code.claude.com/docs/en/goal>
- Claude Code changelog: <https://code.claude.com/docs/en/changelog>
- Claude Code issues: <https://github.com/anthropics/claude-code/issues/101528> 、/93744 、/58348 、/18646
- Ralph ループのプラグイン: <https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop>
- Codex cookbook: <https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex>
- Codex use case: <https://developers.openai.com/codex/use-cases/follow-goals/>
- Codex issues: <https://github.com/openai/codex/issues/44909> 、/41831 、/23003 、/19910 、/24629 、/34215 、/36590 、/56927
- Hermes docs: <https://hermes-agent.nousresearch.com/docs/user-guide/features/goals>
- Hermes PR: <https://github.com/NousResearch/hermes-agent/pull/18262>
- OpenCode PR（内蔵 `/goal`）: <https://github.com/anomalyco/opencode/pull/59437>
- OpenCode 外部 plugin: <https://github.com/william-ricchiuti/OpenCode-goal-plugin> 、<https://github.com/prevalentWare/opencode-goal-plugin>
- Cursor docs: <https://cursor.com/docs/agent/overview> 、ブログ <https://cursor.com/blog/scaling-agents>
- Kimi Code: <https://moonshotai.github.io/kimi-code/en/reference/slash-commands.html>
- Copilot CLI autopilot: <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot>
- OpenHands: <https://docs.openhands.dev/sdk/guides/agent-stuck-detector>
- Goose: <https://goose-docs.ai/docs/guides/recipes/recipe-reference/>
- pi の拡張（pi.dev）: <https://pi.dev/packages/@schovest/pi-goal> 、/pi-codex-goal 、/pi-goal-x 、/@zhushanwen/pi-goal 、/pi-better-goal 、
  /@hank-warren/pi-loop 、/@tmustier/pi-ralph-wiggum 、/@pi-unipi/long-horizon 、/@derogab/pi-goal 、/pi-goal
- Ralph の原典: <https://ghuntley.com/ralph/> 、<https://ghuntley.com/loop/>
- EvilGenie（reward hacking の benchmark）: <https://arxiv.org/html/2511.21654v2>

二次・伝聞:

- Codex `/goal` の 5 PR の解説: <https://gist.github.com/patleeman/b1b5768393f9bf2f60865b1defeeb819>
- Codex の目標のトークン消費の測定ブログ: <https://relux.works/en/blog/codex-goal-token-burn/>
- HumanLayer「A Brief History of Ralph」: <https://www.humanlayer.dev/blog/brief-history-of-ralph>
- Antigravity の解説: <https://neurals.ca/tech/gemini/antigravity/goal-mode/>
- pi 拡張の一覧: <https://awesome-pi.site/extensions/>

このリポジトリの関連記録: [pi のメッセージ・キューの挙動の実験（CHG-0061 S0）](pi-message-queue-experiments.md)（`agent_settled` からの `triggerTurn` が連鎖する）・
[圧縮の失敗の調査](pi-compaction-failure-survey.md)・[pi の公開拡張の調査](pi-public-extensions-survey.md)。
