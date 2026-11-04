# ローカル PR ビューアの設計

GitHub をリモートに持たない開発で、PR 風のレビュー画面（Web）と pi を往復させる仕組みの設計。
案件と経緯は [CHG-0060](../change/0060-local-pr-viewer.md)。**設計は 2026-11-03 に確定。実装は段階的で、未実装の段は各節に「未実装」と書く。**

## 1 概要と状態

| 項目 | 内容 |
| --- | --- |
| 目的 | リモートが無くても、差分と pi のサマリーを PR のように読み、統合する（レビューコメントの送信は撤去済み。下の「レビューコメント送信の撤去」）。使い手は利用者 1 人と pi |
| 構成 C | **別アプリ + git の ref + 薄い pi 拡張** |
| 状態の正本 | git の ref（`refs/pi/review/<prKey>`）。アプリが落ちても、pi は git だけで動ける |
| アプリ | 画面と入力。全リポジトリを 1 つのプロセスで扱う。置き場所は `apps/pr-viewer/`（chezmoi では配備しない） |
| pi 側 | 道具 `pr_summary`・`/pr`。置き場所は `home/dot_config/pi/harness/`（§9） |
| 実行器 | 統合の実行は**アプリ**（人がブラウザで押した「統合する」の POST。段 A2。§6「統合」・[CHG-0062](../change/0062-pr-hub-simplify.md)）。旧経路（窓口の pi の承認経路 `/pending approve`・`git_integrate`）は撤去済み（A5） |

### 段階

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | 読み取り専用のアプリ（一覧・概要・diff）。リポジトリの登録は起動引数 `--repo` | **実装済み**（develop に取り込み済み。配備は `chezmoi apply`） |
| 2 | コメント・スレッド・送信・stale 表示・ref ライブラリ（`review-log.ts`・`review-git.ts`）・自己検査 | コメント送信の部分は**撤去済み**（下の「レビューコメント送信の撤去」）。ref ライブラリ・自己検査・`GET …/review` は残る |
| 3 | pi の道具・`receipt`・注入・配送の 4 状態の表示 | 道具 `pr_summary` だけ残る。`pr_comments`・注入・配送は**撤去済み**（§9） |
| 4 | ペアリングと制御ポート | **取りやめ**（CHG-0062 で置き換え。実装しない。旧設計は削除済み） |
| 5 | 承認の指示。既定で無効 | **取りやめ**（CHG-0062 で、アプリの「統合する」へ置き換え。§6「統合」。旧設計は削除済み） |
| A2 | 統合 API（`merge-plan`・`merge`）と承認シートの画面（CHG-0062 の段 A2） | **実装済み**（S: サーバ・U: 画面・G: 判定器の拒否の 3 feature。develop に取り込み済み。有効化は `--allow-merge` を付けた起動と実機確認が要る） |

## 2 PR の同一性

| 項目 | 内容 |
| --- | --- |
| 対象 | `refs/heads/feature/*` と `refs/heads/bugfix/*` の 1 本 = 1 PR。**1 feature = 1 PR** |
| `prKey` | `p` + sha256(`"v1\0refs/heads/<branch>"`) の先頭 16 桁 |
| `repoId` | `r` + 正規化した common dir の sha256 の先頭 8 桁。アプリ内の PR の ID は `<repoId>/<prKey>` |
| 統合先（target） | `develop`、なければ `main`、なければ `master`。どれも無ければそのリポジトリは使えない |
| ref の作成 | 最初の書き込みで遅延作成。PR 一覧は、ブランチの ref と `refs/pi/review/*` の和集合 |
| 同名ブランチの再利用 | **v1 は非対応**。統合済み（`merge_result` が `success`）の PR への書き込みは断り、「ブランチ名を変える」と案内する |

## 3 ref のスキーマ v1

| 項目 | 内容 |
| --- | --- |
| ref 名 | `refs/pi/review/<prKey>` |
| commit の tree | `meta.json` と `events.jsonl` の 2 つの通常の blob だけ。余計なファイル・symlink・実行ビットは不正 |
| `meta.json` | schema 1（schema 2 は撤去した起票が作った ref だけ。下の「`brief`」）: `{"schema": 1, "pr": "<prKey>", "branch": "feature/x", "target": "develop", "createdAt": "<ISO>"}` |
| `events.jsonl` | 1 行 1 イベント。順序は行の順（`seq` は持たない） |

### イベント

共通の形: `{"v": 1, "id": "<uuid>", "t": "<種別>", "by": "app" または "pi", "at": "<ISO>", "vs": {"source": "<oid>", "target": "<oid>", "base": "<oid>"}, "d": {…}}`

| 項目 | 内容 |
| --- | --- |
| `by` | **表示用。信頼しない**。誰が書けるかの判定にも、レビュー状態の判定にも使わない |
| `t`（種別） | `comment`・`summary`・`submit`・`receipt`（`comment`・`submit`・`receipt` は撤去前の記録の読み取り互換のためだけに残す）・`merge_request`・`merge_started`・`merge_result`・`brief`（撤去した起票が書いた。schema 2 の ref だけ） |
| `vs` | そのイベントを書いた時点の source・target・base の OID（stale の判定に使う。§4） |

