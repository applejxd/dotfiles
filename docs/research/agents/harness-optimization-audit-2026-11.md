# pi ハーネスの最適化の監査（2026-11）

観測日: 2026-11-18（使われ方の測定の窓は 2026-11-10〜11-17 の 8 日間）。対象: pi 1.5.x のハーネス周り（システムプロンプト・スキル・権限の層）。
問い: 何を廃止・統合・更新・分割・追加すると、保守と選択の正確さが良くなるか。親が測定した事実と、子エージェントの調査（「子の調査」。親が原典で再確認したものは「再確認」と書く）を合わせて記録する。

## 結論

- 測定からは、**目的は費用でなく、保守と正確さ**だと分かった。毎要求の先頭に載る固定部分（約 3 万トークン）は、毎ターンの入力の約 9.5% で、2 割減らしても入力全体で約 2%。効くのは、選択の精度・注意・保守。
- **決定**（2026-11-18、利用者）: 参照切れ・食い違い・権限の穴の修正、よく読まれるスキルの分割、`agent-config-generation.md` の経緯・実測の分離、手動起動 9 本・Orca の 3 本の除外・`learn` + `onboarding` の統合を実施する。診断用の先回り allow・`/sandbox` の YOLO 連動・plan-mode・goal・rewind・permission-explain のフォークの廃止と、package のパッチ更新は見送る。ADR-0031 の自作 4 件は維持する。
- **次の見直しの条件**: 自作がさらに増えたとき・上流が同等の機能を出したとき（[ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md)）。`/sandbox` の YOLO 連動は、複数の pi を同時に使う運用で YOLO の共有が問題になったとき。

## 依頼と進め方

- 依頼（利用者、2026-11-18）: pi のハーネス周り（システムプロンプト・スキル・権限の層など）の最適化。ステップバックして、廃止・統合・更新・分割・追加など複数の線を検討する。
- 進め方: 親が測定し、外部根拠（researcher 2）・スキル監査（scout 2）・権限の設計監査（reviewer 1）を並列に委譲した。結果を親が再確認し、5 つの線で比べて、
  利用者に選んでもらった（下の「決定」）。測定スクリプトは使い捨て（`.tmp/harness-audit/`。コミットしない）。測定の再現の考え方は下の「測定の方法」。

## 測定した事実

### 毎要求の先頭に載る固定部分（2026-11-18 の親セッション。pi は system メッセージに節とツール宣言を保存する）

- 最初の要求の入力は約 30,000 トークン（`cacheWrite` 30,013）。文字では約 62,300 字（平均 約 2.1 字/トークン）。
- 内訳（文字数。全体 62,349 字に対する割合）: ツール宣言 28 本 26,816（43.0%）・スキル一覧 15,754（25.3%）・指示ファイル（`project_context`）6,946（11.1%）・
  `rules`（pi 本体と package の `promptGuidelines`）6,463（10.4%）・ホスト（T3 Code）由来の節 4,007（6.4%）・pi 本体の docs 節 1,329（2.1%）・その他 1,034（1.7%）。
- 指示ファイル 6,946 字の中身: グローバル `agent-instructions-stock.md` 3,886・家の機だけの節 1,243・このリポジトリの `AGENTS.md` 1,541。
- スキル一覧は 31 本（自作 26・pi-subagents 同梱 2・Orca アプリが入れた 3）。1 本あたりの一覧への出現は約 280〜1,130 字。Orca の 3 本（`orca-cli` 1,132・`orchestration` 1,012・`computer-use` 738）で 2,882 字（一覧の 18%）。
  自作 26 本の description は合計 7,420 字。`disable-model-invocation` を使うスキルは 0 本だった。
- 固定部分が、毎ターンの入力に占める割合: 親らしいセッション（最初の要求が 2 万トークン超）18 本・3,249 ターンで、1 ターンの入力は平均 約 31.6 万トークン。固定部分 約 3 万はその約 9.5%。
  固定部分を 2 割減らしても、入力全体で約 2%。**費用の面では、固定部分の縮小はほとんど効かない**（効くのは、選択の精度・注意・保守）。
  pi が計算する名目の費用は 8 日で約 $325（出力 $55・キャッシュ読み $134・キャッシュ書き $135）。GitHub Copilot 経由で実費は別の可能性（推測）。

### 使われ方（2026-11-10〜11-17 の 8 日間。全セッション 143 本。子の実行を含む）

