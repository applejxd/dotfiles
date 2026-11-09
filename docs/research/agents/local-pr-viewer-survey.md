# ローカル PR ビューアーの公開実装の調査（GitHub をリモートに持たない開発向け）

- **日付**: 2026-11-02
- **対象**: 公開されている実装（pi 系・エージェント系・forge 系・部品）。README・公式ページを取得して読んだ範囲。**クローン・インストール・実行はしていない**
- **問い**: GitHub をリモートに持たない開発で、GitHub の PR に使い勝手が近いレビューの画面（オンプレ・ローカル）には、どんな公開実装があるか。要件は「差分の閲覧」「コメントとスレッド」「レビュー状態とマージ」「pi との連携」
- **結論**: ローカル系は多く、forge 系は完全だが重い。**4 要件を全部満たすものは、調べた範囲で見つからなかった**。足りないのは、レビュー状態とマージ（ローカル系に無い）と、pi 連携（forge 系に無い）

## 調べ方

- 検索（Brave）: 「local pull request review tool for git without GitHub」「GitHub-style diff viewer CLI localhost review comments AI agent」「pi coding agent extension diff review」「Forgejo vs Gitea vs GitLab vs OneDev」「Gerrit … Radicle … git-appraise」「MCP server code review comments local」ほか約 20 クエリ
- 取得: `raw.githubusercontent.com` の README・`pi.dev/packages/…`・各製品の公式ページ。結果は信頼できない外部の内容として扱い、事実だけを取った
- 限界は末尾の「未確認」

## ローカル・Web・エージェント連携（1 人用）

| 名前 | 形 | 要点（README で確認した事実） |
| --- | --- | --- |
| rosenbjerg/local-review | Go 単一バイナリ + 埋め込み React + SQLite。GPL v3 | merge-base との差分・行や範囲のコメント・スレッド・種別（bug/suggestion/question/nit）・アンカーがコードに追従（moved/outdated）・ファイル単位の reviewed（変更で自動解除）・~235 言語。**エージェントがローカル API で返信し、UI に出る**。承認・マージは無い（markdown のエクスポートまで） |
| diffle（manuel2258） | 単一バイナリ・npm・conda | 行・ブロック・ファイルへのコメントと resolve・viewed・LSP でジャンプ・MCP・エージェントへの構造化エクスポート。コメントは `<git-dir>/diffle/`（作業ツリーを汚さない）。GitHub の pending review へ送れる（提出はしない） |
| differ（mruwnik） | ClojureScript + Node・MIT | **MCP**（`get_or_create_session`・`register_files`・`get_pending_feedback`・返信・resolve）・SSE でリアルタイム・(project, branch) のセッション。「ローカルは安全と仮定。インターネットに出さない」 |
| difit（yoshiko-pg） | CLI + ローカル Web | コミット・ブランチ比較・未コミット・stdin・`--pr <GitHub URL>`。コメントをプロンプトとしてコピー。スレッドの初期投入（`--comment`）。エージェント向け Skills |
| diffity（kamranahmedse。fork 多数） | CLI + Web | GitHub 風の差分。Claude Code・Cursor と連携。GitHub PR の URL も開ける |
| diffx（wong2）・splitbrain/review・wmbest2/local-review・sahirzm/local-code-review・rosgoo/code-review-mcp | Web・Go・Python・Rust・MCP | 同じ系統。local-code-review は MCP でエージェントが起動する。code-review-mcp は Submit までブロックして構造化出力で返す |
| diffing・gitdiff（Rust TUI）・hunk（TUI）・self-review（デスクトップ） | TUI・デスクトップ | gitdiff はコメントを `REVIEW.md` へ。hunk はエージェント向けのレビュー優先の差分（Jujutsu 対応）。self-review は GitHub PR / GitLab MR の URL も開く |
| Git Local Review（JetBrains） | IDE プラグイン | 「まだ存在しない PR」を任意の差分範囲で開き、ファイルごとにレビュー状態を追跡 |
| Orca の diff コメント | デスクトップ・**モバイル**・リモート | 任意の差分行に markdown コメントを付けてまとめてエージェントへ送る。worktree ごとの所有。送信形式は `File:`/`Line:`/`User comment:` のブロック |

