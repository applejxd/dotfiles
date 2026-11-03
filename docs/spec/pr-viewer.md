# ローカル PR ビューアの設計

GitHub をリモートに持たない開発で、PR 風のレビュー画面（Web）と pi を往復させる仕組みの設計。
案件と経緯は [CHG-0060](../change/0060-local-pr-viewer.md)。**設計は 2026-11-03 に確定。実装は段階的で、未実装の段は各節に「未実装」と書く。**

## 1 概要と状態

| 項目 | 内容 |
| --- | --- |
| 目的 | リモートが無くても、差分とコメントを PR のように読み書きし、pi と速く往復する。使い手は利用者 1 人と pi |
| 構成 C | **別アプリ + git の ref + 薄い pi 拡張** |
| 状態の正本 | git の ref（`refs/pi/review/<prKey>`）。アプリが落ちても、pi は git だけで動ける |
| アプリ | 画面と入力。全リポジトリを 1 つのプロセスで扱う。置き場所は `apps/pr-viewer/`（chezmoi では配備しない） |
| pi 側 | 道具・注入・`/pr`。置き場所は `home/dot_config/pi/harness/`（§9） |
| 実行器 | 統合の実行は**アプリ**（人がブラウザで押した「統合する」の POST。段 A2。§6「統合」・[CHG-0062](../change/0062-pr-hub-simplify.md)）。旧経路（窓口の pi の承認経路 `/pending`）は A5 で撤去する。それまでは併用しない |

### 段階

| 段 | 内容 | 状態 |
| --- | --- | --- |
| 1 | 読み取り専用のアプリ（一覧・概要・diff）。リポジトリの登録は起動引数 `--repo` | **実装済み**（develop に取り込み済み・未配備） |
| 2 | コメント・スレッド（未送信）・stale 表示・ref ライブラリ（`review-log.ts`・`review-git.ts`）・自己検査。サーバの書き込み API（`GET …/review`・`POST …/comments`・`POST …/submit`）と画面の入力を含む | **実装済み**（develop に取り込み済み・未配備） |
| 3 | pi の道具 2 つ・`receipt`・注入・配送の 4 状態の表示。判定器の許可規則はまだ足していない（役割の既定の確認のまま。§9） | **実装済み**（develop に取り込み済み・未配備。実機は未確認） |
| 4 | ペアリングと制御ポート（§7） | **取りやめ**（CHG-0062 で置き換え。実装しない） |
| 5 | 承認の指示（§8）。既定で無効 | **取りやめ**（CHG-0062 で、アプリの「統合する」へ置き換え。§6「統合」） |
| A2 | 統合 API（`merge-plan`・`merge`）と承認シートの画面（CHG-0062 の段 A2） | S（サーバ）・U（画面）・G（判定器の拒否）の 3 feature。実装済み（取り込みは承認待ち・未配備） |

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
| `meta.json` | `{"schema": 1, "pr": "<prKey>", "branch": "feature/x", "target": "develop", "createdAt": "<ISO>"}` |
| `events.jsonl` | 1 行 1 イベント。順序は行の順（`seq` は持たない） |

### イベント

共通の形: `{"v": 1, "id": "<uuid>", "t": "<種別>", "by": "app" または "pi", "at": "<ISO>", "vs": {"source": "<oid>", "target": "<oid>", "base": "<oid>"}, "d": {…}}`

| 項目 | 内容 |
| --- | --- |
| `by` | **表示用。信頼しない**。誰が書けるかの判定にも、レビュー状態の判定にも使わない（例外は、スレッドの「pi が返信済み」の表示だけ。§4） |
| `t`（種別） | `comment`・`summary`・`submit`・`receipt`・`merge_request`・`merge_started`・`merge_result` |
| `vs` | そのイベントを書いた時点の source・target・base の OID（stale の判定に使う。§4） |

