"""AC-07 / AC-08: 結合・字幕の焼き込み・音量・クレジット。実 ffmpeg を使う。"""

import contextlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import finish  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def make_voice(path, seconds, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            amp = 6000 * (1 + math.sin(2 * math.pi * 3 * i / rate)) / 2
            v = int(amp * math.sin(2 * math.pi * 220 * i / rate))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def loudness(path):
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    m = re.findall(r"I:\s+(-?\d+\.\d+) LUFS", r.stderr)
    return float(m[-1])


class AssTests(unittest.TestCase):
    def test_ass_has_japanese_events_in_order(self):
        ts = {
            "subtitles": [
                {
                    "index": 0,
                    "text": "単眼 SLAM を説明します。",
                    "start_s": 0.0,
                    "end_s": 2.5,
                },
                {"index": 1, "text": "次に地図です。", "start_s": 2.5, "end_s": 4.0},
            ]
        }
        ass = finish.build_ass(ts, width=1920, height=1080, font="Noto Sans CJK JP")
        self.assertIn("PlayResX: 1920", ass)
        self.assertIn(
            "Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,単眼 SLAM を説明します。",
            ass,
        )
        self.assertIn("0:00:02.50,0:00:04.00", ass)

    def test_long_lines_are_wrapped(self):
        text = "あ" * 60 + "。"
        ass = finish.build_ass(
            {"subtitles": [{"text": text, "start_s": 0, "end_s": 5}]},
            width=1920,
            height=1080,
            font="x",
            max_chars=30,
        )
        self.assertIn(r"\N", ass)

    def test_credit_event_sits_at_the_end(self):
        ts = {"subtitles": [{"text": "あ。", "start_s": 0, "end_s": 1}]}
        ass = finish.build_ass(
            ts,
            width=1280,
            height=720,
            font="x",
            credit="VOICEVOX:四国めたん",
            video_sec=10.0,
            credit_sec=4.0,
        )
        self.assertIn("VOICEVOX:四国めたん", ass)
        self.assertIn("0:00:06.00,0:00:10.00", ass)

    def test_credit_text_and_description(self):
        self.assertEqual(finish.credit_text("四国めたん"), "VOICEVOX:四国めたん")
        d = finish.description_text("題名", "VOICEVOX:四国めたん")
        self.assertIn("VOICEVOX:四国めたん", d)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class FinishTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=24:duration=6",
                "-pix_fmt",
                "yuv420p",
                str(self.d / "video_silent.mp4"),
            ],
            check=True,
        )
        make_voice(self.d / "voiceover.wav", 5.0)
        (self.d / "timestamps.json").write_text(
            json.dumps(
                {
                    "total_duration_s": 5.0,
                    "subtitles": [
                        {
                            "index": 0,
                            "text": "単眼 SLAM を説明します。",
                            "start_s": 0.0,
                            "end_s": 2.5,
                            "duration_s": 2.5,
                        },
                        {
                            "index": 1,
                            "text": "次に地図です。",
                            "start_s": 2.5,
                            "end_s": 5.0,
                            "duration_s": 2.5,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def run_finish(self, *extra):
        argv = ["--workdir", str(self.d), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = finish.main(argv)
        return code, out.getvalue()

    def probe(self, name="video.mp4"):
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type:format=duration",
                "-of",
                "json",
                str(self.d / name),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        j = json.loads(r.stdout)
        return {s["codec_type"] for s in j["streams"]}, float(j["format"]["duration"])

    def test_output_has_audio_video_and_target_loudness(self):
        code, out = self.run_finish()
        self.assertEqual(code, 0, out)
        kinds, dur = self.probe()
        self.assertEqual(kinds, {"video", "audio"})
        self.assertAlmostEqual(dur, 6.0, delta=0.2)
        self.assertAlmostEqual(loudness(self.d / "video.mp4"), -16.0, delta=1.0)
        self.assertTrue((self.d / "subtitles.ass").is_file())

    def test_asset_credits_go_into_the_description(self):
        (self.d / "assets").mkdir()
        (self.d / "assets" / "ar.jpg").write_bytes(b"x")
        (self.d / "assets.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "entries": {
                        "assets/ar.jpg": {
                            "出典URL": "https://commons.example/ar",
                            "作者": "A氏",
                            "ライセンス": "CC BY 4.0",
                            "状態": "確認済み",
                            "場面": "動機: AR",
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        code, out = self.run_finish("--assets", "assets.json", "--title", "試験")
        self.assertEqual(code, 0, out)
        text = (self.d / "description.txt").read_text(encoding="utf-8")
        self.assertIn("A氏", text)
        self.assertIn("CC BY 4.0", text)
        self.assertIn("https://commons.example/ar", text)

    def test_credit_goes_into_video_and_description(self):
        code, out = self.run_finish(
            "--credit", "VOICEVOX:四国めたん", "--title", "試験"
        )
        self.assertEqual(code, 0, out)
        self.assertIn(
            "VOICEVOX:四国めたん",
            (self.d / "subtitles.ass").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "VOICEVOX:四国めたん",
            (self.d / "description.txt").read_text(encoding="utf-8"),
        )

    def test_existing_video_is_not_overwritten_without_force(self):
        (self.d / "video.mp4").write_bytes(b"keep")
        code, out = self.run_finish()
        self.assertEqual(code, 2)
        self.assertEqual((self.d / "video.mp4").read_bytes(), b"keep")
        code, out = self.run_finish("--force")
        self.assertEqual(code, 0, out)

    def test_missing_inputs_exit_2(self):
        (self.d / "voiceover.wav").unlink()
        code, out = self.run_finish()
        self.assertEqual(code, 2)
        self.assertIn("voiceover.wav", out)


def frame_gray(path, t, size="320x180"):
    """指定時刻のフレームをグレーで取り出し、バイト列を返す。"""
    r = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-s",
            size,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return r.stdout


def diff_pixels(a, b, w=320, rows=(0, 180), cols=(0, 320), thr=60):
    n = 0
    for y in range(*rows):
        for x in range(*cols):
            if abs(a[y * w + x] - b[y * w + x]) > thr:
                n += 1
    return n


class AssEscapeTests(unittest.TestCase):
    def test_control_sequences_and_newlines_are_neutralized(self):
        ts = {"subtitles": [{"text": "あ\\Nい\nう{\\an8}え", "start_s": 0, "end_s": 1}]}
        ass = finish.build_ass(
            ts, width=640, height=360, font="x", credit="A\\NB{x}", video_sec=5.0
        )
        body = [ln for ln in ass.splitlines() if ln.startswith("Dialogue: 0")][0]
        self.assertNotIn("{", body)
        self.assertNotIn("\\an8", body)
        self.assertEqual(body.count("\\N"), 0)  # 本文の改行は折り返し用の \\N だけ
        cred = [ln for ln in ass.splitlines() if ln.startswith("Dialogue: 1")][0]
        self.assertNotIn("{", cred)
        self.assertNotIn("\\N", cred)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class FinishRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x203060:size=640x360:rate=24:duration=6",
                "-pix_fmt",
                "yuv420p",
                str(self.d / "video_silent.mp4"),
            ],
            check=True,
        )
        make_voice(self.d / "voiceover.wav", 5.0)
        (self.d / "timestamps.json").write_text(
            json.dumps(
                {
                    "total_duration_s": 5.0,
                    "subtitles": [
                        {
                            "index": 0,
                            "text": "単眼 SLAM を説明します。",
                            "start_s": 0.0,
                            "end_s": 5.0,
                            "duration_s": 5.0,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def cli(self, *extra, timeout=90):
        return subprocess.run(
            [
                sys.executable,
                str(HERE.parent / "scripts" / "finish.py"),
                "--workdir",
                str(self.d),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_bgm_does_not_hang_and_keeps_target_loudness(self):
        bgm = self.d / "bgm.wav"
        make_voice(bgm, 3.0)  # ビデオより短い BGM はループする
        r = self.cli("--bgm", str(bgm))  # 無限ループの測定で止まらないと timeout で失敗
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertAlmostEqual(loudness(self.d / "video.mp4"), -16.0, delta=1.0)

    def test_subtitles_are_visible_in_the_output_frames(self):
        r = self.cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        src, out = (
            frame_gray(self.d / "video_silent.mp4", 2.5),
            frame_gray(self.d / "video.mp4", 2.5),
        )
        self.assertGreater(diff_pixels(src, out, rows=(130, 180)), 80)  # 下部に字幕
        self.assertLess(diff_pixels(src, out, rows=(0, 90)), 20)  # 上部は変わらない

    def test_credit_is_visible_only_at_the_end(self):
        r = self.cli("--credit", "VOICEVOX:四国めたん", "--no-subs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        late = diff_pixels(
            frame_gray(self.d / "video_silent.mp4", 5.0),
            frame_gray(self.d / "video.mp4", 5.0),
            rows=(0, 60),
            cols=(160, 320),
            thr=40,
        )
        early = diff_pixels(
            frame_gray(self.d / "video_silent.mp4", 1.0),
            frame_gray(self.d / "video.mp4", 1.0),
            rows=(0, 60),
            cols=(160, 320),
            thr=40,
        )
        self.assertGreater(late, 30)
        self.assertLess(early, 10)

    def test_derived_files_are_not_overwritten_without_force(self):
        (self.d / "subtitles.ass").write_text("keep", encoding="utf-8")
        (self.d / "description.txt").write_text("keep", encoding="utf-8")
        r = self.cli("--title", "t")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual((self.d / "subtitles.ass").read_text(encoding="utf-8"), "keep")
        self.assertEqual(
            (self.d / "description.txt").read_text(encoding="utf-8"), "keep"
        )
        self.assertFalse((self.d / "video.mp4").exists())

    def test_failure_leaves_no_partial_output_and_exits_2(self):
        (self.d / "video_silent.mp4").write_bytes(b"not a video")
        r = self.cli()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse((self.d / "video.mp4").exists())
        self.assertEqual([p.name for p in self.d.glob("*.tmp*")], [])


if __name__ == "__main__":
    unittest.main()
