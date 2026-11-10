#!/usr/bin/env python3
"""試験用の偽 manim。`fake_manim.py -ql script.py SceneName` と同じ呼び方で、
SceneName クラスの `LINES = [...]`(使う台本の行)から、実 ffmpeg で短い動画と字幕(srt)を作る。

- 動画の長さ = 使う行の duration_s の合計(timestamps.json)
- クラス本体に `FAIL = True` があれば、失敗(終了コード 1)する
- 呼び出しを作業フォルダの manim_calls.log に追記する(描画の回数を試験で数える)
"""

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv):
    quality = "480p15" if "-ql" in argv else "1080p30"
    rest = [a for a in argv if not a.startswith("-")]
    script, scene = rest[0], rest[1]
    with open("manim_calls.log", "a", encoding="utf-8") as f:
        f.write(scene + "\n")
    tree = ast.parse(Path(script).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == scene)
    attrs = {
        b.targets[0].id: ast.literal_eval(b.value)
        for b in node.body
        if isinstance(b, ast.Assign) and isinstance(b.targets[0], ast.Name)
    }
    if attrs.get("FAIL"):
        print("fake manim: 失敗します", file=sys.stderr)
        return 1
    ts = json.loads(Path("timestamps.json").read_text(encoding="utf-8"))["subtitles"]
    lines = attrs["LINES"]
    out = Path("media/videos") / Path(script).stem / quality
    out.mkdir(parents=True, exist_ok=True)
    dur = sum(ts[i]["duration_s"] for i in lines)
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x203060:size=64x36:rate=15:duration={dur:.3f}",
            "-pix_fmt",
            "yuv420p",
            str(out / f"{scene}.mp4"),
        ],
        check=True,
    )
    t, blocks = 0.0, []
    for n, i in enumerate(lines, 1):
        d = ts[i]["duration_s"]
        blocks.append(f"{n}\n{_t(t)} --> {_t(t + d)}\n{ts[i]['text']}\n")
        t += d
    if attrs.get("NOSRT"):  # 字幕を出さないシーン(前回の srt も残さない)
        (out / f"{scene}.srt").unlink(missing_ok=True)
        return 0
    (out / f"{scene}.srt").write_text("\n".join(blocks), encoding="utf-8")
    return 0


def _t(sec):
    ms = round(sec * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
