# 無人実行で避けること

## 「承認が要るか」を判断基準にしない

理由は 2 つある。どちらも**ツールの不具合とは無関係**で、仕様どおりに
動いていても成り立つ。

### 1. 無人では承認が「確認」にならない

席にいない以上、`ask` が出ても誰も答えない。各ツールの仕様上の帰結は
「自動拒否」「スキップ」「応答待ちのまま停止」のいずれかで、**どれも
目的を達成しない**。承認を挟めば安全に実行できる、という前提が成り立たない。

| 実行環境 | `ask` の仕様上の結果 |
| --- | --- |
| Claude `dontAsk` | 自動拒否 |
| Claude `-p` (非対話) | スキップして継続 |
| Copilot cloud agent | `deny` 扱い |
| 対話セッションで離席 | 応答が来るまで止まる（run 全体が無駄になる） |
| pi の TUI | 確認の画面を出して待つ。**5 分（`promptTimeoutMs`）で拒否**し、「誰も答えなかった」と伝える（承認にはならない） |
| pi の背景の子エージェント | 確認は親の画面へ転送され、親の `promptTimeoutMs` が効く（実測: 利用者が答えれば続行する） |
| pi の YOLO mode | `ask` を全部自動で承認する（`deny` は効く） |

つまり「承認が要る操作」を計画に入れた時点で、そのサイクルは失敗する。

### 2. そもそも `ask` が出ないことがある

Copilot CLI の `permissions-config.json` はプロジェクト単位で
コマンドを事前承認できる（`/add-dir` や `/allow-all` でも増える）。
`commandIdentifiers` に `git` が入っていれば Copilot は `git` 系で
プロンプトを出さない。`kind: "write"` があればファイル書き込みも同様。

さらに、権限の方針（`pi-permission-policy.json`）の `ask` / `deny` に載っていない破壊的な形もある
（例: `docker run -v /:/host`、`uv tool install`、`mise use -g`）。
**止められていない = やってよい、ではない。**

## 判断基準

次のどれかに当たるなら、承認の有無に関わらず**やらない**。

1. **不可逆か** — 取り消せない。本体の履歴へのコミット、削除、履歴の書き換え（専用 worktree の枝へのコミットは、枝ごと捨てられるので可）
2. **外部に見えるか** — リモートや外部サービスに出る
3. **環境を変えるか** — インストール、設定変更、常駐プロセス

迷ったらやらない。レポートに「これをやりたかった」と書けば、
復帰したユーザが判断できる。それで十分速い。

## やらないことの一覧

| 操作 | 該当する基準 | 代わりに |
| --- | --- | --- |
| `git push` | 外部（拒否される） | しない。統合は利用者が行う |
| 本体の作業ツリーでの `git commit` / `git add` / ファイル編集 | 不可逆（復帰時に差分が読めない） | 専用 worktree の枝で行う（子は worktree の中で自由にコミットしてよい） |
| `git clean` / `git reset --hard` / `git branch -D` | 不可逆 | 触らない |
| `git stash drop` / `git checkout --` / `git restore` | 不可逆 | 触らない |
| `git config`（`--get` を含む） | 環境 | 触らない。設定値はファイルを読む |
| worktree の外への `rm` / `find -delete` | 不可逆 | 消さない。worktree の中で作業する |
| `sudo` 全般 | 環境 | レポートに必要性を書く |
| `docker run` の `--privileged` / `-v /:...` / `--pid=host` | 環境（ホストを直接触れる） | 使わない |
| `docker exec` でのシェル起動 | 環境 | 使わない |
| `apt` / `brew` / `pipx install` / `uv tool install` / `pip install` / `npm install -g` | 環境（`brew`・`pip`・`pipx`・`uv tool`・`npm -g` などは拒否される。統合後） | worktree の中の `uv run --with` / `uv add` |
| `uv add` / `uv remove` / `uv sync` | 環境（依存が残る） | worktree の中なら自由（ローカル。枝の変更として残る）。本体では使わない |
| `mise install` / `mise use -g` / `mise settings set` | 環境（`mise use -g` は拒否される。統合後） | 使わない。worktree の中の `mise exec` は可 |
| `uv self update` / `mise self-update` / `mise implode` | 環境（deny 済み） | 使わない |
| `cmake --install` | 環境（システムへ書く） | ビルドまでに留める |
| `docker rm` / `docker rmi` / `docker * prune` | 不可逆 | 触らない |
| `gh pr create` / `gh issue create` / `gh issue comment` | 外部 | 本文案を worktree の `.tmp/away/` か `report.md` に置く |
| `gh pr checkout` / `gh issue close` | 不可逆・外部 | 触らない |
| `nc` による疎通確認 | 外部 | 必要性をレポートに書く |
| 長時間のバックグラウンド常駐 | 環境（`subagent stop` では止まらない） | `timeout` で上限を付ける。サイクル内で完結させる |