- スキルの読み込み回数（`read` と `bash` での `SKILL.md` の読み込み。多い順）: dotfiles-conventions 約 69・feature-orchestration 約 51・commit 約 29・friction-review 約 20・away-shift 約 16・session-recall 約 16・
  pi-extension-dev 約 14・experiment-loop 約 11・review-loop 約 10・env-check 約 9・sdd-docs 約 7・pi-subagents 約 7・skill-creator 約 6・github-operations 約 6・imozuru 約 5・learn 約 3・onboarding 約 3・
  ipynb-to-marimo-pages 約 2・uv-migration 1・powerpoint-studio 1・council-mode 1。0 回: arxiv-paper-ja・conference-video・cuda-version-migration・fix・oss-research・readme-writer（新規）・chezmoi-usage・
  computer-use・orca-cli・orchestration。窓は短く、このリポジトリ中心。0 回は不要の証拠ではない。
- ツール呼び出し: bash 3,352・read 1,671・grep 774・fetch_page 216・ls 207・bg_run 158・todo 157・find 149・subagent 139・write 114・web_search 93・contact_supervisor 80・edit 52・
  subagent_supervisor 33・bg_status 32・ask_user_question 15・bg_kill 13・search_papers 8・watchdog_diff 7・bg_wait 2・goal_wait 2。
  **plan_mode_question・plan_mode_complete・goal_complete・goal_blocked は 0 回**。plan mode の状態記録（`plan-mode-state`）162 件（18 セッション）は、すべて `enabled: false`。`/goal` は 1 セッションだけ
  （`goal-state` 15 件）。固定部分に載る宣言は、plan_mode 2 本 1,957 字・goal 3 本 2,887 字（計 4,844 字）。
- 子エージェントの起動: reviewer 69・worker 21・scout 15・researcher 4（oracle・evidence-auditor は 0）。
- `pi-checkpoint`（pi-rewind の記録）は 20 セッションで 677 件。`/rewind` を実際に使ったかは、ログから分からない。
- 権限の確認（審査ログ 2026-11-09〜11-17）: 人に見せた確認（`permission_request.waiting`）は 193 件（約 21 件/日）。親の確認は external_directory_read 79・bash 69・external_directory 26。
  直近 5 日（11-13〜）の 118 件のうち 37 件（約 3 割）は、利用者が指示した統合・反映（`git flow finish` 18・`git flow integrate` 8・`chezmoi apply` 11）。
  規則による自動拒否（blocked）112 件のうち、作業ツリーの外（external_directory 系）は約 72 件。呼び出し元は子の reviewer 38・researcher 11・worker 7・scout 6・試験用 5・親 5
  （子の定義が `external_directory: deny` のため、pi 本体の許可済みの場所以外は読めない）。
  YOLO の自動承認は 301 件で、275 件は 11-09（方針を「bash は allow が既定」に変える前）、11-11〜13 が 26 件、**11-14 以降は 0 件**。`/sandbox`・`pib` が日常で使われているかは、囲いの内側が審査ログに出ないため、これでは分からない。
- 変更の集中（直近 6 日、2026-11-12〜、マージを除く 62 コミット）: `docs/spec/agent-config-generation.md` 24・`test/agents/pi_stock/permission_cases.json` 18・
  `home/.chezmoitemplates/pi-permission-policy.json` 16・`test/test_pi_stock_config.py` 13・`agent-instructions-stock.md` 11・`dotfiles-conventions/SKILL.md` 8。権限の方針・判定表・仕様書の 3 点セットが変更の中心。

### 構成の規模

- 権限の方針 `pi-permission-policy.json`: 449 行・49 KB・規則 約 401 件（bash 167・external_directory_read 115・path_write 65・path 44 ほか）。判定表 約 650 例・54 KB。
  `external_directory_read` の allow 106 件のうち、システム診断（`/proc`・`/sys`・`/etc`・`/var/log` など）の先回り許可が 約 73 件（方針自身が「知識に基づく草案で、この機械に実在するかは確認していない」と書く）。
