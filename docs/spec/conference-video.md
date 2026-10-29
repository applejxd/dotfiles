# conference-video（学会発表動画風の解説動画を作るスキル）

研究のリポジトリや論文から、3〜5 分の学会発表動画風の日本語解説動画（`video.mp4`・ナレーション・字幕・説明文）を作るスキル。
流れは、取材 → 台本 → 音声（VOICEVOX）→ 描画（Manim）→ 仕上げ → 確認。利用者の承認を、構成案と台本の 2 回で取る。

- **配布の場所**: `home/dot_claude/skills/conference-video/`（`chezmoi apply` で `~/.claude/skills/conference-video/` へ）。Copilot・pi・Codex など、`~/.claude/skills` を読む CLI から使える。
- **正本は skill-lab**（個人のスキル開発用リポジトリの `skills/conference-video/`）。ここへは**複製**（vendor）で、このリポジトリでは編集しない。直すときは skill-lab 側で直して、取り込み直す。
- **取り込んだ版**: skill-lab のコミット `18b5c69`（2026-10-29）の `skills/conference-video/` の追跡ファイル（52 件。`git archive` で取り出した）。キャッシュ（`.ruff_cache`・`__pycache__`）は含めない。
- **中の第三者のコード**: `vendor/manim-skill/`（MIT。Yusuke Miyashita。`vendor/UPSTREAM.md` に取得元・コミット・方針、`LICENSE` を保持）。無改変で使う。

## 依存と契約

| 項目 | 内容 |
| --- | --- |
| 実行環境 | `uv`（描画の依存は `pyproject.toml` / `uv.lock`。Manim・numpy・`manim-videomobject`）。`SKILL.md` の前提確認（`scripts/preflight.py`）が、不足を案内する |
| 音声 | VOICEVOX（ローカルのエンジン。`scripts/voicevox_engine.py`・`tts_generate.py`） |
| 成果物の保存先 | スキルの外: `${CONF_VIDEO_HOME:-$HOME/.conference-video}/<slug>/`。利用者のリポジトリは読むだけで書かない。既存の成果物を上書きしない（`finish.py` は `--force` が無いと止まる） |
| 出典 | 結果の数値・動画は、論文・公式の動画・利用者が渡したものだけ。数値を作らない（クレジットは `references/attribution.md`） |

## このリポジトリでの扱い

- `home/.chezmoiignore.tmpl` で、実行時に作られるもの（`.venv`・`.pytest_cache`・`.ruff_cache`・`.tmp`・`__pycache__`）を配布・取り込みの対象から外す（`powerpoint-studio` と同じ扱い）。
- スキルの試験（`tests/`）は、スキルの中に置いたまま配布する。実行は、スキルのフォルダで `uv run --no-project --with pytest pytest tests -p no:cacheprovider --ignore=tests/e2e`（取り込み時に 253 件とサブテスト 146 件が通ることを確かめた。e2e はブラウザと VOICEVOX が要るので手動・未実施）。このリポジトリの `mise run verify` の対象ではない。
- Python の整形・lint は、上流（skill-lab）の書き方のまま保つため、このリポジトリの `ruff` の対象から外す（`pyproject.toml` の `extend-exclude`）。`vendor/`（manim-skill）の Markdown も、無改変で保つため markdownlint の対象から外す（`.markdownlint-cli2.jsonc` の `ignores`）。
- `SKILL.md` の frontmatter は `name` と `description` だけ（`allowed-tools` なし・`context: fork` なし）。理由は [スキルの frontmatter の方針](skill-frontmatter.md)。

## 更新の手順

skill-lab 側で直してコミットし、このリポジトリで次を実行する（取り込むのは**コミット済みの版**だけ。未コミットの変更があると止まる）。

```bash
python3 scripts/sync_skill_lab.py conference-video --check   # 差分を見るだけ（差分があれば終了コード 1）
python3 scripts/sync_skill_lab.py conference-video           # 置き換え。上の「取り込んだ版」も更新する
```

実行時に生える `.venv` などは消さない。置き換えたら feature で commit → finish する（スキル自前の試験は、元で保証する）。
シンボリックリンクにしない理由: skill-lab は、一部のマシンにしか無い作業用のリポジトリで、無いマシン（Pi・別の機）ではリンクが切れる。pi のサンドボックスも、作業ツリーの外の `~/src` を読めるとは限らない。
