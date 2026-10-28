# 描画のパターン(Manim)

試験(SLAM-MER、6 シーン・25 行)で動作を確認した書き方。

## 設定

```python
from manim_videomobject import VideoMobject
from manim_videomobject.compat import ensure_pillow_compat

ensure_pillow_compat()  # ★ 画像(ImageMobject)を使うスクリプトは必ず呼ぶ

HQ = os.environ.get("CONF_VIDEO_QUALITY") == "high"
config.pixel_width, config.pixel_height = (1920, 1080) if HQ else (854, 480)
config.frame_rate = 30 if HQ else 15
config.frame_width, config.frame_height = 16, 9
config.background_color = "#FFFFFF"   # 論文スライドに合わせた白地
FONT = "Noto Sans CJK JP"
```

- **画像を使うときは `ensure_pillow_compat()` をスクリプトの先頭で呼ぶ**。この環境の Pillow
  (13.0.0)では、Manim の `ImageMobject` が `ValueError: Invalid mode for data type` で
  描けない(2026-10-27 に SLAM-MER の試験で確認)。`VideoMobject` は作成時に
  同じパッチを当てるが、それより前に画像を使うと失敗する
- スクリプト内の `config` は CLI の `-ql` / `-qh` より後に効く。
  画質は環境変数 `CONF_VIDEO_QUALITY=high` で切り替える
  (確認: `CONF_VIDEO_QUALITY=high manim -qh script.py Scene2_Map` で
  `media/videos/script/1080p30/` に 1920x1080、30 fps が出た。
  13.9 秒のシーンが 21 秒、メモリ約 0.7 GB)
- 解像度を変えると出力フォルダ名が変わる(`480p15` → `1080p30`)。
  `concat.txt` のパスを合わせる
- 字幕は `finish.py` が下端に焼く。図は画面の下 1 割を空ける
  (`y > -2.8` に収める)。文字数の多い行は 3 行になるので、
  さらに余裕を見る(約 `y > -2.5`)
- 数式は `MathTex`、日本語は `Text(..., font=FONT)`。文字を長く並べるときは
  `Text` を使い、`MathTex` の中に日本語を入れない

## 時間予算: Clock パターン

`timestamps.json` を読み、行ごとの `duration_s` に動きを収める。

```python
_TS = json.load(open("timestamps.json", encoding="utf-8"))["subtitles"]
T = [s["text"] for s in _TS]
D = [s["duration_s"] for s in _TS]


class Clock:
    def __init__(self, scene, i):
        self.scene, self.i, self.used = scene, i, 0.0
        scene.add_subcaption(T[i], duration=D[i])

    def play(self, *anims, rt=1.0, **kw):
        self.scene.play(*anims, run_time=rt, **kw)
        self.used += rt

    def wait(self, t):
        if t > 0.02:
            self.scene.wait(t)
        self.used += t

    def end(self):
        rest = D[self.i] - self.used
        if rest > 0.02:        # Manim は wait(0) を拒否する
            self.scene.wait(rest)
```

- 1 行 = 1 つの `Clock`。`c.play(..., rt=秒)` の合計が `D[i]` を
  超えると、vendor のリンタが「animation exceeds subtitle timing」で止める
- `play(..., run_time=rt)` は、渡した全アニメーションの長さを `rt` に
  そろえる。長いアニメーションと短いフェードを同時に入れると、
  フェードも長くなる
- 台本を直して `tts_generate.py` をやり直すと `D` が変わる。
  スクリプトは再実行するだけで追従する

## 実動画の貼り込み(結果部)

1. ffmpeg で、必要な範囲を切り抜いて 24 fps にそろえる(音声は捨てる)

   ```bash
   ffmpeg -y -ss 165 -t 11.5 -i official.mp4 \
     -vf "crop=1920:780:0:150,fps=24,scale=1280:-2" \
     -an -c:v libx264 -crf 20 -pix_fmt yuv420p clips/rt1.mp4
   ```

2. `manim_videomobject.VideoMobject` で貼る(Manim 本体には無い)

   ```python
   clip = VideoMobject("clips/rt1.mp4", fps=15, start=0, end=6,
                       max_width=1280).scale_to_fit_width(13.5)
   self.add(clip)
   c.play(clip.play(run_time=6), rt=6)
   ```

3. 1 つのクリップを 2 行にまたがせない。行ごとに `start` / `end` を
   分けて `VideoMobject` を作り、`self.remove` と `self.add` で
   入れ替える(境界で絵が途切れない)
4. 出典と許可の表示を画面に残す
5. `VideoMobject` はフレームを JPEG に展開する。長い動画は
   切り出してから渡す(1 クリップ 10〜15 秒が目安)

## 画像・動画素材の貼り込み(動機・課題)

- 写真は `ImageMobject`、短い動画は結果部と同じ `VideoMobject`(上の「実動画の貼り込み」)
- 大きさは画面幅の 6 割程度までにし、字幕(下 1 割)と重ならないようにする
- 出典(作者・ライセンス)を素材の隣に小さく出す(例: `Photo: A / CC BY 4.0`)。
  同じ内容が素材台帳 `assets.json` にある
- 1 場面の長さは台本の行の `duration_s` に合わせる(動画はこの長さに切り出す)

## 冒頭の概要図と使い回し

- 概要図はブロック(`VGroup`)として一度作り、シーンをまたいで使い回す。
  ブロックを返す関数(`def overview(): ...`)にして、シーンごとに縮小して隔に
  置く
- 理論部では、いま説明しているブロックの枠を強調(色を変える、`Indicate`)し、
  他のブロックは薄くする
- 論文の図を使うときは、許可を `brief.md` に記録し、出典を画面に入れる

## ほかの要素

- 配色は 3〜4 色に絞り、意味に固定する(例: 青 = 時間、赤 = 空間)
- 棒グラフは `Rectangle` と `Text` で自作する(論文の表の数値を
  そのまま使う。丸めない。比などの換算は画面に式を出す)
- 点の散らばりは `random.Random(固定シード)` で再現できるようにする
- 図の説明の文字は短く。ナレーションと同じ文を画面に置かない