- 仕様書 `agent-config-generation.md`: 56,888 字（342 行）。`### permission-system の設定` の節だけで 27,817 字。1 行が 3,595 字の箇条書きがある。
- 自作の部品（ADR-0031 の例外）: 検索 MCP 1,655 行（core 1,366 + MCP 289）・`pib` 一式 1,043 行（runner 668 + `pib` 351 + `pib-shell` 24）・`/sandbox` 545 行・
  `pi-permission-explain` のフォーク 443 行（上流 0.1.1 の改変。**ADR-0031 の一覧に載っていなかった**）。試験 約 4.2K 行（pib 2,603・toggle 711・websearch 914）。
  ADR-0031 の見直し条件「例外の自作が 3 件を超えたとき」に当たる（4 件）。
- 子エージェントの定義の写し 6 本: `agentOverrides` が `permission` を受けない（pi-subagents 0.87.0 の docs の「Supported override fields」。permission-system は agent の frontmatter でしか agent 別の方針を読まない）ので、写しは必要。

## 外部の根拠（子の調査 R1。親が再確認したものは「再確認」）

- Gloaguen ら "Evaluating AGENTS.md" arXiv 2602.11988（v1 2026-02-12、v3 2026-09-29）。要旨（再確認）: 「context files does not generally improve task success rates, while increasing inference cost by over 20% on average」
  「instructions in the context files are well followed … repository overviews … are not helpful」「useful for specifying non-standard coding practices」。
- Claude Code 公式 memory（<https://code.claude.com/docs/en/memory>）: CLAUDE.md は 200 行を目安に、部分的にしか要らない指示は path 別の規則へ、複数手順の手順書は skill へ（子の調査。未再確認）。
- Agent Skills 仕様（<https://agentskills.io/specification>）: description は 1〜1,024 字、SKILL.md は 500 行未満・約 5,000 トークン未満が推奨、詳細は references へ（子の調査。未再確認）。
  手動で呼ぶ手順は `disable-model-invocation`（Claude Code の skills docs。子の調査）。
- Anthropic "advanced tool use"（2025-11-24。再確認）: ツール 58 本で約 55K トークン。Tool Search で 約 72K → 約 8.7K（85% 減）、MCP 評価の精度は Opus 4 が 49% → 74%・Opus 4.5 が 79.5% → 88.1%。
  使う目安は「定義が 1 万トークン超・10 本超」で、「小さなライブラリ・全部を毎回使う」ときは効果が小さい。pi の 28 本・約 1 万トークンは閾値付近。
- Anthropic "Making Claude Code safer with sandboxing"（2025-10-20。再確認）: 「sandboxing safely reduces permission prompts by 84%」。承認の連打は「approval fatigue」。
  効く囲いは、ファイルシステムとネットワークの**両方**の隔離が要る（ネットワークが開いたままだと、読んだ秘密を送り出せる）。pi の `pib` は通信を既定で開けている（ADR-0036）。
- Anthropic の auto mode の記事（2026-03-25）: 確認の 93% が承認される。広いシェルの許可規則を外す（子の調査。未再確認）。
- pi 公式 `docs/security.md`（pi 1.5.0）: 承認の画面・transcript の監視・project trust・差分の確認は安全の境界ではなく、境界は OS・コンテナ・VM・sandbox で作る。

## 上流の最新（子の調査 R2。2026-11-17〜18。npm の 3 版は親が再確認）

- 更新できる版: pi 本体 1.5.2（1.5.1=11-09、1.5.2=11-10）・`@gotgenes/pi-permission-system` 42.0.2（11-16。子の転送 bash を親で綴り違いも含め照合 #1019）・`cc-safety-net` 2.7.15（11-17）・
  `pi-subagents` 0.89.0（11-16。Herdr・Rex・worktree 中心）・`pi-background` 0.4.4・`pi-plan-mode` 0.60.2・`pi-goal` 0.55.3・`pi-btw` 0.63.8。いずれもパッチ〜マイナーで、公開された脆弱性情報は見つからなかった。
- 更新で不要になる自作・写し・一時対処は見つからなかった。`cd ~/…` の誤判定（#1083）と修正 PR #1084 は未マージ（一時対処は残す）。`pi-permission-explain` は上流が 0.1.1 のままで、週間 DL 10・Issue 0・3 つの改変の取り込みなし。
  `@ayulab/pi-rewind` は上流が 2026-07-28 にアーカイブ済み（代替は未確認）。

## スキル・権限の監査の要点