この表は代表例で、網羅ではない。権限の方針の
`ask` / `deny` に載っているものは当然やらないが、
**そこに無くても上の 3 基準に当たるならやらない**。
`uv tool install` や `docker run -v /:...` のように、
`ask` にも `deny` にも載っていない環境変更が実在する。

## やってよいこと

- 読み取り（`git diff`、`git log`、ファイル閲覧、`grep`）
- **子は、専用 worktree の中で**: ファイルの作成・編集・削除、`git add`・`git commit`（枝へ）、
  `uv add`・`uv sync`・`uv run --with`・ローカルの `npm install` などローカルな依存の変更
- 親は、`.tmp/away-shift/<run-id>/` の中と、worktree 内の引き継ぎファイル（`.tmp/away/`）への書き込み
- 既存のテスト / lint / ビルドの実行（成果物を worktree の外へインストールしないもの）
- ネットワーク読み取り（ドキュメント参照、`gh` の読み取り系）

## 本体に触れたくなったら

「試しに直してみないと検証できない」場面は多い。**本体の作業ツリーは変えず、専用 worktree の枝で直す**（`SKILL.md`）。

1. 子が worktree の中でコードを直し、検証し、コミットする
2. 親が、worktree の中で同じ検証を自分で再実行する
3. 停止時に `audit` が、本体の `HEAD`・`git status` が開始時のままかと、枝のコミット・差分を出す
4. レポートで「この枝を統合するか捨てるか」を利用者に尋ねる

復帰した利用者が本体で `git diff` を打って**何も出ない**状態を保つ。これは「勝手に変えられていない」という保証になる。

## 秘密情報

`.env`、トークン、鍵の中身をログ・レポート・コマンド出力に残さない。
検証に必要でも、存在の有無だけを記録する（値は書かない）。

## 子に作業させる理由と、気をつけること

away-shift は、実験を**子（サブエージェント）に任せ、親が監督する**。理由は次のとおり。

- **文脈が汚れない。** サイクルごとに新しい子なので、長い実験の出力で親の文脈が膨らまない。引き継ぎはファイル（`.tmp/away/notes.md`）。
- **範囲を物理的に絞れる。** 子の `cwd` を専用 worktree にすると、その外への書き込みは確認（無人では拒否）になる。
- **止める手段がある。** `subagent` の `stop` と `timeoutMs`・`checkpointBeforeDeadlineMs`（`resume.md`）。

気をつけること（実測）。

- **`stop` は子を止めるが、子のサブプロセスは止めない。** 子のコマンドには `timeout` を付けさせ、停止時は `audit --kill` で掃除する。
- **子の自己申告は当てにならない。** 「確認は出なかった」と誤報した例がある。親が worktree で再検証し、確認の有無は審査ログで確かめる。
- **子はこの skill の本文を読んでいない。** 制約は `brief-common.md`（`references/child-brief.md` のひな形から作る）で渡す。
- 子の確認は親の画面へ転送される。離席中は誰も答えず、5 分で拒否される（承認にならない）。