| 種別 | `d` の中身 |
| --- | --- |
| `comment` | `{"thread", "anchor", "body"}`。`anchor` は `{"path", "side": "old" または "new", "blob": "<oid>", "line": n, "lineEnd": n}` か `null`（PR 全体）。`body` は平文。スレッドの最初のコメントの `thread` は自分の `id`、返信は同じ `thread` |
| `summary` | `{"done", "files": […], "findings": [{"ref": "<comment id>", "reply"}], "notes", "mergeMessage"}`。中身は CHG-0060 の D1・D2 |
| `submit` | `{"batchId": "<uuid>", "kind": "comment" または "changes" または "approve", "items": ["<comment id>", …], "dest": {"worktreeId"}, "resendOf": "<batchId>"}`。`resendOf` は省略可 |
| `receipt` | `{"batchId", "sessionId"}`。前提条件つきで追記する（その batch の `receipt` がまだ無いこと） |
| `merge_request` | `{"requestId", "sourceRef", "sourceOid", "targetRef", "targetOid", "baseOid", "message", "cleanup"}`。`cleanup` は `branch_and_worktree` など |
| `merge_started` | `{"requestId", "pendingId"}`。**pi が書く**（§8） |
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
| JSON として正しく、`t` が既知 |
| `receipt` が実在する `submit` の `batchId` を指す |

## 4 状態の導出

状態は ref の中身から導く。保存はしない。

| 対象 | 状態 | 導出 |
| --- | --- | --- |
| スレッド | 未送信 | どの `submit.items` にも入っていない |
| | 送信済み | `submit` に入り、その batch の `receipt` が無い |
| | pi が読んだ | その batch の `receipt` がある |
| | pi が返信済み | `receipt` の後に、同じスレッドで `by` が `pi` の `comment` がある。**表示用の状態**で、`by` を使うのはこの判定だけ（権限・統合・配送の判定には使わない）。利用者が受領後に足したコメントでは変わらない |
| レビュー | 変更依頼 / 承認 | `submit.kind` が `changes` か `approve` の最新のもの（`comment` の送信では変わらない。GitHub と同じ）。`by` では判定しない。その `submit` の `vs` が現在の source・target・base と違えば「古いレビュー」（stale） |
| stale | 古い版 | `vs` が現在の source・**target・base** のどれかと違う。行のアンカーは、`side` に対応する blob と比較する（行の再対応づけはしない） |
| 統合 | 承認待ち → 実行中 → 完了 | `merge_request` → `merge_started` → `merge_result` |

- 統合の許可は、固定された要求に対する制御の指示だけから得る（§8）。`by` や `submit` の種別からは得ない。
- レビューの承認と統合の承認は、データ上は別のイベントだが、画面では 1 回の操作にまとめる。
- 結果の状態（成功・拒否・失敗・不明）は、既存の `ExecutionResult` の `saved`・`kept`・`termination` から決め、`outcome` からの推測はしない。

## 5 配送

### レビューを送る

| 項目 | 内容 |
| --- | --- |
| 作る | 「レビューを送る」は `submit` 1 イベントを CAS で追記する。1 commit なので**原子的** |
| 送信の項目 | 送信時点の未送信（どの `submit.items` にも入っていない）コメント。数えるのは `by` が `app` のコメントだけ（pi の返信は項目に入れない。表示上の数え分けで、権限の判定には使わない） |
| 不変性 | `submit` は項目の ID の一覧・`batchId`・`vs`・宛先を持つ。送信後に足したコメントは含まれない。改変はなく、追記だけ |
| 未送信の漏洩防止 | `pr_comments list` は `submit` に入った項目だけを返す |
| 届け方 | 受け手の pi が、次の入力の前（`before_agent_start`）に ref を読み、未受領の batch を注入する（§9）。アプリへの通信はしない |
| 画面の表示 | 「次に pi へ入力したときに届く」と常に明示する。pi を起こす自動送信はしない |

### 宛先

| 項目 | 内容 |
| --- | --- |
| `worktreeId` | 作業ツリーのルート（`git rev-parse --show-toplevel` の正規化パス）の sha256 の先頭 16 桁。**パスそのものは ref に書かない** |
| 既定 | そのリポジトリの主 worktree（`git worktree list --porcelain` の先頭）。親が develop・作業が worker の運用でも届く |
| 画面 | 宛先を選べる。選べる一覧は、アプリが `git worktree list` から導く |
| 受け手 | 自分の `worktreeId` が `submit.d.dest.worktreeId` と一致する**親の pi だけ**が消費する。子（worker）には注入しない |

