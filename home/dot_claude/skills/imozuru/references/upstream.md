# 上流と変更点

このスキルは [MaryCache/imozuru](https://github.com/MaryCache/imozuru)（MIT。`LICENSE` を同梱）を vendor して調整したもの。
経緯・安全性の検討・許可規則は、dotfiles リポジトリの `docs/spec/imozuru.md`。

## 取り込んだ版

- 上流のコミット: `ecb82c71b611872a0f49e783eda3bec987c80d91`（2026-10-21）。
  <https://github.com/MaryCache/imozuru/tree/ecb82c71b611872a0f49e783eda3bec987c80d91>
- 取得: `https://codeload.github.com/MaryCache/imozuru/tar.gz/<上のコミット>`（sha256 `9b5f814e92ac3b2f065142738468b350f42aa78b020f584b2b385b7923c43643`）
- 取り込んだもの: `skills/imozuru/` の `SKILL.md`・`scripts/*.py`・`references/theory.md` と `LICENSE`。
  取り込まなかったもの: `README*`・`examples/`・`assets/`・`tests/`・`.claude-plugin/`

上流の原本のハッシュ（sha256。この版との差分を取るときの基準）:

| ファイル | 上流の sha256 |
| --- | --- |
| `SKILL.md` | `b3a23febb6905ed744bb0684fa05109dbf2bea4fbf8346f5f66f07e3b9826df8` |
| `scripts/chain.py` | `725aa4fa4894820957bc4e8565b7a39f83352ec7b3e0c9704017f5ec77637eca` |
| `scripts/fetch.py` | `94c98d27dd123d5edcfb409b3029f249c14ce51aa03771dd3ff97a4ac8a718aa` |
| `scripts/report.py` | `480276e1d0091eb7ea3f5edca0c7387d3beb9edb3f9da7b79a74063e76dfb3d8` |
| `scripts/watch.py` | `64f529f084d1c644b20755948d91f0c75851bad23e439c1df59b81cbe3dd4c61` |
| `references/theory.md` | `e99ca2f9bf57bdc596c9101a8084c032bf682abdaf8f6ee967f951904028d1e9` |

## この版での変更

上流との差分を小さく保つため、スクリプトは次の最小の変更だけにしている（置換は `scripts/vendor/imozuru_patch.py` で当て直せる）。理由とレビューの結果は dotfiles の `docs/spec/imozuru.md`。

| ファイル | 変更 |
| --- | --- |
| `scripts/imozuru_root.py`（新規） | `confine()`: 書く先を `.tmp/research/` の中に限り、根や中のシンボリックリンク・ハードリンクを拒む。`refuse_secrets()`: 外へ送る文字列の秘匿チェック（`web-search` の `check_query` を借りる）。`youtube_problem()`: YouTube を fetch.py が通さないようにする（fetch_youtube.py だけが通す） |
| `scripts/imozuru_net.py`（新規） | 名前を 1 回だけ引き、公開 IP だけに接続するハンドラ（DNS rebinding 対策。プロキシ宛ての要求だけ stdlib のまま） |
| `scripts/fetch_youtube.py`（新規） | YouTube の字幕を取る別スクリプト。`fetch.py` を YouTube 許可つきで呼ぶ。個人の PC (applejxd) にだけ chezmoi が配り、確認なしの許可には載せない |
| `scripts/fetch.py` | `confine`・`refuse_secrets`・接続の固定ハンドラを通す。YouTube は `youtube_problem()` で止める。`yt-dlp` に `--ignore-config`、外部コマンドの標準入力を遮断 |
| `scripts/watch.py` | `confine`・`refuse_secrets`（`add` の URL）・接続の固定ハンドラ。送る直前に feed の URL も秘匿チェック（`fetch_final`） |
| `scripts/report.py` | `confine` |
| `scripts/chain.py` | `refuse_secrets`（題名・著者名・ID） |
| `references/theory.md` | 変更なし |
| `SKILL.md` | `description` を二重引用符の 1 行にして、使わない場面（`oss-research`・`arxiv-paper-ja`）を足した。置き場を `~/research/` から `.tmp/research/` にした。検索役を、`web-search` スキルの `websearch.py` を使う親に置き換えた。呼び方（`python3 ~/.claude/skills/imozuru/scripts/<名前>.py`）と、上流の `examples/` への参照を直した |

上流を更新するときは、上の sha256 と上流の新しい版を比べ、差分だけを取り込む。
