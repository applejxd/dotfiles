# 調査記録

特定時点の実測、比較、アップストリーム調査を保存します。
現在の運用ルールは [仕様・運用](../spec/index.md)、採用した設計判断は
[ADR](../adr/index.md) を参照してください。

## 運用

- ファイル名は `kebab-case-topic.md`（連番なし）
- 観測日・対象の版・一次情報の URL を必ず書く
- 実測は**実行したコマンドと出力**を載せる。推測を書くときは「推測」と明示する
- 陳腐化しても削除しない。「いつ時点か」が分かれば古い観測にも価値がある
- **現在の総合判断は [探索・変更案件](../change/index.md) の候補比較表が正本。**
  ここを全部読まないと現状が分からない状態にしない

### 記録の単位

**1 記録 = 1 つの問い。** 同じ問いを測り直した・掘り下げた観測は、同じ
ファイルへ**日付の付いた節**として足してよい。問いが変わったら新しい記録にする。
形は次の 3 つを認める。

| 形 | 使う場面 | 例 |
| --- | --- | --- |
| 単発 | 1 回の調査で閉じる | [allow リスト監査](opencode/permission/allow-list-audit.md) |
| 連番の記録（`## 記録 E1 — <日付>`） | 仮説と検証を何度も回す | [compaction 関連の hook 仕様](agents/compaction-hooks.md) |
| 節の追記 | 1 つの調査を配備・再測で掘り下げる | [permission 適用範囲の穴](opencode/permission/gaps.md) |

- 追記した節には、見出しか節の冒頭に**日付**を書く。日付が無ければ
  ファイル冒頭の日付の観測とみなす
- **過去の観測・結論を書き換えない。** 訂正・撤回は新しい節か新しい記録として
  足し、元の節の冒頭に訂正先への案内を置く。誤字とリンク切れの修正は別
- 追記で節が 10 を超えたら、冒頭に「読み方」（節の群・日付・覆った節）を置く
  （例: [srt の適用可否](opencode/permission/sandbox-runtime.md)）
- **追記で育った記録も割らない。見出しの文言も変えない。** 案件・仕様・コードの
  コメントが節番号と見出しで参照している（`調査記録 19 節` など）。
  短い記録を細かく分けることもしない

### 後の観測・現行の仕様への案内

索引から古い結論へ直接入っても気付けるようにする。後の観測や現行の仕様
（[spec/](../spec/index.md)）と食い違う記録には、**冒頭に**次の形で案内を付ける。
本文はそのまま残す。一覧の「内容」に覆った結論を書くときも、当時のものと分かる形にする。

```markdown
> **後続の観測**: <覆った結論と、覆した記録へのリンク>
>
> **現行の仕様**: <spec へのリンク>
```

### 置き場

- 増えたらサブディレクトリへ分ける。現在は対象（`agents/` / `opencode/` /
  `shell/` / `testing/` / `chezmoi/`）で分け、`opencode/` はさらに主題（`permission/` / `plugin/`）で
  分けている
- テンプレートは `~/.claude/skills/sdd-docs/references/research-template.md`

## 一覧

### エージェント CLI 横断

