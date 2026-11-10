"""読み確認: 台本の各行を ENGINE がどう読むか(仮名)を表示する。"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import readings  # noqa: E402
from fake_voicevox import FakeVoicevox  # noqa: E402
from dict_fixture import write_dict  # noqa: E402


class ReadingsTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "n.txt").write_text(
            "subtitles:\n- 単眼です。次に地図。\n- 二行目。\n", encoding="utf-8"
        )
        write_dict(self.d / "y.json", {"SLAM": "ス'ラム"})

    def run_cli(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = readings.main(["--narration", str(self.d / "n.txt"), *extra])
        return code, out.getvalue()

    def test_prints_one_line_per_subtitle_with_phrases(self):
        with FakeVoicevox() as fake:
            code, out = self.run_cli(
                "--engine-url", fake.url, "--yomi", str(self.d / "y.json")
            )
        self.assertEqual(code, 0, out)
        self.assertIn("1: 単眼です。次に地図。", out)
        self.assertIn(
            "単眼です|次に地図", out
        )  # 偽サーバは 1 文字 1 モーラ。句点で句を区切る
        self.assertIn("2: 二行目。", out)

    def test_unreachable_engine_exits_2(self):
        code, out = self.run_cli(
            "--engine-url", "http://127.0.0.1:9", "--connect-timeout", "1"
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
