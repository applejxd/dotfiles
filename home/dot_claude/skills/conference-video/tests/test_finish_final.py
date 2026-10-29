"""finish --final: 公開前の機械チェックが通らなければ、最終動画を作らない。実 ffmpeg を使う。"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import finish  # noqa: E402
import review_sheet  # noqa: E402
from dict_fixture import write_assets, write_dict  # noqa: E402
from test_finish import make_voice  # noqa: E402
from test_release_check import ASSET  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
TS = {
    "total_duration_s": 5.0,
    "subtitles": [
        {
            "index": 0,
            "text": "単眼 SLAM です。",
            "start_s": 0.0,
            "end_s": 5.0,
            "duration_s": 5.0,
        }
    ],
}


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class FinishFinalTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self._old = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(self.d / "home")
        self.addCleanup(
            lambda: (
                os.environ.pop("CONF_VIDEO_HOME", None)
                if self._old is None
                else os.environ.update(CONF_VIDEO_HOME=self._old)
            )
        )
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
                str(self.d / "video_silent.mp4"),
            ],
            check=True,
        )
        make_voice(self.d / "voiceover.wav", 5.0)
        (self.d / "timestamps.json").write_text(
            json.dumps(TS, ensure_ascii=False), "utf-8"
        )
        (self.d / "assets").mkdir()
        (self.d / "assets" / "a.png").write_bytes(b"png")
        write_assets(self.d / "assets.json", {"assets/a.png": ASSET})
        write_dict(self.d / "yomi.json", {"SLAM": "ス'ラム"})

    def run_finish(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = finish.main(["--workdir", str(self.d), *extra])
        return code, out.getvalue()

    def test_final_builds_the_video_when_the_checks_pass(self):
        code, out = self.run_finish(
            "--final", "--credit", "VOICEVOX:四国めたん", "--assets", "assets.json"
        )
        self.assertEqual(code, 0, out)
        self.assertTrue((self.d / "video.mp4").is_file())

    def test_final_refuses_a_provisional_asset(self):
        write_assets(self.d / "assets.json", {"assets/a.png": {**ASSET, "状態": "仮"}})
        code, out = self.run_finish("--final")
        self.assertEqual(code, 2, out)
        self.assertIn("assets/a.png", out)
        self.assertFalse((self.d / "video.mp4").exists())

    def test_final_refuses_remaining_yomi_candidates(self):
        write_dict(self.d / "yomi.json", {"KL": ("ケ'ーエル", "候補", "")})
        code, out = self.run_finish("--final")
        self.assertEqual(code, 2, out)
        self.assertIn("KL", out)
        self.assertFalse((self.d / "video.mp4").exists())

    def test_final_refuses_open_notes(self):
        key = review_sheet.note_key("単眼 SLAM です。")
        review_sheet.notes_store(self.d).update(
            key, None, review_sheet.make_entry(1, "単眼 SLAM です。", "直す")
        )
        code, out = self.run_finish("--final")
        self.assertEqual(code, 2, out)
        self.assertIn("未対応", out)
        review_sheet.change_status(self.d, [key], review_sheet.FIXED)
        time.sleep(0.01)
        self.assertEqual(self.run_finish("--final")[0], 0)

    def test_without_final_the_old_behavior_is_unchanged(self):
        write_assets(self.d / "assets.json", {"assets/a.png": {**ASSET, "状態": "仮"}})
        self.assertEqual(self.run_finish()[0], 0)

    def test_final_cannot_be_combined_with_draft(self):
        code, out = self.run_finish("--final", "--draft")
        self.assertEqual(code, 2, out)
        self.assertIn("--draft", out)


if __name__ == "__main__":
    unittest.main()
