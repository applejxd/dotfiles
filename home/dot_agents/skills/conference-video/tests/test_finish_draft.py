"""finish --draft: 下書き動画(DRAFT 表示つき・別名・video.mp4 に触れない)。実 ffmpeg を使う。"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import finish  # noqa: E402
from test_finish import make_voice  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
TS = {
    "total_duration_s": 5.0,
    "subtitles": [
        {
            "index": 0,
            "text": "単眼 SLAM です。",
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
}


class DraftAssTests(unittest.TestCase):
    def test_draft_mark_covers_the_whole_video_only_when_asked(self):
        ts = {"subtitles": [{"text": "あ。", "start_s": 0, "end_s": 1}]}
        plain = finish.build_ass(ts, 640, 360, "x", video_sec=8.0)
        self.assertNotIn("DRAFT", plain)
        ass = finish.build_ass(ts, 640, 360, "x", video_sec=8.0, draft=True)
        marks = [
            ln for ln in ass.splitlines() if "DRAFT" in ln and ln.startswith("Dialogue")
        ]
        self.assertEqual(len(marks), 1)
        self.assertIn("0:00:00.00,0:00:08.00", marks[0])
        self.assertIn("Style: Draft,", ass)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class FinishDraftTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        subprocess.run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x203060:size=320x180:rate=15:duration=6",
                "-pix_fmt",
                "yuv420p",
                str(self.d / "draft_silent.mp4"),
            ],
            check=True,
        )
        make_voice(self.d / "voiceover.wav", 5.0)
        (self.d / "timestamps.json").write_text(
            json.dumps(TS, ensure_ascii=False), encoding="utf-8"
        )

    def run_finish(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = finish.main(["--workdir", str(self.d), *extra])
        return code, out.getvalue()

    def test_draft_writes_draft_mp4_and_leaves_the_final_alone(self):
        (self.d / "video.mp4").write_bytes(b"final")
        code, out = self.run_finish("--draft")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.d / "draft.mp4").stat().st_size > 1000)
        self.assertEqual((self.d / "video.mp4").read_bytes(), b"final")
        self.assertIn("DRAFT", (self.d / "subtitles.draft.ass").read_text("utf-8"))
        self.assertFalse((self.d / "subtitles.ass").exists())
        self.assertFalse((self.d / "description.txt").exists())
        self.assertIn("下書き", out)

    def test_draft_can_be_rebuilt_without_force(self):
        self.assertEqual(self.run_finish("--draft")[0], 0)
        code, out = self.run_finish("--draft")
        self.assertEqual(code, 0, out)

    def test_draft_refuses_to_write_the_final_name(self):
        code, out = self.run_finish("--draft", "--out", "video.mp4")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.d / "video.mp4").exists())
        self.assertFalse((self.d / "draft.mp4").exists())

    def test_draft_keeps_the_video_length(self):
        self.assertEqual(self.run_finish("--draft")[0], 0)
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(self.d / "draft.mp4"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertAlmostEqual(float(r.stdout), 6.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()