- 更新: `pi-extension-dev` が、2026-11-13 の撤去 commit（91d93a44）で消えた `pi-upstream.md`・`pi-extensions.md`・`test/agents/pi/faux.ts` を「正本」と呼び続けていた。`sdd-docs` に、撤去済みの `checkpoint` スキル・OpenCode への言及。
  グローバルの指示（`agent-instructions-stock.md`）が、`watchdog_diff` を ask と書いていた（方針は deny）。仕様書に方針との食い違いが 3 件（`subagent_launch` の ask/allow・`path` の deny の件数・YOLO の ON/OFF が逆の記述）。
- 権限の穴 2 件: `git flow feature publish`（feature 枝のリモートへの push）が allow と固定されていた（`git push` は deny）／`gh --hostname h api … --method POST` のように前置きオプションが付くと、`gh api` の書き込みの ask に当たらない。
- 設計: `path`／`path_write` の deny と `pib` の `hide` の重複は、別の実行経路（ファイルツールは囲いの外・bash は囲いの中）を守るので必要（reviewer も維持を推奨）。
  診断用の先回り allow 約 73 件・`/sandbox` の YOLO 連動（YOLO は共有の設定ファイルなので、囲いなしの pi や子にも次のターンから効く。ADR-0040 が限界として明記）は、簡素化の候補だった。
  害 × 層の表で、止める層が 0 の害（穴）は、未列挙の秘密・環境変数の取得と送信、PR・issue の投稿や publish などの外部送信（通信が開いている）、永続化、費用の暴走（子の大量起動）。受容している。
- 誤報の訂正（子の報告を親が検証）: S2 の「AGENTS.md に Orca の記述は無い」は誤り（`agent-instructions-stock.md` にある）。S1 の「`commit` スキルが AGENTS.md と逆」は過大（スキル自身が「リポジトリの規約を優先」と明記している）。

## 比べた線と、利用者の決定（2026-11-18）

| 線 | 候補 | 決定 |
| --- | --- | --- |
| 更新 | 参照切れ・食い違いの修正、ADR-0031 の一覧の追記 | 実施 |
| 更新 | 権限の穴 2 件（publish の deny・`gh *api` の前置き） | 実施 |
| 更新 | package のパッチ更新 | **見送り**（利用者が選ばなかった。上の「更新できる版」は残る） |
| 分割 | よく読まれるスキルを核 + references へ（dotfiles-conventions・feature-orchestration・commit・sdd-docs）、`agent-config-generation.md` の経緯・実測を research へ、Tailscale の詳細をスキルへ | 実施 |
| 分割 | 専門 7 本（conference-video・powerpoint-studio・ipynb-to-marimo-pages・arxiv-paper-ja・cuda-version-migration・uv-migration・readme-writer）と fix・learn・onboarding を手動起動に | 実施 |
| 分割 | Orca の 3 本（computer-use・orca-cli・orchestration）を設定 `skills` の `!名前` で除外 | 実施 |
| 統合 | `learn` + `onboarding` → `agents-md` | 実施 |
| 廃止 | 診断用の先回り allow 約 73 件 | **見送り** |
| 廃止 | `/sandbox` の YOLO 連動 | **見送り**（ADR-0040 のとおり。見直しの条件: 複数の pi を同時に使う運用で YOLO の共有が問題になったとき。11-14 以降の YOLO 自動承認 0 件は、判断材料として残す） |
| 廃止 | pi-plan-mode・pi-goal・pi-rewind・permission-explain のフォーク | **見送り**（利用者が維持を選んだ） |
| 追加 | スキルの description 長の検査・測定の常設 | 作らない（ADR-0031 の既定） |
| 維持 | 子の定義の写し 6 本・`path` と `pib` の二重・圧縮 70 万・モデルの割り当て | 変えない |

**[ADR-0031](../../adr/0031-evaluate-existing-extensions-first.md) の再評価**（自作が 4 件になった）: 4 件（検索 MCP・`pib`・`/sandbox`・permission-explain のフォーク）はいずれも、利用者の判断で維持する（2026-11-18）。置き換え候補は見つからなかった
（permission-explain は上流が 0.1.1 のままで、改変の取り込みなし）。一覧の見積もりを実測に更新し、permission-explain を一覧に足した。次の見直しの条件: 自作がさらに増えたとき・上流が同等の機能を出したとき。

## 実施した変更の要点（feature 枝 `feature/harness-tune`）