| 文書 | 内容 |
| --- | --- |
| [エージェントハーネス比較](agents/harness-comparison.md) | Claude Code / Copilot CLI / Codex CLIの機能・強制層・設定差分、OpenCodeへの乗り換え評価（2026-09-19 時点の見送り。後に OpenCode を配備） |
| [sandbox機能の包括調査](agents/sandbox-capabilities.md) | Claude Code / Copilot CLIのsandbox全機能、採用状況、落とし穴 |
| [pi のハーネスの試作](agents/pi-harness-spike.md) | 2026-10-08。E1: 組み込みと同じ名前のツールは `/reload` でハーネスが抜けると組み込みが戻り判定なしで実行（`-nbt` でも）、別名ならツール 0 個。`execute()` での再検査で入力の書き換えを拒否、判定器の異常 5 通りはすべて拒否。E2: 別名のツールを 4 モデルが迷わず使用、既定の圧縮は別名のファイル操作を拾わずハーネスで補う。E3: 並列の ask は codemode の中でだけ重なり先の確認が永久に止まる（順番待ちで解消）、bash の `details` に生の出力が残る（伏せて 0 件）、codemode・MCP もハーネスの判定を通る。E4: 子エージェントも同じハーネスで判定し子の ask を `blocked` で親へ返せる、Fence で包めるが pi は設定・認証の読み取りでも `.lock` を作るので agent 置き場は書ける必要がある |
| [ハーネス付きの pi への拡張の追加](agents/pi-extension-under-harness.md) | 2026-10-11。E5: 明示の `-e` の拡張は `-ne` でも読まれ、ツールは判定（役割の `tools`・既定の確認）と結果の伏字化を通る。同名ツールの差し替えは pi が起動を止める。ただし拡張の読み込み時の処理は囲えない。E6: `pis` では `exposure` が既定の `codemode` の MCP のツールは呼べない（`-nbt` で `codemode` が宣言されない）（Windows で実施。Unix は未実施） |
| [pi をどこで・どこまで守って動かすか](agents/pi-isolation-options.md) | 2026-10-24 に I2 を追記（OpenShell で PowerShell の `pis` の問題は解決しない見込み。Windows ネイティブは MXC が「Coming soon」で、docs の経路は WSL2 + Docker Desktop の Linux コンテナ）。2026-10-13。I1: pi 本体に承認機能は無く、公式は境界（隔離）を勧める。Windows の隔離手段の比較（Sandbox・Hyper-V・`wslc`・専用ユーザー）、`wsb` の CLI、Sandbox での導入検証の実測、ハーネスの Windows 移植を見送った理由。運用の判断: Windows ネイティブの `pi` は信頼できる環境でだけ、ガードなし |
| [pis（標準のサンドボックス）の実機の挙動](agents/pis-sandbox-field-test.md) | 2026-10-15。S1: 12 項目のうち 11 が期待どおり。Orca の資格情報の漏れ・共通指示の欠落・`fd` の毎回のダウンロードを見つけて直した。S2（2026-10-25）: 内側は DNS を引けないがプロキシ越しの CONNECT は通り、許可外は 403。ページ取得の失敗はツールの事前の名前解決が原因。クリップボードの失敗と回避策（`PI_CLIPBOARD_OSC52`） |
| [Zed（pi-acp）・Orca から `pis` を使う方法](agents/zed-orca-pis-integration.md) | 2026-10-20。Z1: pi-acp は環境変数 `PI_ACP_PI_COMMAND` で起動コマンドを差し替えられ、`confirm`・`notify`・`setStatus` を扱える。`pis --no-sandbox` の RPC は手元で通った。Orca は起動コマンドの上書きを持つ。pi-acp 本体・Zed・Orca の実機は未確認。Z2（2026-10-21）: Orca のネイティブチャット（Pi Chat）は WSL・SSH では使えず、WSL のプロジェクトは「No chat in WSL」でターミナルのみ（Windows 側のプロジェクトなら使える） |
| [pi のバックグラウンド処理の実機実験](agents/pi-bg-experiments.md) | 2026-10-20。B1: 実モデル 4 つ・13 シナリオで `bg_run` / `bg_kill` / `guarded_task` の background を試した。基本は動く。`&` の拒否は行末にしか効かず 2 モデルがすり抜け、`gpt-6-sol` は `guarded_task` が壊れ、並行ジョブは 1 件ごとに 1 ターン、ログのパスは読めず行き止まり |
| [pi の公開拡張の調査と、使えないことの不利益](agents/pi-public-extensions-survey.md) | 2026-10-20。P1: 月間ダウンロード数の上位 150 件を分類し、今のハーネスと対比。主要な機能は自作で持っている。不足は、構造化した質問・永続する記憶・LSP の診断・worktree 隔離の 4 点。スキルは軽く試せるが拡張は重い。中継プロキシ型・観測の SaaS 送信・ Web UI は避ける。npm の検索 API は重複で網羅に使えない。P3: 自作拡張の採点（総合 B+ 78 点。安全 A・機能の幅 C+）。P4: ask-user 系拡張の方式と反例。P5（2026-10-21）: 人気の `pi-memory`・`pi-btw`・`pi-advisor-flow`・`pi-fff` を既存の仕組みと比べた。どれも導入しない（`review` を `explorer` 役に、`btw` を `explore` の子にした）。**P6（2026-10-22）: worktree 隔離の先行例（`@gotgenes/pi-subagents-worktrees` 0.3.3・`@tintinweb/pi-subagents` 0.22.0 の配布物を読んだ）と、P1〜P5 の訂正（質問は実装済み・通知・P2 の不満・`btw`・P3 の行数と点数は現行ではない）。上の「不足 4 点」「総合 B+ 78 点」は P1・P3 当時のもの**。**P7（2026-10-22）: worktree 隔離の先行例を Claude Code・Cursor（公式 docs）、Codex アプリ（二次情報）で比べた。`git worktree lock` で実行中を守る、自分が作ったものだけを掃除する、同時数の上限、filter driver の確認を CHG-0029 に取り入れた。実機では動かしていない** |
| [OpenShell と現行サンドボックスの比較](agents/openshell-comparison.md) | 2026-10-23。O1: OpenShell v0.1.5 を、公式の docs・issues・NVD と第三者の記事で調べた（動かしていない）。判定側を境界の外に置く・資格情報を渡さない設計が文書にある一方、コンテナか VM が要り、WSL2 は experimental で不具合の報告があり、重大な脆弱性が 2 件ある。独立した検証は見つからない |
| [自作サンドボックスの代替候補の比較](agents/sandbox-alternatives-comparison.md) | 2026-10-24。C1: Docker Sandboxes・nono・srt・Claude Code ネイティブ・Fence を、WSL2・pi・資格情報・ホストの道具・子の隔離で比べた（動かしていない）。nono は pi を名指しで対応するが WSL2 では資格情報の代理が既定で使えない。Docker Sandboxes は Windows ネイティブで資格情報を注入するが WSL2 の中や pi の記述は無い。コマンド内容を解析する層を持つ既製品は見つからなかった |
| [検索・モデルのデータの扱いの裏取り](agents/web-search-data-handling.md) | 2026-10-24。D1: 制約のある環境の Bedrock・AgentCore と、個人機の Copilot・検索 API の公式のデータの扱い。Bedrock は学習に使わずモデルプロバイダーと共有しないが、一部のモデル（Claude Fable 5 / 5.1 など）は最大 30 日保持され人の確認の対象になりうる。AgentCore の検索のクエリは AWS の外へ出ない。「opt-out 設定」の正体は公式文書から特定できない。Brave はクエリを最大 90 日保持、Copilot の学習への利用の既定値は不明 |
| [サンドボックス内のエージェントへの認証の渡し方](agents/agent-auth-delegation.md) | 2026-10-24。D6 で GitHub（gh）の方式（世間は MITM ＋ CA。gh の http_unix_socket ＋ Envoy が単純で実測済み）を確認。D5 で世間の実践（主流は内側に置く。隔離は 2026 年に出始めた段階）と既製の署名プロキシの実用性（aws-sigv4-proxy は応答がバッファされる）を確認。D4 で LiteLLM を再評価（サプライチェーンの対策は取れるが、決め手は機能: Bedrock の忠実度・重さ・Copilot の DB なしの不確かさ。pi の Copilot の長期トークンは read:user だけ）。D3 で LiteLLM の MCP Gateway・AgentCore・GitHub の連携と、設計を真似る要点、共有ゲートウェイと個人の GitHub の制約を追記。D2: 制約のある環境の Bedrock・AgentCore と個人機の GitHub で、強い認証情報を内側に置かずに使う手段を網羅調査（動かしていない）。Bedrock の短期 API key（最大 12 時間）、ホスト側の署名プロキシ、AgentCore の JWT 認証、GitHub App の 1 時間のトークン。常駐のゲートウェイは必須でない。LiteLLM は 2026-03 と 2026-10 にサプライチェーン事件（2 回目は署名導入済みでも突破） |
| [Bedrock ブローカーの実機確認（段 U7b）](agents/bedrock-broker-field-test.md) | 2026-10-26。B1: 実機で、スクリプトを 2 回実行して最後の 1 行（報告コード）を手で返す手順。署名・ストリーミング・鍵の更新・プロキシ越しなどを確かめる（偽の上流での確認は済み、実機は未取得）。Copilot ブローカーとの機能差のうち、Bedrock で未検証・未決・未実装のものの一覧 |
| [他のコーディングエージェントの、ファイル操作・シェルツールの作りと、専用ツールへ寄せる仕掛け](agents/tool-design-survey.md) | 2026-10-24。OpenCode・Claude Code・Codex・Crush・Gemini CLI・Roo・Cline・Continue・Copilot・Zed・Amp・Goose・Aider・pi を比較。tail・一括読み・追記・stdin の専用引数はどこにも無い（一括読みは非推奨へ）、cat の拒否をする製品は無く説明文が主流、Claude はヒアドキュメントの書き込みに先験がある可能性 |
| [全承認（bypass・yolo）モードでも確認を残す仕組みと、公開・送信系のガードの分類](agents/permission-bypass-survey.md) | 2026-10-25。Claude Code・Gemini・Codex・OpenCode・VS Code・Cursor・pi の公開拡張・コマンドガードの OSS（dcg など）を比較。Claude Code が `confirm`（bypass でも出す ask）に最も近い、外部送信を既定で止める製品は無い、`gh api` の暗黙の POST への手当てが OSS に無い、上位層が ask を自動回答する落とし穴 |
| [外部送信・公開・破壊的操作を防ぐ設計の代替案（網羅調査）](agents/guard-design-alternatives.md) | 2026-10-25。ネットワーク層・資格情報・環境と承認方式・リポジトリ内の独立評価。3 層の骨格は現状維持が妥当。小さな改善は個人機の gh の権限（OAuth が広い）と、ブローカーへの REST の deny の「追加」（撤去は不可。GraphQL と git が残る） |
| [プロキシ必須の環境で境界の通信を通すには](agents/corp-proxy-boundary.md) | 2026-10-15。Fence は許可済みの通信を直接つなぎ、上流プロキシはグレーゾーン用。`srt` の `parentProxy` は許可リストを保って通るが、`pis` の境界の形（R1・存在しない保護対象・`$HOME` 拒否）が載らない。許可リストを照合する中継を足して解決（制約のある環境の機械では未実測） |
| [Claude の deny の展開数](agents/claude-deny-glob-expansion.md) | 名前マッチの deny が 3239 件の bind-mount に展開された測定、whitelist 化の根拠 |
| [Copilot の開発ツール自動許可の実効権限](agents/copilot-dev-tool-access-grants.md) | dev-tool access ON 時の取りこぼし・RO 上書き、ヘッダが見えない粒度、PATH の bin が RO、mise の latest が消える |
| [Copilot sandbox の既定の許可範囲](agents/copilot-sandbox-default-policy.md) | `/sandbox policy` の表示、$HOME は未許可、存在しないパスの deny 10 件中 3 件が効かない |
| [compaction 関連の hook 仕様](agents/compaction-hooks.md) | 記録 E1–E7。圧縮の直前・直後に割り込める hook、Copilot の入力契約の実測（Claude / Copilot の hook は 2026-09-25 に撤去） |
| [エージェントの git 入力待ちを防ぐ環境変数](agents/noninteractive-git-env.md) | 2026-10-03。OpenCode V2 の `ctx.shell.hook("create.before")` で子シェルの環境を `??=` で足せる実測、ocs は `inner_env` に足せる、`GIT_TERMINAL_PROMPT=0` は TTY があるときだけ効く、`GIT_EDITOR=false` で `rebase -i` が即失敗（`git commit` と分岐した merge は権限で測れず） |
| [Claude / Copilot で git 入力待ち防止の環境変数を入れられるか](agents/noninteractive-git-env-claude-copilot.md) | 2026-10-04。Claude の `settings.json` の `env` はシェルの値を上書きするので「未設定時のみ」に不適（公式）、`CLAUDE_ENV_FILE` は実機未検証。Copilot は環境変数の設定が無く `preToolUse` の `modifiedArgs` は効くが狭い allow で実行が拒否された（実測）、起動ラッパーは未設定→既定・既設定→維持を実測。推奨は起動ラッパー |
| [秘密ファイル一覧のずれと直下以外の `.env`](agents/secret-file-lists.md) | 2026-10-03。hook の `tables.toml` にあって `read_deny_globs` に無かった資格情報・履歴 15 件、`.env` が `**/` 無しで直下以外は ask 止まりだった実測と、`**/` 化後の deny |
| [AI CLI 設定の生成に関する経緯・実測](agents/agent-config-generation-notes.md) | MCP の配布の経緯・常駐ポートの衝突・モデル階層の比較・hooks 撤去の経緯。2026-08〜10（`agent-config-generation.md` から移設。再測定していない） |
| [Claude / Copilot の sandbox の許可範囲と経路の実測](agents/agent-sandbox-measurements.md) | 2026-09 の実測と未決の点（`agent-sandbox.md` から移設。再測定していない） |
| [AI CLI の実行時の障害の観測（引数破損の頻度・pis のクリップボード）](agents/agents-runtime-observations.md) | 2026-10。頻度と上流 Issue の経緯（`troubleshooting-agents.md` から移設） |
| [ブローカー仕様の実測と経緯](agents/broker-spec-notes.md) | 2026-10-24〜25 の実測（`broker.md` から移設） |
| [checkpoint 仕様の経緯・実測](agents/checkpoint-notes.md) | 2026-09-24 に OpenCode 専用にした経緯、A1 と A2/B の分離、保存先の変遷（`checkpoint.md` から移設） |
| [Claude Code permission リストの既知バグ](agents/claude-permission-known-bugs.md) | 2026-05 時点の issue の表。現在の状態は未確認（`agent-command-policy.md` から移設） |
| [コマンド判定の設計の経緯メモ](agents/command-policy-design-notes.md) | 廃止した判定・以前の穴・採用理由（`agent-command-policy.md` から移設） |
| [imozuru 仕様の経緯・実測・レビュー記録](agents/imozuru-spec-notes.md) | 2026-10-21〜25 の取り込み・調査・レビュー（`imozuru.md` から移設） |
| [モデルの割り当ての見直しの日付つき経緯](agents/model-lineup-review-notes.md) | 2026-10-07 の `commit` の役割変更と採点の前提（`model-lineup-review.md` から移設） |
| [agent-permissions の実測・根拠](agents/permissions-notes.md) | 2026-09-27 の Windows native での確認の範囲（`agent-permissions.md` から移設） |
| [pi の圧縮の 400 エラー（thinking: disabled）の経緯](agents/pi-compaction-400-history.md) | 2026-10。`pi-guard.md` から移設 |
| [長い sleep の誘導の由来と実モデルでの確認](agents/pi-decide-guide-sleep-origin.md) | 2026-10-20。`pi-decide.md` から移設 |
| [自作の拡張（todo / plan / btw / activity / ask / notify / delegate-nudge）の実測と未確認](agents/pi-own-extensions-measurements.md) | 2026-10。`pi-guard.md` から移設 |
| [子エージェント（guarded_task）の経緯・日付・試験結果](agents/pi-subagents-spec-history.md) | 2026-10-09〜22。`pi-guard.md` から移設 |
| [pis のサンドボックスの実機発見談と拒否リスト型の実測・未確認](agents/pis-sandbox-spec-observations.md) | 2026-10-15〜26。`pi-guard.md` から移設 |
| [ツール引数の JSON が壊れる問題の調査](agents/tool-arg-json-breakage.md) | 細粒度ツールストリーミング・strict・Bedrock。`pi-guard.md` から移設 |
| [ガードツール（guarded_edit / ask）の失敗の集計と見送った案](agents/tool-extension-measurements.md) | 失敗 118 件・940 件などの集計。`pi-guard.md` から移設 |
| [二つの task（guarded_task と Windows の task）を別物にしている理由](agents/two-task-tools-rationale.md) | 統合しなかった判断と採点の訂正。`pi-guard.md` から移設 |
| [web 検索スキル仕様の実測・経緯](agents/web-search-spec-notes.md) | 2026-10-11〜26 の実測と CHG-0032 の経緯（`web-search.md` から移設） |
| [commit の確認（素の pi）の仕様メモ](agents/commit-confirm-spec-notes.md) | 補助拡張 `commit-confirm` の表示例・一時 index・退避 ref の鎖の実装・実モデルでの確認。移設日 2026-10-26（`pi-guard.md` から） |
| [pi の子エージェント job の結果の保持と通知の仕様メモ](agents/pi-subagent-jobs-notes.md) | `FINISHED_TTL_MS`・通知・保存ファイル・`audit.ts` の実装の細部と試験。移設日 2026-10-26（`pi-guard.md` から） |
| [AI CLI 設定の生成に関する経緯・実測の記録（その 2）](agents/agent-config-generation-notes-2.md) | 子エージェント・コミットの確認・`/fleet`・bypass の子の、宣言しなかった不具合・採らなかった案・実測（N9〜N12）。2026-09〜10 |
| [pi を AI オーケストレーターとして使う仕組みの調査](agents/pi-orchestrator-survey.md) | 2026-10-26。O1: 導入に値する公開拡張は無く（親を管理専用にするのは edxeth/pi-subagents と @saifymatteo/pi-orchestrator など少数で、どれもフルガードと合わない）、自作の `guarded_task` に orchestrator ロール・待ち合わせ・DAG を足す方針。借りる設計・RPC で複数の子を管理する落とし穴・他社（Claude Code・Codex・Cursor・Anthropic・Cognition）の知見。実機での試験は未実施 |
| [親を「計画・判断・委譲」に絞る仕組みの設計（`plan` の子の案）](agents/orchestrator-role-plan.md) | 2026-10-30。許可リストの `orchestrator` と `setActiveTools`・判定の二重の防御、弱・中・強の 3 案、親専用の検査操作 `check_*`、環境別の変化。中案を選んだ。未確認: pi 1.4.0 の docs 上の保証 |
| [オーケストレーションの役割別のモデル割り当ての調査](agents/subagent-model-assignment.md) | 2026-10-27（M5 は 2026-11-01）。M5: 親の既定を medium から xhigh へ上げた実測（軽い読み取りは medium 18 秒・$0.089、xhigh 19 秒・$0.095、max 324 秒・$0.686。各 1 回）。M1: 「計画は Claude、実装は GPT」の通説に、一次資料の実測は見つからなかった（体験談で向きも逆の記事がある）。一次資料が支える分担は、能力と費用の分担で、同じ系統の中（`opusplan`・Opus リード + Sonnet サブ）。別系統が効く場面はレビュー。公開評価は、Claude がターミナル作業・長期、GPT-6 Sol がマージ可能な差分と費用で優位。委譲の巧さの役割別評価は無し。見立て: 親は最も強いモデル、worker は Sonnet `#medium`（計測済み）に Sol を足して比較、explore は小型を比較、review は作った者と別の系統。実験の設計案つき |
| [スキルの `context: fork` を pi のハーネスで強制できるかの実験](agents/skill-fork-enforcement.md) | 2026-10-27。F1: pi 本体は `context` / `agent` を解釈しない。`input` が展開の前に来るので、`/skill:` はモデルを介さず子へ回せる（強い）。モデルが読む経路は `tool_call` で本文の読み取りをブロックできるが、委任は誘導。シェルの `grep` などは塞げない。F2（2026-10-27）: Claude Code の公式の frontmatter。`context: fork` は本文を子の依頼文にする。F3（2026-10-28）: 全 20 スキルの `fork`・`allowed-tools` の調査。`fork` をそのまま付けてよいのは `fix` だけ。8 スキルが `Bash` を一括で許可していた |

