# 調査記録

特定時点の実測、比較、アップストリーム調査を保存します。
現在の運用ルールは [仕様・運用](../spec/index.md)、採用した設計判断は
[ADR](../adr/index.md) を参照してください。

読み手は利用者（エージェントが何を調べたかのレポート。[ADR-0032](../adr/0032-docs-by-audience.md)）。撤去した自作基盤（ハーネス・sandbox・opencode など。[ADR-0037](../adr/0037-retire-custom-profile-and-other-harnesses.md)）の調査も、当時の記録として残している。

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

- 追記した節には、見出しか節の冒頭に**日付**を書く。日付が無ければ
  ファイル冒頭の日付の観測とみなす
- **過去の観測・結論を書き換えない。** 訂正・撤回は新しい節か新しい記録として
  足し、元の節の冒頭に訂正先への案内を置く。誤字とリンク切れの修正は別
- 追記で節が 10 を超えたら、冒頭に「読み方」（節の群・日付・覆った節）を置く
  （例: srt の適用可否）
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

### pi・エージェント

| 文書 | 内容 |
| --- | --- |
| [長い文脈は要らない（論文）と圧縮の方針](agents/long-context-compaction-paper-2026-11.md) | 2026-11-09。arXiv:2611.05306 の要点（頻繁な圧縮でも精度はほぼ保たれる。良い圧縮は物語ではなく brief）と、自分の運用 104 セッションの集計（25 万超が 69%、圧縮の中央値は約 79 万、長さによる品質の低下は見えない。圧縮の直後に不満の手がかりが増える傾向）。確定した方針: 70 万で圧縮（本体の `reserveTokens`）、`pi-compaction` は要約の指示の恒久設定だけ、自作なし |
| [圧縮の失敗の調査](agents/pi-compaction-failure-survey.md) | 2026-11-02。pi 1.4.0。セッション記録には成功した圧縮（11 回）しか残らず、失敗の文言が取れない（原因は未確定）。公式の既知の不具合は 1.4.0 で多くが修正済み。`session_compact_failed` で理由を残す観測を足す。要約の長さの実測（2026-11-03、8 回で 3.7 万〜5.9 万字）と、長さ・思考レベルの上限の対策 |
| [pi の公開拡張の調査と、使えないことの不利益](agents/pi-public-extensions-survey.md) | 2026-10-20。P1: 月間ダウンロード数の上位 150 件を分類し、今のハーネスと対比。主要な機能は自作で持っている。不足は、構造化した質問・永続する記憶・LSP の診断・worktree 隔離の 4 点。スキルは軽く試せるが拡張は重い。中継プロキシ型・観測の SaaS 送信・ Web UI は避ける。npm の検索 API は重複で網羅に使えない。P3: 自作拡張の採点（総合 B+ 78 点。安全 A・機能の幅 C+）。P4: ask-user 系拡張の方式と反例。P5（2026-10-21）: 人気の `pi-memory`・`pi-btw`・`pi-advisor-flow`・`pi-fff` を既存の仕組みと比べた。どれも導入しない（`review` を `explorer` 役に、`btw` を `explore` の子にした）。**P6（2026-10-22）: worktree 隔離の先行例（`@gotgenes/pi-subagents-worktrees` 0.3.3・`@tintinweb/pi-subagents` 0.22.0 の配布物を読んだ）と、P1〜P5 の訂正（質問は実装済み・通知・P2 の不満・`btw`・P3 の行数と点数は現行ではない）。上の「不足 4 点」「総合 B+ 78 点」は P1・P3 当時のもの**。**P7（2026-10-22）: worktree 隔離の先行例を Claude Code・Cursor（公式 docs）、Codex アプリ（二次情報）で比べた。`git worktree lock` で実行中を守る、自分が作ったものだけを掃除する、同時数の上限、filter driver の確認を CHG-0029 に取り入れた。実機では動かしていない** |
| [AI コーディングエージェントの利用者は、どれくらい隔離して使っているか（声と指標）](agents/sandbox-user-adoption-2026-11.md) | 2026-11-06。ADR-0028 の判断材料。利用者側の選択を、公開リポジトリの設定（Claude Code のプロジェクト設定 83,584 件のうち sandbox 有効と思われるものが約 1.4%、Codex は `sandbox_mode` を明示した中で全開放が約 18%、devcontainer で Claude Code 6,752 件）と HN のスレッドから見る。多数派はホストでの YOLO と Docker・devcontainer。数値つきの利用者調査は見つからず |
| [同種の OSS（coi・isx）の評価と、kcage との比較](agents/oss-sandbox-evaluations-2026-11.md) | 2026-11-08。静的調査。どちらも制御面の分離・GPU・WSL2 の要件を満たさず不採用。借りた点（coi の親ディレクトリの固定・isx の独立 clone＋fetch）。 |
| [pi の sandbox 拡張と GPU: 実機の比較（bubblewrap 系・Docker 系）](agents/pi-gpu-sandbox-2026-11.md) | 2026-11-11〜12。`pi-safe`・`@yuru7/pi-sandbox`・`pi-permission-modes`・`pi-less-yolo` のフラグを WSL2 で実測。どれも設定だけでは GPU が通らず、`--dev-bind /dev/dxg` を `--dev /dev` の後に足せば通る。`pi-safe` は docker 経由で HOME に書ける、`pi-less-yolo` は rootless で cwd に書けない、など |
| [Fence を pi のシェルの先に置く実測（WSL2）と、起動の遅さの原因](agents/fence-latency-2026-11.md) | 2026-11-12。bash・`bg_run`・`!` 相当・子の bash が囲いを通り、GPU・秘密・`/tmp`・通信・キャッシュは設定で通る。遅さ（1 コマンド約 1.0 秒）の主因は、WSL の `/mnt` 配下の `PATH` 要素と cwd の走査で、ラッパーで `PATH` から `/mnt` を外すと約 0.25 秒（実測）。公式は全体を 1 回包む使い方を勧め、常駐の仕組みは無い |
| [stock の pi の package の評価（2026-11）](agents/pi-stock-packages-evaluation-2026-11.md) | 2026-11-08〜09。入れる 7 つ（permission-system・cc-safety-net・subagents・mcp-adapter・web-access・rpiv-todo・rpiv-ask-user-question）の評価・決定と、追加の 4 つ（pi-background・pi-plan-mode・pi-goal・pi-rewind）の評価・決定、検索の決定の経緯、見つけた他の候補（未評価）、btw（`@narumitw/pi-btw@0.63.5`。ツール登録なし・実依存 1 つを grep で確認、実機の `/btw` の確認が導入の条件）の評価・決定、tok/s 表示（`pi-show-token-rate@0.3.0`。ファイル・ネットワーク・子プロセスが 0 件なことを grep で確認、実機での数値の確認が導入の条件）の評価・決定。 |
| [検索・モデルのデータの扱いの裏取り](agents/web-search-data-handling.md) | 2026-10-24。D1: 制約のある環境の Bedrock・AgentCore と、個人機の Copilot・検索 API の公式のデータの扱い。Bedrock は学習に使わずモデルプロバイダーと共有しないが、一部のモデル（Claude Fable 5 / 5.1 など）は最大 30 日保持され人の確認の対象になりうる。AgentCore の検索のクエリは AWS の外へ出ない。「opt-out 設定」の正体は公式文書から特定できない。Brave はクエリを最大 90 日保持、Copilot の学習への利用の既定値は不明 |
| [imozuru 仕様の経緯・実測・レビュー記録](agents/imozuru-spec-notes.md) | 2026-10-21〜25 の取り込み・調査・レビュー（`imozuru.md` から移設） |
| [pi の圧縮の 400 エラー（thinking: disabled）の経緯](agents/pi-compaction-400-history.md) | 2026-10。`pi-guard.md` から移設 |
| [子エージェント（guarded_task。撤去済み）の経緯・日付・試験結果](agents/pi-subagents-spec-history.md) | 2026-10-09〜22。`pi-guard.md` から移設 |
| [web 検索スキル仕様の実測・経緯](agents/web-search-spec-notes.md) | 2026-10-11〜26 の実測と CHG-0032 の経緯（`web-search.md` から移設） |
| [子エージェントの権限（agent ファイルの `permission:`）の実測](agents/subagent-permission-frontmatter-2026-11.md) | 2026-11-10。`external_directory: deny`（単一の値）は、作業ツリーの外の `read`・bash のパス引数を確認なしで即座に拒否した（審査ログでも確認）。入れ子の書式は agent 定義が無効になる。許可リストより `deny` が強い。user 配下の写しでの実測は未確認 |

### テスト

| 文書 | 内容 |
| --- | --- |
| [Raspberry Pi 4 がメモリ切れで SSH ごと固まった件](testing/raspi-oom-ssh-freeze.md) | swap 0 で gitleaks のソースビルド中に固まった経過、zram / earlyoom 導入後の確認 |
| [Docker の cold start 検証で直した障害](testing/docker-cold-start-fixes.md) | tmpfs の noexec、modify_ の python3 解決、Pi 扱いの注入が init で消える、Codex の TOML 連結など解決済み 9 件の経緯 |
| [開発ガイドの実測メモ](testing/development-timing-notes.md) | hook の所要時間・全件の時間・Windows Sandbox の実測・利用者の判断（`development.md` から移設） |
| [testing 仕様の実測メモ](testing/testing-spec-notes.md) | 近似 runner の実測と日付つきの注記（`testing.md` から移設） |
| [撤去後の試験を、これ以上減らす価値があるかの実測](testing/test-reduction-2026-11.md) | 2026-11-12。残った約 1,550 件の時間配分（0.1 秒未満が 1,413 件・遅い 1 ファイルが 3 割強）と、カバレッジで洗い出した重複を減らしたときの変異テストでの検出力の低下（5〜17%）。件数を減らさない判断 |

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
