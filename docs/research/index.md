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
  `shell/` / `testing/`）で分け、`opencode/` はさらに主題（`permission/` / `plugin/`）で
  分けている
- テンプレートは `~/.claude/skills/sdd-docs/references/research-template.md`

## 一覧

### エージェント CLI 横断

| 文書 | 内容 |
| --- | --- |
| [エージェントハーネス比較](agents/harness-comparison.md) | Claude Code / Copilot CLI / Codex CLIの機能・強制層・設定差分、OpenCodeへの乗り換え評価（2026-09-19 時点の見送り。後に OpenCode を配備） |
| [sandbox機能の包括調査](agents/sandbox-capabilities.md) | Claude Code / Copilot CLIのsandbox全機能、採用状況、落とし穴 |
| [Claude の deny の展開数](agents/claude-deny-glob-expansion.md) | 名前マッチの deny が 3239 件の bind-mount に展開された測定、whitelist 化の根拠 |
| [Copilot の開発ツール自動許可の実効権限](agents/copilot-dev-tool-access-grants.md) | dev-tool access ON 時の取りこぼし・RO 上書き、ヘッダが見えない粒度、PATH の bin が RO、mise の latest が消える |
| [Copilot sandbox の既定の許可範囲](agents/copilot-sandbox-default-policy.md) | `/sandbox policy` の表示、$HOME は未許可、存在しないパスの deny 10 件中 3 件が効かない |
| [compaction 関連の hook 仕様](agents/compaction-hooks.md) | 記録 E1–E7。圧縮の直前・直後に割り込める hook、Copilot の入力契約の実測（Claude / Copilot の hook は 2026-09-25 に撤去） |
| [エージェントの git 入力待ちを防ぐ環境変数](agents/noninteractive-git-env.md) | 2026-10-03。OpenCode V2 の `ctx.shell.hook("create.before")` で子シェルの環境を `??=` で足せる実測、ocs は `inner_env` に足せる、`GIT_TERMINAL_PROMPT=0` は TTY があるときだけ効く、`GIT_EDITOR=false` で `rebase -i` が即失敗（`git commit` と分岐した merge は権限で測れず） |
| [Claude / Copilot で git 入力待ち防止の環境変数を入れられるか](agents/noninteractive-git-env-claude-copilot.md) | 2026-10-04。Claude の `settings.json` の `env` はシェルの値を上書きするので「未設定時のみ」に不適（公式）、`CLAUDE_ENV_FILE` は実機未検証。Copilot は環境変数の設定が無く `preToolUse` の `modifiedArgs` は効くが狭い allow で実行が拒否された（実測）、起動ラッパーは未設定→既定・既設定→維持を実測。推奨は起動ラッパー |
| [秘密ファイル一覧のずれと直下以外の `.env`](agents/secret-file-lists.md) | 2026-10-03。hook の `tables.toml` にあって `read_deny_globs` に無かった資格情報・履歴 15 件、`.env` が `**/` 無しで直下以外は ask 止まりだった実測と、`**/` 化後の deny |

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
| [秘密ファイルの禁止を policies へ移せるか](opencode/permission/policies.md) | 2026-10-08。`experimental.policies` の deny はエージェントの allow・ask・保存した承認・plugin の有無に負けず通常起動で効く、例外の allow は権限を与えない、`plan` の edit の写し直しを置き換えられる、`explore` の 4 つの deny は全体の allow / ask を移さない限り外せない、正しくない statement は警告付きで捨てられ余分なキーは黙って通る |

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

### シェル

| 文書 | 内容 |
| --- | --- |
| [PowerShell プロファイルの起動時間](shell/powershell-profile-startup.md) | pwsh 1420→510 ms などの中央値、cmdlet の初回呼び出しの遅さ、oh-my-posh キャッシュを外した後は未計測 |
| [Windows PowerShell 5.1 / 7 での実機確認](shell/windows-powershell-live-check.md) | 2026-10-05。`copilot` 関数の環境変数・終了コード・finally・パイプ、非対話でのプロファイル、Windows の Python での読み取り判定の大小文字。5.1 はネイティブ引数（`"`・空文字・末尾 `\`）が欠ける。pwsh 7 は `finally` が変数を空文字で残す不具合（修正済み・再確認済み）、未確認は対話シェル |
| [非対話シェルで mise の shims を使う](shell/mise-shims-resolution.md) | 2026-10-03。shims を先頭側に置くと cwd の `mise.toml` に従う、`activate` 済み PATH の継承は版が固定される、未 trust はエラー終了で待たない、venv が先なら venv が勝つ、shim は約 40 ms/回 |
| [zenoとzsh-autosuggestionsの連携](shell/zeno-autosuggestions-integration.md) | 2026-05-12〜13。widget競合の原因、ロード順、回避策 |

[ドキュメント一覧へ戻る](../index.md)