### OpenCode 全般

| 文書 | 内容 |
| --- | --- |
| [OpenCode V2の仕様](opencode/v2-capabilities.md) | permission・plugin hook・skill・compaction・V1からの移行と未実装項目（2026-09-20 時点。乗り換え見送りの材料） |
| [OpenCode V2の試験環境の隔離方法](opencode/test-isolation.md) | XDG_CONFIG_HOME が効かない実証、OPENCODE_CONFIG_DIR、Copilot モデルの引き方、過去記録への影響評価 |
| [OpenCode V2のツール登録とコンテキストコスト](opencode/tool-context-cost.md) | ツール一覧の固定費、codemode true/false の差、ツール化の可否判断 |
| [OpenCode V2のaskと並列バッチ](opencode/ask-and-parallel-batch.md) | 承認待ちは並列を壊さない実測、拒否が中断の起点、permission.reply のスキーマ、askの実効がモードで変わる |
| [OpenCode V2のキーバインド](opencode/keybinds.md) | 未知の ID は黙って無視される実測、ID の実在確認法、ctrl+c を app.exit が握る件、キー送出検証が成立しない理由 |
| [OpenCode V2のスキル frontmatter の解釈範囲](opencode/skill-frontmatter.md) | `context: fork` / `agent` / `allowed-tools` は読み捨てられる実証、スキルは常に会話へ展開される、Claude Code 側は未検証 |
| [OpenCode V2のエージェントごとのモデル指定](opencode/agent-models.md) | 子エージェントの model は効く、V1 の agent キーは #variant を黙って無視する、主エージェントは --agent で選んでもモデルが変わらない |
| [OpenCode V2のcommit / reviewエージェントの実機確認](opencode/commit-review-agents.md) | 割り当てたモデルで起動する、--auto は子セッションの確認を自動承認せず止まる（推測）。外部コマンドを止めた git の allow と git commit の ask の実機（E2）、下ごしらえ 10 回の試行錯誤の計測（E3: opus は allow の形の外に出ない、haiku はコミットせずに返る）、接頭辞をやめ素の形を allow にした版（E4: haiku は上書きを手順 4 の冒頭に置いて 9/10 がコミット、書式はスキル任せだと崩れる）、Copilot の Sonnet で Bedrock の Sonnet を近似した計測（E5: 10/10 がコミット、書式は 14 件すべてそろう、`cd` の誘導と連結の確認は増える）、Copilot の Sonnet 5.5 の計測（E6: opus と同等の 10/10・書式で速く、承認済みの全文を一字も変えずに使う。Copilot の commit を切り替え）、子エージェントに確認画面が見えず「確認は出なかった」と推測で報告した件と、`git commit` と確かめを同じ応答に並べた件（E7: `system` を直して並べた回数 5 → 0、言い切りは減るが親が報告を求めると残る） |
| [OpenCode V2でCopilot CLIの/fleet相当を組む](opencode/fleet.md) | コマンドと作業役の子エージェントだけで動く、並べて呼んだ子は同時に走る、background は使われなかった |
| [OpenCode の階層に当てるモデルと effort](opencode/tier-models.md) | 2026-09-30。worker（`fleet-worker`）は opus / sonnet 5.5 の low〜high で合格率に差が無く sonnet が速い、haiku 4.5 は難しめの課題で 0/4・担当外の編集あり、routine（`commit`）は sonnet 5.5 の effort で差が無い。worker を Sonnet 5.5 に切り替えた |
| [/fleet の作業役への指示を足した前後](opencode/fleet-worker-instructions.md) | 呼び出し元への影響を確かめさせると担当外の罠に触れた報告が 0/2 → 2/2（opus 1/1）、合格率は不変、誘導は 14 → 1 回、確認は `pytest` が大半で 19 → 18 回 |
| [OpenCode の DB を srt の境界の内外で共有できるか](opencode/shared-db.md) | 同時書き込み・外での再開・外からの `/undo` が通った、書き込みの例外は `XDG_DATA_HOME/opencode` 全体、ignore が無いと snapshot が取れない、`TMPDIR` が見えないと通信が止まる |
| [OpenCode V2 は LSP を使えるか](opencode/lsp-support.md) | 2026-10-01。v2.0.14〜v2.0.21 は `lsp` 設定を受理・保持するだけで言語サーバを起動せず診断も出さない（公式の移行ガイド・ソース・バイナリで確認）。実装は V1 にだけある。#50916 は未回答 |
| [配置済みの opencode.json に残るキーと V1 / V2 の併用](opencode/agent-config-ownership.md) | 2026-10-08。宣言から外したキーや V1 の定義が残り、元に戻した後の判定を残った policy が支える。同じ ID を V1 と V2 に書くと V2 が丸ごと勝ち V1 のキーは捨てられる。生成器が持つ範囲を決める「所有の規則」を先に入れれば、段 4 を元に戻すだけで元の JSON に戻る（試作） |
| [`ocs` 境界の仕様の補足記録（経緯・実測）](opencode/opencode-sandbox-spec-notes.md) | bypass を使えるようにした経緯・外したデバイス名の実測・以前の隔離用 DB の移行・起動の遅れの実測（`opencode-sandbox.md` から移設） |