| 種別 | `d` の中身 |
| --- | --- |
| `comment`（読み取りのみ） | `{"thread", "anchor", "body"}`。撤去前の記録に残るもので、今は書かない・画面にも出さない |
| `summary` | `{"done", "files": […], "findings": [{"ref": "<comment id>", "reply"}], "notes", "mergeMessage"}`。中身は CHG-0060 の D1・D2 |
| `submit`・`receipt`（読み取りのみ） | 撤去前の記録に残るもの。今は書かない・画面にも出さない |
| `merge_request` | `{"requestId", "sourceRef", "sourceOid", "targetRef", "targetOid", "baseOid", "message", "cleanup"}`。`cleanup` は `branch_and_worktree` など |
| `merge_started` | `{"requestId", "pendingId"}`。旧経路で pi が書いていた（現行の統合はアプリが実行する。§6「統合」） |
| `brief` | `{requestId, rev, kind, name, title, goal, constraints, scope[], acceptance, via}`。起票（撤去済み。§6「起票の撤去」）が 1 コミットで記録した依頼文。`meta.schema` は 2。**古い読み手は schema 2 を「版が新しい」読み取り専用として扱う**（壊さず、書き込まない）。harness の読み取りは古い記録のために残してある |
| `merge_result` | `{"requestId", "outcome": "success" または "refused" または "failed" または "unknown", "reason", "doneOid"}` |

### 更新・検査・上限

| 項目 | 内容 |
| --- | --- |
| 更新（CAS） | `update-ref --no-deref <ref> <新> <旧>`（新規は旧 = 0）。失敗したら再読して `build(state)` をもう一度呼ぶ（最大 8 回）。`build` は前提条件を再評価する |
| イベントログの採用理由 | CAS に不可欠なわけではない。操作履歴を扱いやすいので採る（JSON の snapshot でも CAS 自体は成立する） |
| 到達可能性 | **最初の記録と、`vs.source` が変わったときの新しい source** を、その commit の追加の親にする（前の版は、その時点の commit が親として持つ）。追記を待たずに、最後にレビューした版も、ブランチ削除や rebase の後に gc されない |
| 上限 | 1 イベントの本文 16 KB・`events.jsonl` 512 KB・イベント 2000 件・PR 200 本 / リポジトリ |
| 終端記録の余裕 | **1900 件を超えたら、または `events.jsonl` の末尾 32 KB に入るときは、`receipt`・`merge_started`・`merge_result` 以外を断る**（件数とバイトの両方。上限近くまで通常のイベントで埋めても、受領の記録が書ける） |
| 自己検査 | **各 PR の初回アクセス時**（起動時の全件検査はしない）。下表 |
| 読み取り専用 | `meta.schema` が自分より新しければ読み取り専用にし、「更新が必要」と表示する |
| 不整合な PR | その PR だけ書き込みを断る（fail closed）。他の PR は動く。**修復はしない** |

自己検査の項目:

| 項目 |
| --- |
| tree がちょうど 2 つの通常 blob |
| サイズが上限内 |
| `prKey == hash(meta.branch)` |
| id の重複なし |
| JSON として正しく、`t` が既知（撤去前の `comment`・`submit`・`receipt` も既知として読む） |

## 4 状態の導出

状態は ref の中身から導く。保存はしない。

| 対象 | 状態 | 導出 |
| --- | --- | --- |
| サマリー | 古い版 | `summary` の `vs` が現在の source・**target・base** のどれかと違う（`summaryStale`） |
| 統合 | 承認待ち → 実行中 → 完了 | `merge_request` → `merge_started` → `merge_result` |

- 統合の許可は、アプリの「統合する」の POST（§6「統合」）だけから得る。`by` や ref のイベントからは得ない。
- 撤去前の記録にある `comment`・`submit`（変更依頼・承認）は、読めるが状態の導出にも統合の判定にも使わない。
- 結果の状態（成功・拒否・失敗・不明）は、既存の `ExecutionResult` の `saved`・`kept`・`termination` から決め、`outcome` からの推測はしない。

## 5 レビューコメント送信の撤去（2026-11-05）

画面でのレビューコメントの送信と、pi への配送（注入・受領）を**撤去した**。旧 §5「配送」の設計は git の履歴にある。

- 理由: 実使用の証拠が無かった（`refs/pi/review/*` に `comment` のイベントが 0 件）。依頼はチャットで行う。
- 撤去した範囲: 画面の送信バー・シート・キュー・行コメント・PR 全体コメント、`POST …/comments`・`POST …/submit`（POST すると 405）、道具 `pr_comments`、`before_agent_start` の注入と受領、diff 応答の `oldBlob`・`newBlob`、統合の計画の `warnings`。
- 残したもの: `pr_summary`（`guarded_pr_summary`）・サマリー表示・統合ボタンと `recordMerge`・一覧・差分の閲覧（閲覧専用）・`GET …/review`（`summary`・`merged`・`readonly`・`bad`）・`reviewHints`。
- 読み取り互換: 撤去前の `comment`・`submit`・`receipt` のイベントを持つ記録も、壊さず読める（警告にも拒否にもしない）。書くことはしない。

## 6 アプリ

### 起動とポート