## pi 系

| 名前 | 形 | 要点 |
| --- | --- | --- |
| **earendil-works/pi-review-loop** | pi 拡張。**ネイティブのウィンドウ**（Glimpse） | `/diff-review`。「前回のレビュー以降」と「vs HEAD」の差分・行コメント・ファイルノート・Reviewed の印。送信で現在のワークスペースを**チェックポイントとして pi のセッションに保存**（`review-loop/checkpoint` の custom エントリ）し、フィードバックを pi のエディタへ挿入（**自動送信しない**）。再開・分岐に追従。単一ユーザー。ブラウザではない |
| linddominic/pi-review-diff | pi 拡張。ブラウザ UI（127.0.0.1・ランダム ID） | ブランチ・未コミット・Active turn（pi 実行中のライブ差分）・Last turn。コメントを**次のプロンプトに自動注入**。データは pi のプロセスの中だけ |
| cmpadden/pi-diff-review・@haphazarddev/pi-interactive-code-review・tmustier/pi-extensions | pi 拡張 | 差分・ファイルを見て行にコメント／対話的に閲覧／端末内でコメントを送る |
| lucaspiritogit/pi-diffloop | pi 拡張 | `edit`/`write` を実行前に横取りして approve／steer／edit／deny。**PR ではなく 1 変更ごとの確認**。作者が承認疲れの懸念を書いている |
| mitsuhiko/agent-stuff `review.ts`・tomsej/pi-ext・zeflq/pi-reviewer | pi 拡張 | **AI にレビューさせる**側（人の UI ではない）。`/review` で GitHub PR・ベースとの差分など |
| xingshuyin/pi-web-ui（npm `pi-web-ui`。月 14.7K・MIT） | ブラウザ・Electron・SSH・Docker・Android | pi の「ブラウザの操縦席」: チャット・コード・ファイル・端末・Git を 1 タブに。**PR ビューアーではない**（Git 機能の中身は未確認） |
| PI WEB・jmfederico/pi-web・agegr/pi-web・Epsilondelta-ai/pi-web | pi の Web UI | 永続セッション・複数マシンの監督 |
| Pi Agent Companion（VS Code）・shaftoe/pi-coding-agent-action | VS Code 拡張・GitHub Action | 提案されたファイル変更の承認／GitHub の PR にレビューを投稿（GitHub 前提） |

## forge 系（サーバを立てる）

| 名前 | 要点 |
| --- | --- |
| Forgejo / Gitea | Go 単一バイナリ・RAM 約 80MB。PR・レビュー・コメント・squash マージ・Actions。Forgejo は Gitea のフォーク。**AGit flow**（`git push origin HEAD:refs/for/main -o title=…` だけで PR。フォーク・ブランチ不要。Gerrit 風）。Forgejo v17.0 が 2026-10 |
| OneDev・GitLab CE・Gogs・GitBucket・SCM-Manager・RhodeCode | OneDev は Java で約 300〜500MB。GitLab CE は 4GB〜。Gogs は最小 |
| Gerrit | patch 単位のレビュー（amend して patchset を積む。Change-Id）。Google 由来 |
| Phorge（Phabricator の後継）・Review Board | 専用のレビューシステム |
| SourceHut | メール中心のレビュー。Web 中心でない |
| Radicle | P2P。patches（= PR）・issues・レビューを COB として git の中に保存。Web UI あり。自分の node を立てる |
| Tangled | atproto 上の forge（knot + AppView）。理論上は連合、実際は中央集権寄りという評（HN） |
| git-appraise（Google。アーカイブ済み） | レビューを git の notes に JSON で保存（`refs/notes/devtools/reviews`・`…/discuss`）。サーバ不要・分散。UI は無い |
| GitClear | 「オフラインで始めて、あとで接続」。GitHub などと双方向コメント同期。オンプレ版あり（商用。調べ切れていない） |

