# vendor/manim-skill

- 取得元: <https://github.com/Yusuke710/manim-skill>
- コミット: `a0048d9e265499038f34a9aa58ff16d306b5034c`(2026-10-07)
- ライセンス: MIT(Copyright (c) 2025 Yusuke Miyashita)。
  同階層の `LICENSE` を保持する
- 取得日: 2026-10-27
- 取り込んだもの: `SKILL.md`(参照用)と `tools/` の 5 ファイル。
  `README.md` の GIF と `video_viewer.png` は除外

## 方針

- **無改変で使う**:
  - `tools/lint-subtitles.py`
    (`add_subcaption` の時間の模擬検査。言語に依存しない)
  - `tools/video_viewer.py` と `ui.html`(動画ビューア)
- **使わない**: `tools/tts-generate.py`(Kokoro 専用)。
  `scripts/tts_generate.py` が VOICEVOX 版で置き換える。
  入出力の形式(`narration.txt`、`timestamps.json`)は互換にする
- vendor 内のファイルは編集しない。差分が要るときは `scripts/` に
  自前の版を置く
- 上流の Markdown(`SKILL.md`、`tools/README.md`)は、このリポジトリの
  markdownlint(1 行 80 文字など)に適合しない。無改変を優先して直さない
- 更新するときは取得元のコミットを上に追記し、下のハッシュを照合する

## 無改変の確認(sha256)

2026-10-27、取り込んだ 7 ファイルを、上流のクローン(コミット `a0048d9`)と
`cmp` で突き合わせ、すべて同一だった。

```text
685bbbfec0e0d00a24b85d15700a425fe7ba3d578084fc9d0dde4de7224034b7  LICENSE
40ffbd7dc500a0e4f5a2dd45176db88a64814d3943f7c6e58ad62ae031eee288  SKILL.md
f95aa64a4b76789479d31a3b21dbb46111232394a88acaec81f30ec9dfdbd516  tools/README.md
ae265f17feea51e6fb64512f1cac85d33cfe37e84385e1fba22a119cffe4a5e5  tools/lint-subtitles.py
193d0ea071b74a5d0930f204867c34625897f912f93b14bb5c982b2bad02137c  tools/tts-generate.py
a51d76da592a72bfde0cae1a25dc1f8b4cfaa699461d449b010e247072b64157  tools/ui.html
50045c88d76efa4ac45f1d5b8d0184525f651ce3b513874c428e8351ea42dc24  tools/video_viewer.py
```

照合は `sha256sum` で行う:

```bash
cd skills/conference-video/vendor/manim-skill && sha256sum -c <<'EOF'
(上の表を貼る)
EOF
```