### 受領の記録と再送

| 項目 | 内容 |
| --- | --- |
| 受領の記録 | 注入の直前に `receipt{batchId, sessionId}` を前提条件つきで追記する。成功したときだけ注入するので、同じ batch が複数の pi から二重に届かない |
| pi が止まっているとき | `receipt` が付かず「送信済み」のまま |
| 再送 | 利用者の「再送」で、同じ項目の新しい `submit`（`resendOf` つき）を足す。自動の再送はしない |
| **限界** | 受領の記録は注入より前。**その間に落ちると「読んだ」と出るのに届いていない**。再送で救う |

## 6 アプリ

### 起動とポート

| 項目 | 内容 |
| --- | --- |
| 起動 | **v1 は利用者が起動する**（`pis` の Fence の内側からは届かない見込み）。`node apps/pr-viewer/server.ts --repo <パス> [--port <N>] [--allow-host <名前>] [--allow-merge]`（既定のポートは 8780。tailnet の名前（`*.ts.net`）の Host は既定で許可。`--allow-merge` は統合を許可する（既定で無効。下の「統合」））。`/pr start` は案内だけ。ビルドは不要 |
| UI ポート | `127.0.0.1` で待ち受ける。認証なし（遠隔の通信路は tailnet が保証する決定） |
| 制御ポート | UI とは**別のポート**。同じく `127.0.0.1`。段 4 から使う |
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
| 上限 | diff 全体 2 MB・1 ファイル 200 KB・ファイル一覧 400 件・コミット一覧 200 件・1 回の git は 10 秒 / 出力 4 MB。超えたら省略表示か 500 |
| 配信 | `/` と `/web/<名前>` は、許可リストにあるファイル（`index.html`・`app.css`・`*.js`）だけ。ディレクトリの走査は許さない |
| 書き込み系（段 2。実装済み） | `POST …/comments`・`POST …/submit` だけ。`Content-Type: application/json` と独自ヘッダー `X-PRV: 1`、`Origin` があるときは `Host` と一致することを要する。本文は 64 KB まで（chunked でも実測で打ち切る）。**表示していた版の固定**: 本文の `expect: { source, target, base }`（画面が表示した PR の 3 つの OID）を、あれば現在の PR と照合し、違えば 409 `stale_view`（見ていない新しい版を承認しない）、形が不正なら 400 `bad_expect`。画面は必ず付ける。レビュー状態の読み出しは `GET …/review`（副作用なし。ref が無い PR でも書かない）。断る場合は 409（`merged`・`bad_state`・`readonly`・`stale_view`）・413（`limit`） |
| 書き込みの git | 読み取りと同じ安全な実行器の上に、**許可リストだけ**を通す入口を持つ（`hash-object -w --stdin`・`mktree`・`commit-tree`・`update-ref --no-deref`。対象の ref は `refs/pi/review/p<16 桁>` だけ。先頭の `-c` は作者設定 3 つだけ）。残りの読み取り系も同じ許可リストで絞る |

### 描画と git の安全規則