### OpenCode の permission

| 文書 | 内容 |
| --- | --- |
| [permission適用範囲の穴](opencode/permission/gaps.md) | grep/globがread denyを迂回する実測、カスタムツールのバイパス、プロジェクト設定がグローバルに勝つ（policiesだけは勝てない・plugin/mcpは実行される）、read ツールは deny を守る、grep/glob を tools で無効化できる（採らなかった） |
| [設計を縛る制約の総覧](opencode/permission/constraints.md) | CHG-0002の判断の根拠を1枚にまとめたもの。制約13項目、境界が無いこと、sandboxを採用しないとした当時の理由（CHG-0004 で覆った）、誘導対象の選定計測 |
| [Anthropic Sandbox Runtime の適用可否](opencode/permission/sandbox-runtime.md) | 2026-09-22〜24 の 26 節。srtは汎用、denyReadは許可領域の内側にしか効かない、認証情報を落とすだけでgit push/ghが止まる、ドメイン制限とseccompの実測、opencode --standalone ごと包む構成の成立（19節）、境界の外に残る経路、隔離用DBと配備時の癖 |
| [Fence は srt の代わりに OpenCode を包めるか](opencode/permission/fence.md) | 11 項目の実測で一部だけの `denyRead`・R1・snapshot の置き物・`TMPDIR` の問題が消えた、存在しないパスへの `denyWrite` は効かない、起動が約 0.8 秒遅い、`session.synthetic` でホストのエージェントが動いた事故。E2: 実装した `ocs` の組み立てで必須の項目が全部通った、`~/.local/state` を開けないと opencode が `EROFS` で止まる |
| [shell allowの費用対効果とpluginゲート](opencode/permission/shell-allow-and-plugin-gate.md) | 実履歴1,247セグメントでのallow被覆率、静的パターンのクォート/変数回避、ask→allow引き上げの実測（allow 7 件の案は同日の監査で 5 件に） |
| [allowリスト監査](opencode/permission/allow-list-audit.md) | git diff/statusの任意コード実行、sed -n の危険性、リダイレクトが resource に残る実証、allowとaskの等価性 |
| [出力フィルタと子エージェント](opencode/permission/output-filter-and-subagents.md) | execute.afterでshell出力を伏字化できる実証、符号化ですり抜ける限界、continue_loop_on_deny、子エージェントも共通permissionに従う |
| [カスタムエージェント(Bypass)とキーバインド](opencode/permission/bypass-agent.md) | opencode.jsonのkeybindsが除去される実証（cli.json では効く）、modeではなくagentで実装する、permission="allow"の展開、bypassが外す防御の範囲、bypass からだけ呼べる子と承認制の子の除外（deny した子は一覧から消える） |
| [sandboxはあるか](opencode/permission/sandbox.md) | 組み込みsandboxが無いことの確認、shell差し替えでbwrapを被せる実測とその限界、プロセスごと隔離の実証、常駐サービス経由の脱出、snapが動かない、採用時の検討事項 |
| [hookの呼ばれ方とactionの種類](opencode/permission/hook-order.md) | execute.beforeが評価より前に走る実測、external_directoryが別actionで立つ、誘導のdenyは確認を出さない、evaluateにagentが載る、差し替えが評価へ波及する、配備と計装の手順 |
| [静的 deny の pip を execute.before で説明付きに止める](opencode/permission/early-guard.md) | execute.before が静的 deny より先に走り、例外のメッセージ（uv への誘導）がモデルへ届く。plugin 無し・rules.json 破損では静的 deny が止める。ocs 相当・`--auto` でも止まる（bypass は ADR-0014 前の記録では通していたが、現在は止める）。誤検知（`uv pip`・`echo`・`git commit -m`）なし、並列の他呼び出しは動く。追記で pip 以外の deny 全項目へ拡張（A・B・bypass・止めない例の実機確認） |
| [bypass を ask→allow だけに再定義できるか](opencode/permission/bypass-ask-upgrade.md) | bypass から `"*" = "allow"` を外し evaluate で ask を allow に書き換える plugin 方式の実測。shell・外部ディレクトリ・`.env.*` の ask が通り、静的 deny（pip・秘密・.ssh）と子エージェントの起動制限は残り、ask を持つ子は化けず、plugin を外すと ask に戻る。V2 配列版も同結果。ADR-0014 で採用し、実際の生成物での実測を追記 |
| [作業ツリーの外の読み取りとスキルのスクリプト](opencode/permission/external-read-and-skill-scripts.md) | スキルのスクリプトで出ていたのは shell の ask だけ、引数のパスから external_directory は立たない、開けた場所の edit と秘密の deny、コマンド置換は別 resource・引用符は残る、git が fsmonitor を起動、`uv run --no-project` が `.python-version` の実行ファイルを起動 |
| [段階2配備後の被覆率](opencode/permission/stage2-coverage.md) | 実履歴1,031呼び出しでの実測、秘密へ触れた15件を3層が全件受け止める、誘導後も87%が確認、伏字化の誤爆0.3%、内容の形とパス判定は両方要る |
| [組み込みエージェントの制限の上書き](opencode/permission/builtin-agent-override.md) | 全体の permissions が explore / plan などの組み込みの制限を上書きする（公式の仕様）。explore が shell で確認を出し `.env.example` を実際に書けた、`agents.explore` の deny でツールが一覧から消え確認ゼロ、API で取り出した実効規則の評価で plan の edit が漏れる。E2: 試験用の設定で別ポートのサーバを起動すれば実効規則をモデルに頼らず取り出せる（起動直後は 404）、`agents.plan` の宣言で組み込みの規則と plan モードの指示が保たれる、`git log --output` が `build` で確認なしに書けた。E3: `evaluate` に親の ID は無いが `ctx.session.get` で親の今のエージェントを辿れる、`execute.before` の ID と `source.id` が一致する、親が bypass の子の外部の読み取りを自動で許可できた |
| [秘密ファイルの禁止を policies へ移せるか](opencode/permission/policies.md) | 2026-10-08。`experimental.policies` の deny はエージェントの allow・ask・保存した承認・plugin の有無に負けず通常起動で効く、例外の allow は権限を与えない、`plan` の edit の写し直しを置き換えられる、`explore` の 4 つの deny は全体の allow / ask を移さない限り外せない、正しくない statement は警告付きで捨てられ余分なキーは黙って通る。E2: 全体の allow / ask を役割ごとの規則の束へ移すと 14 エージェント中 9 つが今と全件一致し `explore` の補修も外せる、`title` / `summary` に全体の規則が流れ込んでいた、read の例外は policy とエージェント側の両方に要る、規則の束を当てない子は基底の全部許可になる |

