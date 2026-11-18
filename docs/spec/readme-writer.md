# readme-writer（README を作る・直す・点検するスキル）

リポジトリの実体（manifest・ソース・CI・LICENSE）に裏づけられた `README.md` を、作る・直す・点検するスキル。
事実の抽出（`scripts/collect_facts.py`）と、README が約束するコマンド・パス・リンクの実在検査（`scripts/check_readme.py`）を、標準ライブラリだけのスクリプトで行う。

- **配布の場所**: `home/dot_agents/skills/readme-writer/`（`chezmoi apply` で `~/.agents/skills/readme-writer/` へ）。pi など、`~/.agents/skills` を読む CLI から使える。
- **正本は skill-lab**（個人のスキル開発用リポジトリの `skills/readme-writer/`）。ここへは**複製**（vendor）で、このリポジトリでは編集しない。直すときは skill-lab 側で直して、取り込み直す。
- **取り込んだ版**: skill-lab のコミット `af3e23d`（2026-11-17）の `skills/readme-writer/` の追跡ファイル（45 件。`git archive` で取り出した）。
- **正本の仕様・評価**: skill-lab の `docs/spec/0005-readme-writer.md`、`docs/change/0007-readme-writer.md`、`experiments/readme-writer/`（比較評価と改善ループの記録）。

## 契約

| 項目 | 内容 |
| --- | --- |
| 実行環境 | `python3`（3.11 以上。`tomllib` を使う）。標準ライブラリだけで、追加の導入は要らない。ネットワークに出ない |
| 成果物 | 頼まれた README（`README.md` など）と、利用者への短い報告。既存の README は、書き換えてよいと言われていなければ、案を示して許可を得てから書き換える |
| 動かして確かめる範囲 | 作業ツリーの中だけで完結し・ネットワークに出ず・何もインストールせず・秘密を使わず・戻せない操作をしないコマンドだけ、許可なしで実行する。それ以外は実行せず「未実行」と報告する |
| 検査スクリプトの境界 | 読むだけ（README のコマンドを実行しない・リポジトリへ書かない・`.pyc` も書かない）。リポジトリの外を指すリンク・symlink は読まない。1 MB を超えるファイルと 2 万字を超える行は打ち切る |

## このリポジトリでの扱い

- スキルの試験（`tests/`、70 件。標準ライブラリの `unittest`）は、スキルの中に置いたまま配布する。実行は、スキルのフォルダで
  `python3 -m unittest discover -s tests`（このリポジトリの `mise run verify` の対象ではない）。評価用のリポジトリ（`evals/files/`）も、試験が使うので配布に含める。
- 評価用リポジトリの `.github/`（CI の定義）は、**配布先に出ない**（chezmoi は、source の先頭が `.` のディレクトリを配らない）。
  試験は、`.github` が無くても通るようにしてある（CI の抽出の確認は、あるときだけ行う）。
- Python の整形・lint は、上流（skill-lab）の書き方のまま保つため、このリポジトリの `ruff` の対象から外す（`pyproject.toml` の `extend-exclude`）。
- `home/.chezmoiignore.tmpl` で、試験が作る `__pycache__` を配布・取り込みの対象から外す。
- `SKILL.md` の frontmatter は `name` と `description` のほかは、手動起動の 1 行だけ（`allowed-tools` なし・`context: fork` なし）。理由は [スキルの frontmatter の方針](skill-frontmatter.md)。
- ローカルの変更: `SKILL.md` の frontmatter に `disable-model-invocation: true` を 1 行足した（2026-11-18。利用者の決定。理由は skill-frontmatter の「[手動起動](skill-frontmatter.md#手動起動disable-model-invocation)」）。skill-lab 側にも同じ変更を入れて取り込み直すまで、`sync_skill_lab.py` の置き換えで消える（`--check` の差分に出る）。 あわせて、description の対象外案内の「AGENTS.md / CLAUDE.md の作成(onboarding)」は、`onboarding` を `agents-md` へ統合したので古い（skill-lab 側で直す。手動起動なので害は小さい）。

## 評価の結果（正本の記録の要約。skill-lab 側が正本）

先行スキル（`readme`）・スキルなしと、審査員 3 系統（Claude・GPT・Gemini）で盲検比較した。平均順位（1 が最良。各セル 1 回）は、
改善前（v1）が 2.17 対 1.56 対 2.28 で先行スキルに負け、v3 が 1.44 対 1.83 対 2.72 で最良になった（GPT 系の実行者 1.44 対 2.06 対 2.50、未見の 2 ケース 1.17 対 2.33 対 2.50）。
冗長な README を混ぜた検査（カナリア）では、冗長版が選ばれたのは 0/6 だった。**限界**: 各セル 1 回で、調整に使ったケースを含む。発動精度は未測定。

## 更新の手順

skill-lab 側で直してコミットし、このリポジトリで次を実行する（取り込むのは**コミット済みの版**だけ。未コミットの変更があると止まる）。

```bash
python3 scripts/sync_skill_lab.py readme-writer --check   # 差分を見るだけ（差分があれば終了コード 1）
python3 scripts/sync_skill_lab.py readme-writer           # 置き換え。上の「取り込んだ版」も更新する
```

置き換えたら feature で commit → finish する。シンボリックリンクにしない理由は [conference-video](conference-video.md) の同名の節と同じ。