| 項目 | 規則 |
| --- | --- |
| 描画 | `textContent` のみ。`innerHTML`・`insertAdjacentHTML`・`eval` を使わない。**v1 は Markdown を描画しない**（本文は改行とコードだけ） |
| コメントの位置 | スレッドは、行の側の blob（旧は `oldBlob`・新は `newBlob`）と `anchor.blob` が一致するときだけ行の下に置く。一致しないもの（古い版のコメント）は、表の上に「表示中の行に対応しないスレッド」としてまとめる（行番号だけで置くと、新しいコードの同じ行に付いてしまう） |
| CSP 等 | `default-src 'self'`・外部画像なし・`frame-ancestors 'none'`・`nosniff`・`Referrer-Policy: no-referrer` |
| git の実行 | 固定の argv・`shell:false`・hook / fsmonitor / 外部 diff / textconv / 外部 filter を止める設定・`--no-ext-diff --no-textconv --no-pager`・出力量と時間の上限。**自動の fetch も止める**（`GIT_NO_LAZY_FETCH=1`・`GIT_ALLOW_PROTOCOL=` を固定。partial clone で足りないオブジェクトを読むと git が ssh などを起動するため。足りないときは取得せずエラーにする） |
| 入力 | ref は `for-each-ref` の出力にあるものだけ。OID は 40（または 64）桁の 16 進だけ。パスは `--` の後か `<oid>:<path>` でだけ渡し、ref 内のパスをファイルシステムのパスとして使わない |
| 登録 | 登録されたリポジトリ（正規化した common dir）だけを扱う |

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
| 入口の検査（merge-plan・merge だけ。既存の comments・submit は変えない） | (1) `--allow-merge` が無ければ 403 `merge_disabled`（**既定で無効**。起動の旗で値を取らない） (2) `Tailscale-Funnel-Request` ヘッダーがあれば 403 `forbidden_funnel` (3) **Origin 必須**（無し・`null`・別ホスト・形の悪い値は 403 `forbidden_origin`。host を Host ヘッダーと照合） (4) `X-PRV: 1` と `application/json`（無ければ 400） (5) 本文は上限 64 KB・未知のキーは 400。OPTIONS は 405 で CORS ヘッダーを返さない |
| 実行の入力 | `expect: {source, target}`（2 キー必須・40 桁の 16 進。違えば 409 `stale_view`）・`message`（1〜4000 文字・改行は `\n` にそろえる・1 行目が空白だけは不可・制御文字と双方向制御文字と孤立サロゲートは不可）・`cleanup`（`none`·`branch`·`branch_and_worktree`。既定 `none`） |
| 応答 | 成功 200 `{merge: {commit, targetOld, targetNew, cleanup, warnings, recorded}}`。統合器の拒否コードをそのまま HTTP に写す（`conflict` は `conflicts` を添える。`recover_needed`・`busy` も 409。`failed` は 500 `merge_failed`）。生の git 出力・絶対パスを返さない。詳細な契約は試験 `test_pr_viewer_merge_api.py` と U の画面 |
| 計画（merge-plan） | `mergeable`・`refusal`・`blockers`・`plan`（統合元・統合先の先頭・コミット数・ファイル一覧 200 件・+/−・リスクのあるパス 50 件・`riskConfig`・`touchesApp`）・`defaults`（メッセージ・`messageSource`・`summaryStale`）・`warnings`（変更依頼・古いレビュー・未送信コメント。**表示専用**）。リスクの判定は表示上限ではなく**全件の変更パス**に対して行う。リスク設定（`~/.config/pi/harness/rules.json` の `judge.common.pi.integrate.risk_paths`。`--rules-file` で差し替え）を読めないときは `riskConfig: "unavailable"`（「リスクなし」と混同しない）。`touchesApp`（`apps/pr-viewer/**` に触れるか）は設定と独立。既定メッセージは、レビュー記録の下書き（検査を通るものだけ。古い版なら `summaryStale`）、無ければ枝の最新コミットの件名を使う生成文 |
| 記録（表示用） | 成功だけ、`merge_request` と `merge_result` を 1 回の追記で書く（`merge_result` は先行する request が要る）。書けなかっても統合の成功は取り消さず `recorded: false`。記録は権限の根拠にしない。診断ログは標準エラーに 1 行の JSON（要求 ID・PR・結果・統合後の OID・記録の成否。本文・ヘッダー・パスは出さない） |
| 同時実行・停止 | リポジトリ単位の「待たない」排他（取れなければ 409 `busy`。plan も同じ）と、統合器のロックファイル（別プロセスとの排他）。SIGTERM・SIGINT は**実行中の統合を、結果の記録と応答を終えるまで待つ**（一律の強制終了は設けない。強制するなら SIGKILL と `recover`）。通信が切れても統合は最後まで続く |
| plan の負荷 | plan は同じリポジトリで直列化するだけ（連打抑止・結果の再利用はしない）。同じ内容の object は同じ OID になるので無制限には増えないが、再計算の CPU と git の起動は毎回かかる。到達できるクライアントは資源を使える（認証を入れない方針の帰結） |
| 旧経路（`/pending`）との共存 | **併用は禁止**（A5 で旧経路を撤去するまで）。アプリは統合の前に、`refs/pi/lock/*`・`refs/pi/running/*`（どれか 1 本でもあればリポジトリ全体で拒否）と、`refs/pi/pending/*` の記録（`params.source` がこの枝と一致する `git_integrate` だけ。壊れた記録は無視）を確かめて断る（409 `legacy_*`）。列挙できない・200 件超は `legacy_unreadable`（見えないものを無いことにしない）。**確認の直後に旧経路が始まる窓は残る**（旧経路は別のロック（ref）を使うため、アプリのファイルロックとは相互に排他できない）。同時に使わない運用で守る |

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
2. `chezmoi apply`（`rules.json` を生成し直す）→ 使う pi / pis を再起動する。
3. 配備先で、判定器が `X-PRV` 付きの curl と `merge-cli.ts merge` を deny することを確かめる。tailnet や funnel で公開するなら、`~/.config/agents/local.toml` の `[pis.network] deny` に自分の公開名を足し、Fence の内側から届かないことを確かめる（上流プロキシが名前解決する経路では、中継が内部アドレスを止められない: [pi-sandbox](guard/pi-sandbox.md)）。
4. `--allow-merge` を付けてアプリを起動し、安全な試験用リポジトリで統合を 1 回試す。異常終了の後は CHG-0062 §3.5 の手順で `recover` する。