| 項目 | 内容 |
| --- | --- |
| 起動 | **v1 は利用者が起動する**（`pis` の Fence の内側からは届かない見込み）。`node apps/pr-viewer/server.ts --repo <パス> [--port <N>] [--allow-host <名前>] [--allow-merge]`（既定のポートは 8780。tailnet の名前（`*.ts.net`）の Host は既定で許可。`--allow-merge` は統合を許可する（既定で無効。下の「統合」））。`/pr start` は案内だけ。ビルドは不要 |
| UI ポート | `127.0.0.1` で待ち受ける。認証なし（遠隔の通信路は tailnet が保証する決定） |
| 起動の道具 | **正本は `scripts/pr_app.py`**（`serve`・`install`・`uninstall`・`restart`・`status`・`logs`・`expose`・`unexpose`。試験は `test/test_pr_app.py`）。設定 `~/.config/pr-viewer/env` の権限の旗（`PRAPP_ALLOW_MERGE`）は**新規作成時にすべて `0`**、既存の設定は上書きしない。起動元はこのスクリプトのあるチェックアウト（`PRAPP_ROOT` で上書き）で、`apps/pr-viewer/server.ts` が無ければ停止する（別の worktree へは切り替えない）。**linked worktree からの `install` は終了コード 2 で拒否する**（unit が worktree の絶対パスに固定され、掃除後に Restart のループになるため。`serve` は影響しない）。常駐は systemd の user ユニット（Linux のみ）、公開は `tailscale serve` だけ（Funnel は使わない）。`PRAPP_DRY_RUN=1` で表示だけ |
| bind | `localhost` や `0.0.0.0` にしない。どちらか一方でも bind に失敗したら、両方閉じて終了する（bind が排他。lock ファイルは要らない） |
| 依存 | `node:http` だけ。npm の依存なし |
| import 境界 | `pending-*.ts`・`integrate-*.ts`・`exclusive-lock.ts`・`native-action.ts`・`board-collect.ts` を import しない（試験で固定）。統合器 `merge.ts` は HTTP 側では `merge-api.ts` からだけ使う（`merge-cli.ts` は別）。`merge-api.ts` は harness を import せず、git を直接動かさない |
| アプリ内の git | 専用の実行器 `git-view.ts`。`review-git.ts` は git の実行を**注入**で受け、`worktree.ts` を import しない（アプリも pi も同じライブラリを使えるようにする） |

### API 契約の要約（段 1）

| 項目 | 内容 |
| --- | --- |
| 方式 | GET だけ（副作用なし）。応答は JSON・`Cache-Control: no-store`。エラーは `{"error": {"code", "message"}}`（メッセージにパスや内部の例外を含めない） |
| エンドポイント | `/api/repos`・`/api/prs`・`/api/prs/<repoId>/<prKey>`（概要・コミット・ファイル）・`/api/prs/<repoId>/<prKey>/diff?path=<p>` |
| 一覧に出す PR | `feature/*`・`bugfix/*` の枝のうち、**差分が無く（0 コミット。統合先と同じか祖先）、レビューの記録（`refs/pi/review/<prKey>`）も無い枝は出さない**（統合済みで枝だけ残っているもの。中身が空で PR とは言えない）。記録があれば「統合済み」として出る。記録の有無を読めなかったときは隠さない。一覧に出さないだけで、ID を直接指定すれば詳細は読める |
| 含まれる枝 | open な PR の枝の先頭が、別の open な PR の枝の先頭の祖先（別のコミット）なら、前者に `includedIn`（含む枝の名前）を付け、**一覧では既定で隠す**（統合用の枝 `feature/bundle-N` の構成員を並べないため。表示だけで、切り替え「含まれる枝も表示（N 件）」で出る。選択は `localStorage`）。ID を直接指定すれば従来どおり読める・操作できる。git が失敗したときは付けない（隠さない側）。詳細応答（`/api/prs/<repoId>/<prKey>`）の `pr` にも付く（概要画面は全件を計算しない）。一覧は 1 本の PR の git 失敗で全滅させず、読めなかった PR を `errors: [{repoName, branch, reason}]`（短い理由。絶対パスは伏せる）で返し、画面が警告を出す。統合・判定・権限には使わない |
| 統合先の進み・両側の変更・未 push（A3。読み取りだけ） | `PrSummary` に `behind`（分岐点から統合先が進んだコミット数。`rev-list --count <base>..<target>`）と `overlap`（`{count, paths, truncated}`。`behind > 0` のときだけ、`diff --name-only -z <base> <target>` と PR 側の変更ファイル（改名は旧パスも）の積集合。パスは最大 20 件。統合先側の変更が 2000 件を超えたら `paths: []`・`truncated: true` で「多数」）を足した。`/api/repos` の各要素に `unpushed`（統合先の枝が `<target>@{upstream}`、なければ `refs/remotes/origin/<target>` より先にある件数。上流が読めないときは `null`）を足した（どれも既存の項目は変えない後方互換の追加）。**`overlap` は衝突の目安であって判定ではない**（可否は統合の確認画面が `merge-tree` で出す）。`unpushed` は `fetch` をしない「最後に取得した状態との比較」 |
| 上限 | diff 全体 2 MB・1 ファイル 200 KB・ファイル一覧 400 件・コミット一覧 200 件・1 回の git は 10 秒 / 出力 4 MB。超えたら省略表示か 500 |
| 配信 | `/` と `/web/<名前>` は、許可リストにあるファイル（`index.html`・`app.css`・`*.js`）だけ。ディレクトリの走査は許さない |
| 書き込み系 | `POST …/merge-plan`・`POST …/merge` だけ（§6「統合」）。コメント・送信の POST は撤去した（405）。`Content-Type: application/json` と独自ヘッダー `X-PRV: 1`、`Origin` を要する。本文は 64 KB まで（chunked でも実測で打ち切る）。レビュー状態の読み出しは `GET …/review`（副作用なし。ref が無い PR でも書かない。`summary`・`merged`・`readonly`・`bad` を返す） |
| 書き込みの git | 読み取りと同じ安全な実行器の上に、**許可リストだけ**を通す入口を持つ（`hash-object -w --stdin`・`mktree`・`commit-tree`・`update-ref --no-deref`。対象の ref は `refs/pi/review/p<16 桁>` だけ。先頭の `-c` は作者設定 3 つだけ）。残りの読み取り系も同じ許可リストで絞る |

### 描画と git の安全規則

画面（A3）: 一覧の開いた PR に「develop が N 進んだ」、一覧の上部にリポジトリごとの「origin（最後に取得した状態）より N 件先」（0・`null` は出さない）、PR 概要の先頭に「衝突の可能性: N 件」（開くとパス一覧。多すぎるときは「多数」）を出す。パスは `textContent` だけで出す。