### OpenCode の plugin

| 文書 | 内容 |
| --- | --- |
| [plugin生態系の棚卸し](opencode/plugin/ecosystem.md) | 主要プラグインのV1/V2世代判定、Claude Code hook互換3件、oh-my-opencodeの衝突点 |
| [plugin APIの実測](opencode/plugin/api-probe.md) | permission hookの入力・deny実効性・ロード失敗時のfail-open、生コマンドとcwdの取得経路（cwd は後の相関調査で別経路に） |
| [pluginの相関と承認要求の可否](opencode/plugin/correlation.md) | 並列実行時のcwd相関、plugin から ask を出せるかの実測、ctx.permission.rules の不在 |
| [pluginのロード経路](opencode/plugin/loading.md) | 明示指定は絶対パスのディレクトリのみ、~が展開されない、失敗が無言、Orca overlayとの関係、Claude Codeとの仕組みの違い |
| [ask画面へ説明を出す](opencode/plugin/ask-description.md) | 権限ダイアログがmessageを読まない実証、TUI pluginのtoastなら出せる、app_bottomスロットが2.0.12に無い、安価モデルでの説明生成。2.0.14で確認画面のすぐ上のスロット（session.composer.top）に出せる・opencode.jsonの登録でもtui.tsが読まれる（2026-09-30） |