## 7 ペアリングと制御（段 4。未実装）

> **置き換え予定（2026-11-03）**: ペアリング・制御ポート・long-poll・共有の秘密は採らない。通信は ref の追記と、pi 内の受信箱で行う（[CHG-0061](../change/0061-pr-inbox.md) の決定 D2）。以下は置き換え前の設計で、実装しない。

| 項目 | 内容 |
| --- | --- |
| 開始 | `/pr pair`。**利用者専用の TUI コマンド**（モデルは呼べない。`/pending` と同じ構造） |
| 通信の向き | pi がアプリへつなぎ続ける long-poll。pi は待ち受けない（出方向だけで足りる） |
| アプリが導出するもの | pi の申告（`cwd` など）は信用せず、アプリが `cwd` から git で repo・worktree・branch を導く。導出できなければ拒否 |
| 秘密 | ペアリングで共有する乱数。**メモリだけ**に持つ（保存しない） |
| 範囲 | 制御ポートは repo の内容を返さない |
| セッション終了 | `session_shutdown` で unpair を試みる。落ちたときは、一定時間 poll が無ければ死亡とみなす |
| 複数の窓口 | v1 は、統合先ごとに窓口を **1 つ明示選択**する。取り出した指示を他へ再配布しない |
| `--repo` | 段 4 でも撤去しない（リポジトリの登録とペアの寿命は別の責務） |
| `local_ports` | `common.toml.tmpl` は変えない（空のまま）。制御ポートはマシンごとの `local.toml` で開ける案内だけ。サンドボックスの境界を動かす判断は利用者が行う |

| エンドポイント（制御ポート） | 内容 |
| --- | --- |
| `GET /ctl/ping` | 存在確認・バージョン |
| `POST /ctl/pair` | `{sessionId, cwd, mode, hasUI, pid}`。成功すると `{pairId, secret}` |
| `POST /ctl/poll` | 秘密つき。指示を取り出す（claim を伴うので **POST**）。待つ時間は 1 回 25 秒ほど |
| `POST /ctl/result` | 秘密つき。結果のヒント（正本は ref） |
| `POST /ctl/unpair` | 秘密つき |

## 8 承認の指示（段 5。未実装・既定で無効）

> **置き換え済み（CHG-0062、2026-11-03）**: 承認の指示を `merge_request`（ref の追記）で窓口の pi へ届ける設計は採らない。統合は、人がブラウザで押した POST でアプリが実行する（§6「統合」）。以下は置き換え前の設計で、実装しない。
>
> （旧）**置き換え予定（2026-11-03）**: 承認の指示は、制御ポートではなく `merge_request`（ref の追記）で窓口の pi の受信箱に届ける（[CHG-0061](../change/0061-pr-inbox.md) の S5・決定 D1・D2）。機能（アプリで閉じる）は維持する。以下は置き換え前の設計。

