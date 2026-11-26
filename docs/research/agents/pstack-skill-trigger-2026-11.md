# pstack 由来の汎用スキル 5 本の初回発火測定

2026-11-26。5 本を同時に提示した合成ケース 24 件で、選ばれた本文の集合はすべて事前の期待と一致した。
これは単一モデルかつ読み取り専用の測定である。既存スキルと一緒に使った場合や、実際の検証手順の成否は測っていない。

## 条件と計測方法

- 参考: [pstack 0.15.48](https://github.com/cursor/plugins/tree/9e278fe4d4ecd8bfe98b1b79bf4be662efb338cc/pstack) と [Pi 1.6.0 の JSON イベント仕様](https://github.com/earendil-works/pi/blob/faac585884ae2c013a6b1400f3e9e77f10b34bac/packages/coding-agent/docs/json.md)。
- 基準: Dotfiles `develop` の `f755705e` から切り出した `feature/pstack-practices` の初稿。[配布候補 5 本](../../spec/verification-skills.md)を毎回同時に提示した。
- モデル: GitHub Copilot `gpt-6.2-sol`、推論設定 `low`。各ケースは新規セッションで 1 回だけ実行した。
- 入力: 5 本それぞれの正例 3 件、対象外 6 件、目的が競合しやすい依頼 3 件。アプリ本体を含まない合成の作業フォルダを使用した。
- 測定: 依頼にスキル名や判定ラベルを入れなかった。対象ファイルの `read` が成功したことを Pi の JSON ツールイベントで突き合わせた。最終回答の自己申告は数えなかった。
- 隔離: 評価用に `read` のみをモデルへ提示した。MCP と既存スキル・コンテキストファイルの自動検出は無効にした。端末への配布は行っていない。

実行コマンドは `python3 .tmp/pstack-study/run.py`。各ケースで `pi --mode json --no-session --no-mcp --no-context-files --no-skills --no-prompt-templates --no-approve --tools read --provider github-copilot --model gpt-6.2-sol --thinking low` に、5 本分の `--skill` と自然文の依頼を渡した。
初回の入力・計測コード・集計元は同 worktree の `.tmp/pstack-study/` に置いた。生の会話ログは保存しない。

## 結果

| 観点 | 結果 |
| --- | ---: |
| 正例で対象スキルの本文を読んだ | 15/15 |
| 対象外で 5 本のどれかを読んだ | 0/6 |
| 競合例で期待した 1 本だけを読んだ | 3/3 |
| 完了したセッション | 24/24 |
| 1 セッションの所要時間の中央値 | 6.57 秒 |

正例では `verify-behavior`、`blast-radius`、`prevent-repeat`、`reframe`、`verify-state` がそれぞれ 3/3 だった。
競合例では、通常経路より互換性を問う依頼で `blast-radius`、問題名より順序を問う依頼で `verify-state`、再現より再発防止を問う依頼で `prevent-repeat` を選んだ。
1 件目の終了を確かめてから最大 4 並列で残りを実行し、ジョブ全体は約 58 秒だった。

### 解釈と次の判定

この結果から、少なくともこのモデルと書き下ろしの入力では、5 本を個別に待って調整する必要は見えなかった。
24 件全体で同じ回答を繰り返せるか、既存の `review-loop` や `imozuru` と競合しないかは未判定である。
試行版 5 本を残す。配布後の動作とみなさず、既存スキルを含めた別の入力で競合を調べる余地を残す。

## 未確認

- UI、CLI、モデル検査器を実際に動かした成果の品質。
- 別モデル、既存スキルの同時提示、観測条件を揃えた反復、配布先での検出。
- `chezmoi apply`。`uv run pre-commit` は既存依存 `keypirinha-stub` の取得時の `Repository not found` で停止した。frontmatter と対象 Markdown は切り出した検査で確認した。

## 既存スキルとの境界の点検（2026-11-27）

既存スキルと候補の説明を読み比べ、次の依頼でどの成果物を優先するかを整理した。「優先」は文面からの期待であり、発火の実測ではない。

| 自然文の依頼 | 優先 | 境界 |
| --- | --- | --- |
| 互換性だけをレビューして、指摘がなくなるまで直して | `review-loop` | 範囲が狭くても修正と再レビューを反復 |
| レビューのやり直しは要らない。前の版で保存したデータが壊れないかだけ見て | `blast-radius` | 変更の波及先を限定 |
| 最近また同じ指摘をしている気がする。セッションから不満を洗い出して | `friction-review` | 既知の原因の対策ではない |
| この入力ミスで何度もやり直した。次は保存前に止めて | `prevent-repeat` | 既知の失敗を仕組みで防ぐ |
| うまく名前が付けられない分野だけど、引用をたどって原典を集めて | `imozuru` | 成果物は文献・原典 |
| 何と呼べばいいか分からない。検索の前に、どの問題か切り分けて | `reframe` | 成果物は問いの整理 |
| キャンセルの直後に再試行すると画面で何が起きるか、手順どおりに見て | `verify-behavior` | 指定された操作の観測 |
| キャンセルと再試行を入れ替えても二重保存しないか調べて | `verify-state` | 順序の組み合わせと不変条件 |

`reframe` の初稿は、すでにテーマが定まった文献調査だけを対象外にしていた。
`imozuru` は用語が分からない段階から扱うため、テーマの明確さに関係なく、文献や原典の収集が主目的なら `reframe` を対象外とした。
`blast-radius` と `prevent-repeat` の説明にも、反復レビューやセッション記録からの摩擦調査との境界を明記した。

初回の 24 件は変更前の記録であり、新しい説明の発火率を示さない。今回、モデル試行の追加は行っていない。

### 配布経路と検証の範囲（2026-11-27）

- chezmoi 2.67.0 の `managed --include=files` を一時の設定・宛先で実行した。`.agents/skills/` 配下の対象 `SKILL.md` が 5/5 件表示された。端末への `apply` はしていない。
- Pi 1.6.0 の `DefaultResourceLoader` と `formatSkillsForPrompt` を一時の `HOME` で実行した。chezmoi のグローバルスキル置き場を `~/.agents/skills/` として見せると、31 本が検出され、22 本がモデル向け一覧に載り、警告は 0 件だった。対象 5 本と `review-loop`・`imozuru`・`friction-review` はすべて一覧に一度ずつ載った。
- `mise run verify`、`mise run verify:all`、`uv run pre-commit run --all-files` は、既存 Git 依存 `keypirinha-stub` を取得できず、pre-commit の hook を実行できなかった。Git は `Repository not found`、GitHub API は `404` を返した。依存・hook の設定に本変更の差分はない。[GitHub の公式文書](https://docs.github.com/en/repositories/creating-and-managing-repositories/troubleshooting-cloning-errors#repository-not-found)によると Git の応答は不在とアクセス不可のどちらでも起こり、今回の応答だけでは判別できない。