- スキル一覧: 手動起動 9 本（`disable-model-invocation: true`。`conference-video` と `readme-writer` は skill-lab からの複製で、frontmatter の 1 行だけをこのリポジトリで足した。skill-lab 側にも同じ変更を入れて取り込み直すまで、
  `scripts/sync_skill_lab.py` の置き換えで消える）、Orca の 3 本を設定で除外、`learn`+`onboarding` → `agents-md`（手動起動）、`tailscale-serve` を新設（家の機だけ）。
- よく読まれるスキルの分割: dotfiles-conventions・feature-orchestration・commit・sdd-docs を、核 + references（見出しは残し、本文を references へ）。`pi-extension-dev` の参照切れを直した。
- 常設の指示: `watchdog_diff` の記述を直し、Tailscale の節を核 2 行 + スキルにした（家の機の節 1,243 → 447 字）。グローバルの指示の全体は 3,886 → 3,614 字（−7%）。
  **指示ファイル（AGENTS.md）は、固定部分の 11% で、もともと大きな削減の対象ではなかった。**
- 権限: `git flow … publish` を deny（6 規則。bash の規則の末尾）、`gh *api` の前置き対応（7 規則）。判定表に例を足した。最初の実装は 12 規則（前置き × 4 形）を `finish` の規則の前に置いたため、枝名に `finish`・`config` を含む `publish` が後ろの ask に上書きされる穴と、種別の扱いの過不足があった。独立した reviewer の監査で見つかり（MAJOR 1・MINOR 3）、位置を末尾にして 6 規則へ直した。
- 仕様書（手動起動の方針は [skill-frontmatter](../../spec/skill-frontmatter.md#手動起動disable-model-invocation)）: [`agent-config-generation.md`](../../spec/agent-config-generation.md) の経緯・実測を [`permission-policy-rationale-2026-11.md`](permission-policy-rationale-2026-11.md) へ移し、現行の仕様に絞った。仕様と方針の食い違い 3 件を直した。

### 実施後の固定部分の見込み（推定。実機の起動では未確認）

- スキル一覧: 15,754 字（31 本）→ 約 8,900 字（19 本。−44%）。配備後の `SKILL.md` の frontmatter から、pi の `formatSkillsForPrompt`（`disable-model-invocation: true` を一覧から除く）と同じ形で数えた。
  内訳: 手動起動 9 本・Orca 3 本の除外・`learn` と `onboarding` の統合で 13 本が減り、家の機だけ `tailscale-serve` が 1 本増える。
- 指示ファイル: 6,946 字 → 約 5,880 字（−15%。グローバル 3,886→3,614、家の機の節 1,243→447）。
- 固定部分の全体: 約 62,300 字 → 約 54,400 字（−13%）。トークンでは約 3.0 万 → 約 2.6 万の見込み。毎ターンの入力に占める割合は約 9.5% → 約 8.3% で、費用への効きは小さい（上の結論どおり）。

## 測定の方法（再現）

- 固定部分: 最新セッションの先頭の system メッセージ（`~/.pi/agent/sessions/**/*.jsonl` の `role: system` の `sections` と `toolsAdded`）の文字数を、節・ツール宣言ごとに数える。
- 使われ方: セッションの assistant メッセージの toolCall（ツール名・`read` の `path` が `*/skills/<名前>/SKILL.md`）と、`custom` エントリの `customType` を数える。
- 確認の件数: 審査ログ `~/.pi/agent/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl` の `permission_request.*` を、surface・要求元の agent・決定の主体（`decidedBy.kind`）で数える（`friction-review` の `--approvals` が同じ数え方の入口）。
- どれも件数と文字数だけを出し、本文は読まない。

## 未確認・限界

- `/plan`・`/btw`・`/rewind`・`/sandbox` の実際の使用は、ログから完全には分からない。窓は 8 日で、専門スキルの月次の使用は不明。
- 設定 `skills` の `!名前` が、自動検出した `~/.agents/skills/` のスキルに効くことは、pi 1.5.0 のソース（`package-manager.js`）の読解で確かめた。実機の起動では未確認。
- 判定エンジンの実ゲートの挙動は、reviewer も親も未確認（設定・試験・仕様・エンジンのソースの読解まで）。
- T3 Code が足す節（4,007 字）と `mcp__t3-code__*` のツールは、このリポジトリの管理外。ホストの節は「`delegate_task` を使う」と案内するため、常設の指示の「`subagent` で委譲する」と競合する。ホスト側の設定の確認が要る。
- 費用は、pi が計算する名目の値。Copilot 経由の実費は別の可能性がある（推測）。