アプリは承認を**指示**するだけで、保留の作成も実行も窓口の pi が行う。アプリは `refs/pi/pending` を書かない。

| 項目 | 内容 |
| --- | --- |
| 指示 | `{instrId, prId, requestCommit, requestId}`。有効 120 秒・1 回限り。秘密つきの POST の poll で受け取る |
| 照合 | 窓口の pi は `requestCommit` の `events.jsonl` から、その `requestId` の `merge_request` を読む（**ref の先頭ではなく、その commit**）。構造化して、保留に作る要求（source ref・source OID・target ref・target OID・base・メッセージの digest・cleanup）と**完全一致**を確かめる。一致しなければ `merge_result{refused}` |
| 順序 | 照合 → `merge_started{requestId, pendingId}` の追記（**追記できなければ実行しない**）→ `requestApproval` → 既存の `planApproval` → `executeApproval` → `merge_result` の追記 |
| 実行前の確認 | 期限・現在のセッション・有効設定・`isIdle`・`authorize` を、実行の直前に確かめる。モデルの実行中は `merge_result{refused: busy}` で断る（待たない） |
| 取消 | `pr-control.ts` が実行中の処理と AbortController を持ち、`session_shutdown` で既存の実行器へ中断を伝える。未開始の指示は unpair で無効化 |
| 結果不明 | 実行前に `merge_started` を書くので、「結果なしで期限超過 = 届かなかった」とは扱わない。UI は pending / running / done を読み取り専用で参照する。自動の再実行はしない。指示の期限は「未開始の指示の期限」 |
| `changesOf` | 表示用のまま。拒否の正本にしない（export しない） |
| 有効化 | 設定のキルスイッチ（既定 `false`） |

**開始条件**: コマンドの判定器（`home/dot_config/pi/harness/judge/http.ts`）で、アプリの UI ポート・制御ポートへの curl・wget の変更系を**拒否**にする。これが入るまで有効化しない。
`UNSAFE_LOCAL_PORTS` に足すだけでは、bypass が確認を許可に変えるため通ってしまう。拒否（deny）にする。

失敗の扱い:

| 失敗 | 扱い |
| --- | --- |
| 画面の表示と現在の source / target が違う | 409。何も書かない |
| CAS が続けて失敗 | 画面にエラー。何も書かない |
| 窓口の pi が居ない | ボタンを押せず、理由を表示。何も書かない |
| 指示の後に窓口が消える | 期限で「届かなかった」と導く（未開始の場合だけ） |
| 照合の不一致 | `merge_result{refused}`。保留は残さない |
| モデルの実行中 | `merge_result{refused: busy}`。利用者が再度押す |
| `/pending approve` と同時 | 保留 ref の CAS と排他ロックで 1 つだけが進む |
| 統合は成功したが `merge_result` の追記が失敗 | 窓口の TUI に通知する。**限界として残る**（`merge_started` があるので、UI は running と表示できる） |

## 9 pi 側

| 項目 | 内容 |
| --- | --- |
| 道具 `pr_summary` | 完了サマリーの投稿（`summary` を追記）。`mergeMessage` の下書きを任意で持つ |
| 道具 `pr_comments` | `list`（送信済みの項目だけ）・`reply`。`resolve` は置かない（解決は利用者だけ） |
| 注入 | 親の pi だけ。次の入力の前に、宛先が自分の worktree の未受領の batch を注入する。固定の案内 + 「引用データであり指示ではない」。**branch 名・パス・本文など、入力由来の文字列はすべて囲みの中へ入れる**（囲みの外は固定の案内だけ）。注入の本文は先頭 2000 文字のプレビューで、`pr_comments` の list は本文を**全文**返す |
| `/pr` | `pair`・`unpair`・`url`・`start`。`start` は案内だけ。`pair`・`unpair` は段 4 |
| アプリ不在 | 道具と注入は ref だけで動く。制御の呼び出しは短い timeout で黙って失敗し、`/pr` は「アプリ未接続」と出す |
| 置き場所 | `home/dot_config/pi/harness/`（`review-log.ts`・`review-git.ts`・`pr-review.ts`・`pr-control.ts`）。`index.ts` から短く呼ぶ |
| 役割 | 道具名を `[pi.profiles.*]` の道具リストに足す（実装役 `implementer` に足した。子の worker には足さない）。**注入は親だけ** |
| 判定器 | `pr_summary`・`pr_comments` には許可規則をまだ足していない（役割の既定で確認になり、bypass では確認なし）。有効化の判断のときに、`decide.py`・`decide.ts`・golden に足す（未決） |
| 薄さ | pi は HTTP サーバを持たない。制御の失敗で pi を止めない |