| 項目 | 規則 |
| --- | --- |
| 描画 | 生の文字列は `textContent` のみ。`innerHTML`・`insertAdjacentHTML`・`eval` を使わない。本文の markdown は `web/markdown.js` が `createElement` と `textContent` だけで描く（下の「markdown の描画」） |
| CSP 等 | `default-src 'self'`・外部画像なし・`frame-ancestors 'none'`・`nosniff`・`Referrer-Policy: no-referrer` |
| git の実行 | 固定の argv・`shell:false`・hook / fsmonitor / 外部 diff / textconv / 外部 filter を止める設定・`--no-ext-diff --no-textconv --no-pager`・出力量と時間の上限。**自動の fetch も止める**（`GIT_NO_LAZY_FETCH=1`・`GIT_ALLOW_PROTOCOL=` を固定。partial clone で足りないオブジェクトを読むと git が ssh などを起動するため。足りないときは取得せずエラーにする） |
| 入力 | ref は `for-each-ref` の出力にあるものだけ。OID は 40（または 64）桁の 16 進だけ。パスは `--` の後か `<oid>:<path>` でだけ渡し、ref 内のパスをファイルシステムのパスとして使わない |
| 登録 | 登録されたリポジトリ（正規化した common dir）だけを扱う |

### markdown の描画

`web/markdown.js`（`PRV.md(text)`）。「pi のまとめ」・依頼文の表示に使う。統合コミットのメッセージ（確認画面）・ログ・編集用の `textarea` は生の文字のまま。

- 対応: 段落・改行（`<br>`）・見出し（`#`〜`###`）・箇条書き（順序なし/あり。入れ子は 2 段まで）・引用（入れ子 2 段まで）・水平線・コードブロック（言語名は無視）・インラインコード・太字・斜体・リンク・表（GFM の簡単なもの。横にはみ出すときは横スクロール）
- 安全: 要素は `createElement`、文字は `textContent` / テキストノードだけ。生の HTML は文字として出す。リンクは `http:`・`https:` と同一ページ内の `#` だけ許可し（`rel="noopener noreferrer"`・`target="_blank"`）、ほかは書いたままの文字で出す。画像 `![alt](url)` は描画せず `[画像: alt]` の文字にする
- 上限: 全体 2 万文字・300 行・1 行 2,000 文字（超えた行は書式なし）・太字等の入れ子 3 段。超えた残りは書式なしの `<pre>` で出し、描画器が重くならない

### Host の検査と公開

| 項目 | 内容 |
| --- | --- |
| Host の検査 | loopback（`127.0.0.1`・`localhost`）と、tailnet の名前（`*.ts.net`）と、`--allow-host` で足した名前だけ。ほかは 403（tailnet の名前はリポジトリに書かない。DNS rebinding は攻撃者のドメインが `*.ts.net` でないことで防ぐ） |
| tailnet への公開 | `tailscale serve` で HTTPS の 1 つの URL に公開する（手動の設定）。**公開範囲（tailnet の内側だけか）は未確認**。公開インターネットへ出す設定（funnel など）にしない |

### 統合（段 A2。[CHG-0062](../change/0062-pr-hub-simplify.md) §3.5）

人がブラウザで押した「統合する」の POST で、**アプリが develop へ merge commit で同期統合する**（統合器 `merge.ts`。詳細は CHG-0062 §3.5）。統合の権限は**この POST だけ**で、ref に書かれた「承認」・保留・`merge_request` は権限として読まない（Fence 内のエージェントも共有 `.git` の ref を書けるので、偽造できる。反例の試験で固定）。

