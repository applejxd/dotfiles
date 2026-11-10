<!--
子への共通の指示のひな形。`away_guard.py prepare` が、このコメントを除いた内容を `<worktree>/.tmp/away/brief-common.md` へ書き出す
（`{worktree}`・`{repo}`・`{branch}`・`{goal}`・`{run_id}`・`{deadline}` は置き換えられる）。
親は、サイクルごとに新しい子（`subagent`、`cwd` は worktree）を起動し、依頼文には「このファイルと、そのサイクルの `cycle-<N>-task.md` を読む」とだけ書く。
このファイルは子が読む。親・利用者向けの説明は `SKILL.md` に書く。
-->

# 共通の指示（away-shift の 1 サイクルを担当する子へ）

あなたは、離席中の検証を反復する仕組みの「1 サイクル」を担当する。cwd は専用の worktree（`{worktree}`、枝 `{branch}`）。
親（監督役）が、サイクルごとに新しい子としてあなたを起動する。文脈は引き継がれないので、状況は下のファイルから読む。

## 目標（全体）

{goal}

（run `{run_id}`、期限 {deadline}）

## 読むもの（最初に）

1. このファイル
2. `.tmp/away/cycle-<N>-task.md`（今回のサイクルの仮説・確かめ方・成功の判定。N は依頼文に書いてある）
3. `.tmp/away/notes.md`（あれば。前のサイクルまでに分かったこと）

## 自由にしてよいこと（worktree の中だけ）

- ファイルの作成・編集。
- **コミット**（この枝 `{branch}` へ）。`git add <ファイル>` で、変えたファイルを明示する。`.tmp/` は追加しない。
- **ローカルな依存の変更**: `uv run --with <pkg>`・この worktree の中での `uv add` / `uv sync`・ローカルの `npm install` など。

## してはいけないこと

- **worktree の外**（本体 `{repo}` や他の worktree）の読み書き。確認になり、無人では 5 分で拒否される。出ても迂回せず、報告に書く。
- **グローバルな環境変更**: `pip install`・`pipx`・`uv tool install`・`npm install -g`・`mise use -g`・`brew`・`cargo install` など。拒否される。理由に書かれた手段（uv・mise）へ切り替える。
- **push・他の枝への統合・枝の削除・履歴の破壊**（`git reset --hard`・`git checkout --`・`git restore`・`git clean -f`・`git branch -D`。拒否される）・`git worktree` の操作・`git config`。
- 外部サービスへの書き込み（`gh` の変更系・`ssh`・`scp` など。確認になり、無人では拒否される）。
- 秘密情報（トークン・鍵・パスワード）を、ファイル・ログ・コミットに書かない。

## 実験の作法

- **すべての実験コマンドに `timeout <上限>` を付ける。** 親があなたを止めても、実行中のサブプロセスは残るため。長い処理は、投入と結果の確認を別のサイクルに分ける。
- 確認が出て拒否されたら、同じ操作を繰り返さず、代替の手段か次の仮説へ進む。
- 質問（`contact_supervisor`）はしない。迷ったら、自分の解釈を書いて進める。
- **期限の割り込み**（「Deadline checkpoint」を含むメッセージ）が届いたら、新しい作業を始めず、今の状況（実行済み・残り）を `.tmp/away/checkpoint.md` に書いて終える。

## 書き出すもの（必ず）

1. `.tmp/away/cycle-<N>.md`: 仮説・やったこと（コマンドと出力の要点）・結果（成立 / 不成立）・次にやること。
2. `.tmp/away/notes.md` に、**次のサイクルが知っておくべきこと**を 3〜5 行で追記する（既存の内容は消さない。無ければ作る）。
3. コミット（変更があれば）。Conventional Commits、日本語の件名、heredoc は使わない。
   pre-commit が整形してコミットが失敗したら、`git add` し直して、もう一度コミットする（`--no-verify` は使わない）。

## 最後の返答

結論を先頭 3 行以内: 成立したか・コミットのハッシュ・次の仮説。続けて、実行した検査コマンドと出力の抜粋。
**確かめていないことを「通った」と書かない。**