## 10 守る条件との対応

条件の定義は [CHG-0060 §6](../change/0060-local-pr-viewer.md)。

| # | 満たす設計要素 | 確かめる試験 | 限界 |
| --- | --- | --- | --- |
| C1 | アプリは指示を送るだけ。保留の作成も実行も窓口の pi（§8） | 承認の縦断。アプリの import 検査 | 段 5 は未実装。偽ペアの余地（権限は上がらない） |
| C2 | ref が正本。道具と注入は ref だけを読み書きする | アプリを止めた状態で道具・注入が動く | — |
| C3 | `pr_comments list` は `submit` に入った項目だけを返す | 未送信が出ない試験 | — |
| C4 | `127.0.0.1` を明示して bind。tailnet へは serve | `server.address()` の検査 | serve の設定の誤り（funnel など）は検知できない。手動 |
| C5・C14 | `textContent` のみ・Markdown 描画なし・CSP。モデルへは構造化し、引用と依頼を分ける | `innerHTML` 等の静的検査。注入文字列の試験 | プロンプト注入の完全な防止は保証しない |
| C6 | 自作。依存なし | 機械では確かめられない | 複写していないことは review で見る |
| C7 | pi は ref だけで動く。制御の失敗は握りつぶす | app 停止時の独立動作・終了処理・import 境界 | 行数の固定試験は置かない |
| C8 | アプリが書くのは `refs/pi/review/*` だけ。保留は窓口の pi が作る | アプリの import 検査 | — |
| C9 | 登録された repo だけ。専用の git 実行器。ref 内のパスを使わない | 悪意ある設定（fsmonitor・hook・textconv 等）の陰性試験 | git の未知の起動経路は防げない |
| C10 | 遠隔は tailnet に任せる。GET は副作用なし。書き込みは独自ヘッダー・Host・Origin の検査 | 全 GET の副作用検査 | ルート表にあるものだけ。**UI ポートは認証なし**（§12） |
| C11 | `submit` の不変・原子性・`receipt` の前提条件・再送は新 batch。宛先は `worktreeId` | 配送の試験（二重消費・再送・親が develop の構成） | 受領の記録と注入の間の窓 |
| C12 | 全イベントに `vs`。stale は source・target・base。レビュー承認と統合承認は別イベント | 状態導出の試験 | 行番号の再対応づけはしない |
| C13 | CAS・`--no-deref`・再読して再適用・上限・終端記録の余裕・追加の親 | CAS・競合・上限・gc 後の到達可能性 | **保持期限と圧縮は v1 で未実装**（上限で止まる） |
| C15 | `/pr pair` は TUI コマンド。秘密はメモリだけ。アプリは git で導出する | 制御の試験（段 4） | 段 4 は未実装。モデルが curl でペア要求を送れる（判定器の拒否が開始条件） |

## 11 試験