| 項目 | 内容 |
| --- | --- |
| 経路 | `GET /api/capabilities`（`{merge, targets}`。パスを含めない）・`POST /api/prs/<repoId>/<prKey>/merge-plan`（承認シート用の計画。副作用は git の object の書き込みだけ。GET でないのは、`merge-tree --write-tree` が object を書くため）・`POST …/merge`（実行）。`recover` は HTTP に出さない（他の git が動いていないことを人が確かめる手順があるため。画面は CLI の手順を案内する） |
| 入口の検査（merge-plan・merge） | (1) `--allow-merge` が無ければ 403 `merge_disabled`（**既定で無効**。起動の旗で値を取らない） (2) `Tailscale-Funnel-Request` ヘッダーがあれば 403 `forbidden_funnel` (3) **Origin 必須**（無し・`null`・別ホスト・形の悪い値は 403 `forbidden_origin`。host を Host ヘッダーと照合） (4) `X-PRV: 1` と `application/json`（無ければ 400） (5) 本文は上限 64 KB・未知のキーは 400。OPTIONS は 405 で CORS ヘッダーを返さない |
| 実行の入力 | `expect: {source, target}`（2 キー必須・40 桁の 16 進。違えば 409 `stale_view`）・`message`（1〜4000 文字・改行は `\n` にそろえる・1 行目が空白だけは不可・制御文字と双方向制御文字と孤立サロゲートは不可）・`cleanup`（`none`·`branch`·`branch_and_worktree`。既定 `none`） |
| 後始末（`branch_and_worktree`） | [worktree の掃除の規則](orchestration.md#worktree-の掃除の規則)と同じ。統合元が統合済みで、追跡ファイルの変更・未追跡（無視されないもの）・確かめられない設定（`filter`・hooks など）が無ければ、**無視ファイル（`__pycache__`・`node_modules` など）ごと** worktree を削除する（`--force` は使わない。status が空と確かめた後だけ削除する）。削除前に無視ファイルを `<--state-dir>/cleanup-backups/<名前>-<時刻>.tgz` へ退避する（CLI 単体は `<共通 git-dir>/pi-cleanup-backups/`。上限 200 MB・5 件。超える・失敗なら worktree を残して警告）。有効な owner の lock・人が付けた lock・残骸の lock があれば残す（残骸は解除せず、警告で `wt_owner.py reap` を案内する）。枝は、worktree が無くなった後に CAS つきで消す（所有の `claim`・`release`・`reap` は、git の `worktree lock` が非原子のため、共通ディレクトリのガードファイルで排他にしている。[所有の表明](orchestration.md#worktree-の所有の表明)） |
| 応答 | 成功 200 `{merge: {commit, targetOld, targetNew, cleanup, warnings, recorded}}`。統合器の拒否コードをそのまま HTTP に写す（`conflict` は `conflicts` を添える。`dirty`・`ignored` は原因のパス `details: {paths（最大 20 件）, pathCount}` を、`operation_in_progress`（進行中の merge・rebase・cherry-pick など。`details.op` に名前）・`index_locked`（git の `index.lock` がある。統合は実行されていない）は別のコードで返す。`head_mismatch` の文言に今の枝名を入れる。merge-plan の `refusal` も同じ `details` を持つ。`recover_needed`・`busy` も 409。`failed` は 500 `merge_failed`）。生の git 出力・絶対パスを返さない。詳細な契約は試験 `test_pr_viewer_merge_api.py` と U の画面 |
| 計画（merge-plan） | `mergeable`・`refusal`・`blockers`（常に `[]`。API の形と `web/merge.js` の `legacy_` の処理は残す）・`plan`（統合元・統合先の先頭・コミット数・ファイル一覧 200 件・+/−・リスクのあるパス 50 件・`riskConfig`・`touchesApp`）・`defaults`（メッセージ・`messageSource`・`summaryStale`）。リスクの判定は表示上限ではなく**全件の変更パス**に対して行う。リスク設定（`~/.config/pi/harness/rules.json` の `judge.common.pi.integrate.risk_paths`。`--rules-file` で差し替え）を読めないときは `riskConfig: "unavailable"`（「リスクなし」と混同しない）。`touchesApp`（`apps/pr-viewer/**` に触れるか）は設定と独立。既定メッセージは、レビュー記録の下書き（検査を通るものだけ。古い版なら `summaryStale`）、無ければ枝の最新コミットの件名を使う生成文 |
| 記録（表示用） | 成功だけ、`merge_request` と `merge_result` を 1 回の追記で書く（`merge_result` は先行する request が要る）。書けなかっても統合の成功は取り消さず `recorded: false`。記録は権限の根拠にしない。診断ログは標準エラーに 1 行の JSON（要求 ID・PR・結果・統合後の OID・記録の成否。本文・ヘッダー・パスは出さない） |
| 同時実行・停止 | リポジトリ単位の「待たない」排他（取れなければ 409 `busy`。plan も同じ）と、統合器のロックファイル（別プロセスとの排他）。SIGTERM・SIGINT は**実行中の統合を、結果の記録と応答を終えるまで待つ**（一律の強制終了は設けない。強制するなら SIGKILL と `recover`）。通信が切れても統合は最後まで続く |
| plan の負荷 | plan は同じリポジトリで直列化するだけ（連打抑止・結果の再利用はしない）。同じ内容の object は同じ OID になるので無制限には増えないが、再計算の CPU と git の起動は毎回かかる。到達できるクライアントは資源を使える（認証を入れない方針の帰結） |
| 旧経路の残骸（`/pending`） | 旧経路は撤去済み。共存の確認（409 `legacy_*`）も撤去し、`refs/pi/{lock,running,pending}/*` の残骸は統合を妨げない（掃除は `pk pending-clean`。[履歴](guard/pi-pending.md)） |

#### 止められるもの・止められないもの（正直に）

| 攻撃・状況 | 止まるか | 何で |
| --- | --- | --- |
| 他サイトからの CSRF（fetch・form） | 止まる | 非 simple なヘッダーで preflight になり、OPTIONS は 405。form は `X-PRV`・JSON を付けられない。Origin 必須 |
| DNS rebinding | 止まる | Host の許可リスト |
| Funnel（公開）経由 | 止まる（二次情報に基づく） | `Tailscale-Funnel-Request` ヘッダー。Funnel 経由のみ付き、Serve はクライアントの送った同名ヘッダーを消すという第三者の記述が 2 件（2026-11-03 に検索。公式の kb/1312 は取得できず未確認）。**起動後の公開設定の変更は防げない**。Funnel を使う領域で `--allow-merge` を併用しない |
| tailnet 内の他の機器・同一端末の他プロセス | **止まらない** | Origin と `X-PRV` はヘッダーを偏造できるクライアントを止めない。認証（合言葉）は入れない（「追加認証は過剰・通信路は tailnet が保証」の方針）。`--allow-merge` を付けると、到達できるクライアントは統合できる |
| Fence 内のエージェント | loopback は届かない（実測）。tailnet 名は未確定 | 判定器の拒否（`X-PRV` 付きの curl・`merge-cli.ts merge\|recover`）。任意コードは止めない（うっかり防止の水準） |
| 統合によるアプリ自身の変更 | 見える | `apps/pr-viewer/**` は `risk_paths`。変更を統合しても、再起動するまでサーバのコードと配信するファイル（要求ごとにディスクから読む）の版が混在する。起動元は信頃できる作業ツリーに限る |

#### 有効化の手順（利用者が行う。取り込みだけでは有効にならない）

1. 判定器の拒否（G）とサーバ・画面（S・U）を develop に取り込む。
2. **更新時の必須条件**: 旧経路への新規要求を止め、全旧 pi セッションと統合用 git プロセスの終了を確認する。その後に `chezmoi apply`（`rules.json` を生成し直す）・pi / pis の起動・PR ビューアの起動を行う。停止を確認できない間は、更新後のアプリを `--allow-merge` 付きで起動しない。残骸 ref の存在だけでは、停止済みとは判定しない（ファイルを削除しても、すでに動いている旧 pi・統合処理は止まらず、旧経路と新経路は別のロックを使うので排他できない）。
3. 配備先で、判定器が `X-PRV` 付きの curl と `merge-cli.ts merge` を deny することを確かめる。tailnet や funnel で公開するなら、`~/.config/agents/local.toml` の `[pis.network] deny` に自分の公開名を足し、Fence の内側から届かないことを確かめる（上流プロキシが名前解決する経路では、中継が内部アドレスを止められない: [pi-sandbox](guard/pi-sandbox.md)）。
4. `--allow-merge` を付けてアプリを起動し、安全な試験用リポジトリで統合を 1 回試す。異常終了の後は CHG-0062 §3.5 の手順で `recover` する。

#### 統合を取り消す（巻き戻し。利用者が行う。手順は試験 `test_pr_viewer_merge_undo.py` が実 git で固定）

統合は merge commit を develop の先頭へ進めるだけなので、**履歴は復元できる**（手元の作業の保存は下の手順の前提しだい）。戻す先は次で分かる: 統合の応答の `merge.targetOld`（統合前の develop）と `merge.commit`（統合コミット）、画面の「旧 → 新」の OID、レビュー記録の `merge_request.targetOid`（= `targetOld`）と `merge_result.doneOid`（= `commit`）、`git reflog show develop`（作業ツリーありのリポジトリ。bare は reflog が無いので、応答の OID を控える）。まず `git rev-parse <commit>^1` が `targetOld` に等しいことを確かめる。

| 状況 | 手順 |
| --- | --- |
| 未 push と分かっていて（一覧の「origin より N 件先」は最後に取得した状態との比較で、**未 push の目安であって証拠ではない**。公開済みか不明なら下の revert を選ぶ）、統合の後に develop へ他のコミットが無い・develop を checkout している | 前提: **index に未コミットの変更が無い**（`git diff --cached --quiet`。`reset --keep` は worktree の変更は残すが **index の変更は保存しない**。stage 済みがあれば先にコミットか退避する）。`git status` で、統合を戻すと上書きされるファイルに手元の変更が無いことを確かめ、`git reset --keep <targetOld>`。`--hard` ではなく `--keep` を使う（重なると何も変えず中止する）。無関係な未コミットの worktree の作業・未追跡・無視ファイルは残る |
| 同じで、develop をどの worktree も checkout していない | `git update-ref refs/heads/develop <targetOld> <統合コミット>`。末尾の期待値を必ず付ける（統合のあとに develop が進んでいれば、期待値が合わず何も変えない） |
| push 済み・公開済みか不明、または統合の後に他のコミットがある | 履歴を巻き戻さず、**develop を checkout している worktree で** `git revert -m 1 <統合コミット>`（第 1 親 = develop 側を残す。別の枝で実行するとその枝に取り消しができ、develop は戻らない）。**統合が導入した変更だけ**を取り消す新しいコミットができる。後続の変更は残り、重なると衝突しうる。**同じ枝をもう一度統合したいときは、その revert コミットを revert してから**でないと、変更が入らない（git の仕様） |
| cleanup で枝を消した | `git branch <枝> <統合コミット>^2`（第 2 親 = feature の先頭）。worktree は `git worktree add <パス> <枝>` で作り直す。**削除された worktree の中の未追跡ファイルは戻らない。無視ファイルは、上の退避の tgz から戻せる** |

これは利用者が自分の端末で行う手順で、エージェント（pi）に任せることは想定しない。復旧できない異常終了（状態ファイルが残った）は、取り消しではなく `recover`（CHG-0062 §3.5）。統合の結果を確認できなかった（`unverified`）ときも `recover` が「統合済み」と確かめて状態を解除する。

`recover` は、`<git-dir>` 直下と `refs/` 配下（深さ 4 まで）の `*.lock`（`ORIG_HEAD.lock` など）が残っていれば、`details.staleLocks: [{path, ageSec}]` と案内の `message` を**追加で**返す（git-dir と共通ディレクトリの両方。`state`・終了コードは変えない）。
統合が `failed` で終わるときは、git の標準エラーの先頭 300 字（制御文字を除去・URL の資格情報は伏字）を、CLI の `details.git` と理由の「（git: …）」に足す（HTTP へは出さない）。
ロックは**自動では消さない**: 持ち主の git が生きているかの判断を誤ると、実行中の git を壊すため。持ち主がいないことを人が確かめて、手で削除する。

### ジョブ（段 A4a。撤去済み）

画面の「変更を依頼」（feature の worktree で `pis -p` を起動し、結果を検査してアプリが commit する機能。`--allow-jobs`・`job-*.ts`・`web/job.js`）は**撤去した**。
実運用で 1 度も使わず、依頼はチャットで足りるため。
設計の経緯は [CHG-0062](../change/0062-pr-hub-simplify.md) §3.4 と git の履歴にある。`--allow-jobs` は無くなり、`PRAPP_ALLOW_JOBS` も無視される。
`GET /api/capabilities` に `jobs`・`jobsReason`・`jobLimits` は無い。統合の `merge-plan`・`merge` に、ジョブとの排他（`job_running`）は無い。

### 稼働版の固定（常駐サービスの版を、利用者が指定するまで動かさない）

常駐のビューアは、統合で `develop` が進んでも、**起動した時点の版のまま**動く。以前は本体のチェックアウトから直接動かしていたため、サーバのコードは起動時の版・`web/` の静的ファイルはリクエストごとの最新、と食い違いえた。

| 項目 | 内容 |
| --- | --- |
| 仕組み | `pr_app.py serve --pinned`（systemd ユニットが使う）は、本体の `develop` の先頭を `git archive` で `.tmp/pr-app/current/` へ書き出し、**そこから** `server.ts` を動かす。書き出す範囲は `apps/pr-viewer` と `home/dot_config/pi/harness` だけ。`git worktree` は作らない（本体の worktree 一覧・統合の判定・宛先一覧に混ざるため）。統合の対象リポジトリは本体のまま |
| 記録 | `current/PINNED.json`（`oid`・`ref`・`pinnedAt`）。起動ログにも OID を出す |
| 表示 | `GET /api/version`（`{pinned, oid, ref, pinnedAt}`）。画面の隅に `web/ver.js` が OID の先頭 8 桁を出す（固定なしなら「固定なし」）。取れなければ何も出さない |
| 更新 | `pr_app.py restart` だけが版を替える。流れ: `develop` の先頭を `current.new` へ書き出す → 成功したら `stop` → `current` へ入れ替え → `start`。**書き出しに失敗したら、稼働中の版は止めない**。クラッシュ後の自動再起動では版は変わらない。`current` が壊れていれば `serve --pinned` が作り直す |
| 旧形式のユニット | `--pinned` を持たない旧ユニットは稼働版を使わない。本体のチェックアウトで `pr_app.py install` をやり直す（`restart` が警告する） |
| 保証の範囲 | 固定するのは `apps/pr-viewer` と `home/dot_config/pi/harness` の版だけ。Node・git・OS の版、本体にある設定ファイルの値は固定しない。`PINNED.json` の改ざんは検出しない（利用者の端末内の前提） |
| 未対応 | **Windows と、`git worktree` が使えない環境は未対応**（systemd 前提。Windows は未検証） |

#### 既知の制限（稼働版の固定）

- 固定の対象は `develop` の先頭だけ。別の枝の版は動かせない。
- `restart` の間（数秒）は応答しない。

### 起票の撤去（[CHG-0062](../change/0062-pr-hub-simplify.md) 段 B1）

- 画面の「＋ 起票」と、その書き込み API（`POST /api/repos/<repoId>/features`・旗 `--allow-create`・`PRAPP_ALLOW_CREATE`）を**撤去した**。実使用の証拠が 0 件だった（このリポジトリのレビュー記録に brief の保存履歴が無い）。
- 起票は常にチャット（親の `git flow feature start` + `wt_owner.py claim` + worker）で行う。積み重ね・claim・担当外検査が使えるため、画面の起票より上回る。
- 消したもの: `feature-api.ts`・`feature-create.ts`・`brief.ts`・`brief-cli.ts`・`web/create.js`、`/api/capabilities` の `create`、`/api/repos` の `targetOid`、`GET …/review` の `brief`、一覧の `state: "empty"`（起票のみ）、試験用の旗 `--create-test-*`。
- 残したもの: harness（`review-log.ts`・`review-git.ts`）の brief スキーマの読み取り（古い記録を壊さないため。別 feature で後続撤去）。と `worktree-owner.ts` の `readOwner`（統合が使う）。
- 履歴を見るときは git の履歴。設計の本文は撤去前のコミット（`feat(pr-viewer)` の起票追加）にある。

## 7・8（欠番）

ペアリングと制御ポート（旧 §7）・承認の指示（旧 §8）は、[CHG-0062](../change/0062-pr-hub-simplify.md) で「実装しない」と決めた旧設計なので削除した（本文は git の履歴にある）。
統合はアプリの「統合する」（§6「統合」）。節番号は他の文書からの参照を保つため詰めない。

## 9 pi 側

| 項目 | 内容 |
| --- | --- |
| 道具 `pr_summary` | 完了サマリーの投稿（`summary` を追記）。`mergeMessage` の下書きを任意で持つ。この道具だけが残る |
| 撤去したもの | 道具 `pr_comments`（`guarded_pr_comments`）・`before_agent_start` の注入・受領の記録（§5） |
| `/pr` | `url`・`start`。`start` は案内だけ（`pair`・`unpair` は取りやめ） |
| アプリ不在 | 道具は ref だけで動く。制御の呼び出しは短い timeout で黙って失敗し、`/pr` は「アプリ未接続」と出す |
| 置き場所 | `home/dot_config/pi/harness/`（`review-log.ts`・`review-git.ts`・`pr-review.ts`・`pr-control.ts`）。`index.ts` から短く呼ぶ |
| 役割 | 道具名を `[pi.profiles.*]` の道具リストに足す（実装役 `implementer` に足した。子の worker には足さない）。**注入は親だけ** |
| 判定器 | `pr_summary` には許可規則をまだ足していない（役割の既定で確認になり、bypass では確認なし）。有効化の判断のときに、`decide.py`・`decide.ts`・golden に足す（未決） |
| 薄さ | pi は HTTP サーバを持たない。制御の失敗で pi を止めない |

## 10 守る条件との対応

条件の定義は [CHG-0060 §6](../change/0060-local-pr-viewer.md)。

> 注: C1・C8・C11・C15 の「窓口の pi が保留を作る・ペア・制御ポート」は旧経路の設計で、置き換え済み（CHG-0062）。現行の統合は人の POST でアプリが行う（§6「統合」）。ここは当時の条件の記録として残す（C1・C15 の節の参照先は削除済み）。

| # | 満たす設計要素 | 確かめる試験 | 限界 |
| --- | --- | --- | --- |
| C1 | （旧）アプリは指示を送るだけ。保留の作成も実行も窓口の pi。現行は人の POST でアプリが統合する（§6「統合」） | アプリの import 検査 | 旧経路は撤去済み |
| C2 | ref が正本。道具は ref だけを読み書きする | アプリを止めた状態で道具が動く | — |
| C3 | （撤去）`pr_comments list` が送信済みの項目だけを返す条件は、コメント送信の撤去で対象が無くなった | — | — |
| C4 | `127.0.0.1` を明示して bind。tailnet へは serve | `server.address()` の検査 | serve の設定の誤り（funnel など）は検知できない。手動 |
| C5・C14 | `textContent` のみ・CSP。本文の markdown は安全な描画器で描く | `innerHTML` 等の静的検査 | プロンプト注入の完全な防止は保証しない |
| C6 | 自作。依存なし | 機械では確かめられない | 複写していないことは review で見る |
| C7 | pi は ref だけで動く。制御の失敗は握りつぶす | app 停止時の独立動作・終了処理・import 境界 | 行数の固定試験は置かない |
| C8 | アプリが書くのは `refs/pi/review/*` だけ。保留は窓口の pi が作る | アプリの import 検査 | — |
| C9 | 登録された repo だけ。専用の git 実行器。ref 内のパスを使わない | 悪意ある設定（fsmonitor・hook・textconv 等）の陰性試験 | git の未知の起動経路は防げない |
| C10 | 遠隔は tailnet に任せる。GET は副作用なし。書き込みは独自ヘッダー・Host・Origin の検査 | 全 GET の副作用検査 | ルート表にあるものだけ。**UI ポートは認証なし**（§12） |
| C11 | （撤去）`submit` の不変・原子性・再送・宛先の条件は、配送の撤去で対象が無くなった | — | — |
| C12 | 全イベントに `vs`。サマリーの stale は source・target・base | 状態導出の試験 | 行番号の再対応づけはしない |
| C13 | CAS・`--no-deref`・再読して再適用・上限・終端記録の余裕・追加の親 | CAS・競合・上限・gc 後の到達可能性 | **保持期限と圧縮は v1 で未実装**（上限で止まる） |
| C15 | （旧）`/pr pair` は TUI コマンド。取りやめ（ペアリングは実装しない） | — | — |

## 11 試験

| 段 | 要点 |
| --- | --- |
| 1 | `server.address()` が `127.0.0.1`。全 GET の前後で状態が変わらない。悪意ある設定を仕込んだ repo で標識ファイルを作らない。入力の検査。`innerHTML` 等が無い |
| 2 | 4 プロセスの同時追記で欠落・重複が無い。期待 OID の不一致で失敗。symbolic ref に差し替えても通常のブランチを巻き込まない。上限超過で断る。自己検査の各項目で、その PR だけが書き込み拒否になる。stale。`by` を使わない状態導出。撤去前の `comment`・`submit` を持つ記録が読める（互換） |
| 3 | `pr_summary` の試験（`test_pi_pr_review.py`）。ブランチ削除と `gc --prune=now` の後も古い source が残る。コメント送信・注入の試験は撤去した |
| A2 | 統合 API（`test_pr_viewer_merge_api.py`）: 偊の approve / merge_request / 保留を ref に置いても統合されない（同じ fixture で正規の POST が通る対照つき）。`--allow-merge` 無し・Origin 無し / `null` / 別ホスト・Funnel ヘッダー・`X-PRV` 無し・expect の不正とすれ・メッセージと cleanup の不正・旧経路の残骸の保留・ロック・running があっても統合を妨げない・同時 2 要求・衝突・dirty・recover_needed で ref と作業ツリーが動かない。merge-plan の無副作用・リスクの全件判定・SIGTERM で実行中の統合を待つ・通信断でも統合が続く。import 境界（`merge-api.ts` が git を直接動かさない・承認状態を読まない） |
| A4a | ジョブ（撤去済み。試験・`fake_pis.py` も削除した）。稼働版の固定は `test/test_pr_app.py`（`serve --pinned`・書き出し・入れ替え・失敗時に止めない）で見る（`/api/version` と `ver.js` の個別の試験は無い。`ver.js` は規則の試験の対象だけ） |
| 共通 | アプリが `pending-*.ts` などを import しない。新しい試験は `scripts/verify.py` に登録する |

## 12 既知の制限と未確認

| 項目 | 内容 |
| --- | --- |
| 実機でしか確かめられないもの | Windows（path・待ち受け）・tailnet の公開範囲・`/reload` 後に保持した `ctx` が有効か |
| feature の worktree からの書き込み | `refs/pi/review/*` を feature の worktree の `pis` から書けるか（`refs/pi/pending` は確認済み） |
| C13 | 保持期限と圧縮は v1 で未実装。上限で止まる |
| UI ポートは認証なし | tailnet が保証する決定。統合（`--allow-merge`）を有効にすると、到達できるクライアントは統合できる（§6 統合の表）。素の `pi`（Fence なし）では、モデルが変更系の API を直接呼べる（判定器の拒否はうっかり防止の水準） |
| ジョブ（段 A4a） | **撤去済み**（実運用で 1 度も使わなかった）。§6「ジョブ」を参照 |
| ブランチ削除後 | PR の一覧・詳細は、生きているブランチの ref から作る。ブランチを消した PR は画面から見えない（review ref と最後の source は残る。§2 の「branch と review ref の和集合」は**未実装**。独立 review の指摘 M6） |
| 画面からの「再送」 | **撤去済み**（§5） |
| 行の再対応づけ | しない。outdated は blob の比較だけ |
| ref の同期 | 通常の clone / push では同期されない（`refs/pi/review/*`）。バックアップするなら ref を明示して push する（例: `git push <remote> 'refs/pi/review/*:refs/pi/review/*'`）。**自動では保存されない**。mirror で流出しうる。削除は即時消去ではない（未決。CHG-0060 §7） |

## 13 関連

- [CHG-0060](../change/0060-local-pr-viewer.md)（案件）
- [CHG-0055](../change/closed/0055-async-approval.md)（非同期承認）
- [保留（撤去済み・履歴）](guard/pi-pending.md)
- [pis のサンドボックス（pi の側）](guard/pi-sandbox.md)