### テスト

| 文書 | 内容 |
| --- | --- |
| [Raspberry Pi 4 がメモリ切れで SSH ごと固まった件](testing/raspi-oom-ssh-freeze.md) | swap 0 で gitleaks のソースビルド中に固まった経過、zram / earlyoom 導入後の確認 |
| [Docker の cold start 検証で直した障害](testing/docker-cold-start-fixes.md) | tmpfs の noexec、modify_ の python3 解決、Pi 扱いの注入が init で消える、Codex の TOML 連結など解決済み 9 件の経緯 |
| [開発ガイドの実測メモ](testing/development-timing-notes.md) | hook の所要時間・全件の時間・Windows Sandbox の実測・利用者の判断（`development.md` から移設） |
| [testing 仕様の実測メモ](testing/testing-spec-notes.md) | 近似 runner の実測と日付つきの注記（`testing.md` から移設） |

### シェル

| 文書 | 内容 |
| --- | --- |
| [PowerShell プロファイルの起動時間](shell/powershell-profile-startup.md) | pwsh 1420→510 ms などの中央値、cmdlet の初回呼び出しの遅さ、oh-my-posh キャッシュを外した後は未計測 |
| [zsh の起動時間](shell/zsh-startup-time.md) | 2026-10-18。WSL2 で 0.37〜0.40 s → 0.24〜0.25 s、区間別の時間、`/mnt/*` を走査する `command -v` が約 10 ms、`${__p#*…}` が 37 ms。macOS / Windows / 別マシンは未検証 |
| [Windows PowerShell 5.1 / 7 での実機確認](shell/windows-powershell-live-check.md) | 2026-10-05。`copilot` 関数の環境変数・終了コード・finally・パイプ、非対話でのプロファイル、Windows の Python での読み取り判定の大小文字。5.1 はネイティブ引数（`"`・空文字・末尾 `\`）が欠ける。pwsh 7 は `finally` が変数を空文字で残す不具合（修正済み・再確認済み）、未確認は対話シェル |
| [非対話シェルで mise の shims を使う](shell/mise-shims-resolution.md) | 2026-10-03。shims を先頭側に置くと cwd の `mise.toml` に従う、`activate` 済み PATH の継承は版が固定される、未 trust はエラー終了で待たない、venv が先なら venv が勝つ、shim は約 40 ms/回 |
| [zenoとzsh-autosuggestionsの連携](shell/zeno-autosuggestions-integration.md) | 2026-05-12〜13。widget競合の原因、ロード順、回避策 |
| [シェル・VS Code まわりの経緯メモ](shell/structure-shell-notes.md) | シェルの起動契約で採らなかった案・code-exam の案・拡張スクリプト廃止の経緯（`structure.md` から移設） |

### chezmoi の導入・移行コード

| 文書 | 内容 |
| --- | --- |
| [過去の実装に依存する処理の棚卸し](chezmoi/legacy-cleanup-inventory.md) | 2026-10-18。移行・掃除コードを「消せる条件」付きで記録。他のマシンへの適用状況を把握できないため、死にコード以外は残した |
| [導入・適用の障害の観測記録](chezmoi/bootstrap-observations.md) | mise の npm ツールの欠損（2026-09-15）・GitHub CLI の APT 鍵の失効（2026-10-01）（`troubleshooting-bootstrap.md` から移設） |
| [セキュリティ仕様の経緯メモ](chezmoi/security-spec-notes.md) | chezmoi 本体の age 暗号化の廃止の経緯・旧『実行境界』の記述（`security.md` から移設） |
| [Raspberry Pi 向け導入の観測メモ](chezmoi/structure-raspi-notes.md) | clang の標準ヘッダの観測（2026-10-01・10-05。`structure.md` から移設） |
| [Windows 設定の実測・経緯メモ](chezmoi/structure-windows-notes.md) | WSL 3.0.1・GPU のクラッシュ・sudo・PATH 降格・oh-my-posh・7-Zip・電源・ウィジェット・LGPO など（`structure.md` から移設） |
| [sudo を使うスクリプトを Ansible に寄せると楽になるか](chezmoi/ansible-for-sudo-scripts.md) | 2026-10-29。sudo の使用箇所の棚卸し（Linux 4〜5 本）・Ansible の公開情報・評価。全面の置き換えは勧めず、Linux へのキープアライブの共有と、121 の Pi 専用 `/etc` の小さな試作を勧める |
| [121_ubuntu の apt と Pi 専用の /etc を Ansible に移した試作の実測](chezmoi/ansible-trial-121.md) | 2026-10-29。Docker（ubuntu:24.04）で playbook 133 行 vs 元 約 120 行。2 回目 changed=0・導入 80 秒/31MB。まっさらな環境の `--check` は失敗（apt で入れる物に依存）。真偽値の型の落とし穴など。範囲は小さく、実機の Pi は未実施 |
| [WSL の時刻同期と SSH の実測メモ](chezmoi/structure-wsl-time-and-ssh-notes.md) | 時刻同期の未確認事項・SSH の層別の実測・LAN の IP の実験（`structure.md` から移設） |
| [専用 WSL2 の時刻同期の実測](chezmoi/wsl-sandbox-time-sync.md) | 2026-10-18〜19 の実測と原因分析・構築記録（`wsl-sandbox.md` から移設） |
| [再実行の印（retry marker）の置き場に関する記録](chezmoi/rerun-scripts-notes.md) | 印の置き場を sandbox から書けない場所にした理由と、旧置き場の廃止。日付なし（コードの読解。`troubleshooting-bootstrap.md` から移設） |

[ドキュメント一覧へ戻る](../index.md)