| 段 | 要点 |
| --- | --- |
| 1 | `server.address()` が `127.0.0.1`。全 GET の前後で状態が変わらない。悪意ある設定を仕込んだ repo で標識ファイルを作らない。入力の検査。`innerHTML` 等が無い |
| 2 | 4 プロセスの同時追記で欠落・重複が無い。期待 OID の不一致で失敗。symbolic ref に差し替えても通常のブランチを巻き込まない。上限超過で断る。自己検査の各項目で、その PR だけが書き込み拒否になる。stale。`by` を使わない状態導出 |
| 3 | 未送信が注入に出ない。batch は不変。2 つの pi が消費しても注入は 1 回。再送は新しい batch ID。ブランチ削除と `gc --prune=now` の後も古い source が残る。親が develop・PR が feature・worker が子の構成で、指定した親の次の入力にだけ届く。アプリ停止時も `before_agent_start` が即座に返る |
| 4 | 秘密なしは 401。指示は 1 回限り・期限で失効。統合先以外には届かない。poll が止まると死亡扱い。再起動後の再ペア。pi の申告と実体が違うペアは拒否 |
| 5 | 縦断（pending → running → done と `merge_result`）。同じ `requestId` の内容差し替え・同じ OID の別 target・message や cleanup の差し替えを拒否（通常のコメント追記は許す）。指示の取得後・計画中・実行開始後に unpair / reload / 終了を起こして、未開始の実行禁止と既存の停止確認の経路を確かめる。`merge_started` の追記が失敗したら実行しない。`merge_result` の追記が失敗しても UI が状態を表示する。アプリの再起動後に再実行しない。busy の拒否 |
| A2 | 統合 API（`test_pr_viewer_merge_api.py`）: 偊の approve / merge_request / 保留を ref に置いても統合されない（同じ fixture で正規の POST が通る対照つき）。`--allow-merge` 無し・Origin 無し / `null` / 別ホスト・Funnel ヘッダー・`X-PRV` 無し・expect の不正とすれ・メッセージと cleanup の不正・旧経路の保留・ロック・running・同時 2 要求・衝突・dirty・recover_needed で ref と作業ツリーが動かない。merge-plan の無副作用・リスクの全件判定・SIGTERM で実行中の統合を待つ・通信断でも統合が続く。import 境界（`merge-api.ts` が git を直接動かさない・承認状態を読まない） |
| 共通 | アプリが `pending-*.ts` などを import しない。新しい試験は `scripts/verify.py` に登録する |

## 12 既知の制限と未確認

| 項目 | 内容 |
| --- | --- |
| 実機でしか確かめられないもの | Fence の内側から制御ポートへ届くか・Windows（path・待ち受け）・tailnet の公開範囲・`/reload` 後に保持した `ctx` が有効か |
| feature の worktree からの書き込み | `refs/pi/review/*` を feature の worktree の `pis` から書けるか（`refs/pi/pending` は確認済み） |
| C13 | 保持期限と圧縮は v1 で未実装。上限で止まる |
| UI ポートは認証なし | tailnet が保証する決定。統合（`--allow-merge`）を有効にすると、到達できるクライアントは統合できる（§6 統合の表）。素の `pi`（Fence なし）では、モデルが変更系の API を直接呼べる（判定器の拒否はうっかり防止の水準） |
| ブランチ削除後 | PR の一覧・詳細は、生きているブランチの ref から作る。ブランチを消した PR は画面から見えない（review ref と最後の source は残る。§2 の「branch と review ref の和集合」は**未実装**。独立 review の指摘 M6） |
| 画面からの「再送」 | 送信履歴の各 batch に「再送」ボタンがある（`resendOf` つきの新しい `submit`）。受領の記録と注入の間に落ちたときの手動の救済 |
| 段 5 の開始条件 | **判定器でアプリのポートへの変更系の呼び出しを拒否するまで、段 5 は有効化しない** |
| 偽のペア | モデルもペア要求を送れる。権限は上がらないが、窓口の指示を横取りして断ることはできる（制御ポートは repo の内容を返さない） |
| 行の再対応づけ | しない。outdated は blob の比較だけ |
| ref の同期 | 通常の clone / push では同期されない。mirror で流出しうる。削除は即時消去ではない（未決。CHG-0060 §7） |

## 13 関連

- [CHG-0060](../change/0060-local-pr-viewer.md)（案件）
- [CHG-0055](../change/0055-async-approval.md)（非同期承認）
- [保留（非同期承認）](guard/pi-pending.md)
- [pis のサンドボックス（pi の側）](guard/pi-sandbox.md)