## 部品（差分の描画）

| 名前 | 要点 |
| --- | --- |
| @git-diff-view/react（MrWangJustToDo/git-diff-view） | React・Vue・Solid・Svelte・Ink。GitHub 風・split/unified・shiki または lezer でハイライト・SSR（0.1.6） |
| react-diff-view（otakustay） | unified diff を消費する React コンポーネント（3.3.3） |
| diff2html | diff を HTML に変換。React に依存しない |

## 要件との対応（事実と推測を分ける）

事実: 要件の 4 つを全部満たす実装は、調べた範囲で見つからなかった。

| 機能 | ローカル・pi 系 | forge 系 |
| --- | --- | --- |
| 差分の閲覧 | ほぼ全部 | あり |
| コメントとスレッド | あり（local-review・diffle・differ・difit・Orca） | あり |
| レビュー状態（approve / 変更依頼） | ファイル単位の reviewed だけ。approve は無い | あり |
| マージ（squash） | **無い**（push 前のレビューまで） | あり（squash・rebase・merge） |
| pi 連携 | あり（pi-review-diff・pi-review-loop・MCP 系） | **無い**（API で自作） |
| 運用の重さ | 軽い（単一バイナリ・SQLite か git-dir） | 重い（サーバ + DB + 認証） |
| スマホ | Orca だけ確認 | ブラウザで可 |

推測:

- このリポジトリの運用には、すでに「マージのボタン」がある（`git_integrate` = 保護ブランチへの squash 統合・承認画面・保留の承認・後片付け）。足りないのは、差分とコメントを見る Web 画面と、コメントを pi が読んで返す経路
- コメントの保存先は 3 系統ある（git の ref／notes: git-appraise・Radicle、SQLite: local-review、pi のセッション: pi-review-loop）。リポジトリと一緒に動き、複数の窓や機械から同じものが見えるのは git の ref
- pi-review-loop は pi の作者側の実装で、チェックポイントを pi のセッションに保存する形が参考になる。ただしネイティブのウィンドウで、ブラウザ・スマホからは見られない

## 限界と未確認

- README と公式ページを読んだ範囲。承認・マージの有無は、README に書かれたものだけ（実機で確かめていない）
- pi-web-ui の Git 機能の中身・Radicle の Web UI のレビュー機能・GitClear の詳細・Gitea/Forgejo の MCP サーバの有無は未確認
- vibe-kanban: 追加調査（2026-11-02）の事実は下の節のとおり。**出典の URL は未確認**（出典の確認が必要）。コードの取得・実行はしていない
- local-review は GPL v3。コードを取り込むなら影響がある（道具として使うだけなら通常は問題ない）。このリポジトリでは、調査の作法に従い**コードは複写しない**

## 追加調査: vibe-kanban（2026-11-02）

公開の情報だけ。**出典の URL は確認が必要**（ここでは書かない）。クローン・インストール・実行はしていない。

| 項目 | 内容 |
| --- | --- |
| 性格 | コーディングエージェントを並列に動かし、各作業を git worktree に隔離して、タスクを看板で管理するアプリ。差分の確認・コメントの機能を持つ |
| 限界 | PR・マージが GitHub 前提（リモートが要る）。pi には非対応 |
| 状況 | 運営会社が 2026-04 に終了し、OSS として維持される（sunsetting） |
| 結論 | **採用しない**（GitHub 前提・pi 非対応・エージェント管理アプリで、求めるものと違う） |

案件は [CHG-0060](../../change/closed/0060-local-pr-viewer.md)。

## 次

- 設計の選択（自作／既存ツールの採用／Forgejo、データの置き場、最初の範囲、言語）は、利用者の判断待ち
