"""AC-04 / AC-05: 台本の検査。"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import narration_check as nc  # noqa: E402

sys.path.insert(0, str(HERE))
from dict_fixture import write_dict  # noqa: E402

DICT = {"SLAM": "ス'ラム"}


def write(d, name, text):
    p = Path(d) / name
    p.write_text(text, encoding="utf-8")
    return p


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = nc.main(argv)
    return code, out.getvalue()


class NarrationCheckTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.dict = write_dict(Path(self.d) / "yomi.json", DICT)

    def test_clean_script_passes(self):
        n = write(
            self.d,
            "n.txt",
            "subtitles:\n- 単眼 SLAM を説明します。\n- 次に地図の話です。\n",
        )
        code, out = run([str(n), "--yomi", str(self.dict)])
        self.assertEqual(code, 0, out)

    def test_tex_symbols_and_unknown_latin_are_named(self):
        n = write(
            self.d,
            "n.txt",
            "subtitles:\n- 単眼 SLAM です。\n- Q_3D = Q_T ∪ Q_S を使う。\n- KL 発散です。\n",
        )
        code, out = run([str(n), "--yomi", str(self.dict)])
        self.assertEqual(code, 1)
        self.assertIn("2行目", out)  # 数式記号の行(1 始まり)
        self.assertIn("3行目", out)
        self.assertIn("KL", out)  # 辞書に無い英字
        self.assertNotIn("SLAM が辞書", out)

    def test_over_target_reports_seconds(self):
        line = "あ" * 40
        n = write(
            self.d,
            "n.txt",
            "subtitles:\n" + "".join(f"- {line}。\n" for _ in range(10)),
        )
        code, out = run(
            [
                str(n),
                "--yomi",
                str(self.dict),
                "--target-sec",
                "30",
                "--sec-per-char",
                "0.2",
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("超過", out)
        code, out = run(
            [
                str(n),
                "--yomi",
                str(self.dict),
                "--target-sec",
                "300",
                "--sec-per-char",
                "0.2",
            ]
        )
        self.assertEqual(code, 0, out)

    def test_actual_durations_take_precedence(self):
        n = write(self.d, "n.txt", "subtitles:\n- あいう。\n- えお。\n")
        ts = write(
            self.d, "t.json", json.dumps({"total_duration_s": 50.0, "subtitles": []})
        )
        code, out = run(
            [
                str(n),
                "--yomi",
                str(self.dict),
                "--target-sec",
                "40",
                "--timestamps",
                str(ts),
            ]
        )
        self.assertEqual(code, 1)
        self.assertIn("10.0", out)

    def test_candidate_entries_are_flagged_until_confirmed(self):
        n = write(self.d, "n.txt", "subtitles:\n- KL 発散です。\n")
        csv_path = Path(self.d) / "y.json"
        write_dict(csv_path, {"KL": ("ケーエル", "候補", "")})
        code, out = run([str(n), "--yomi", str(csv_path)])
        self.assertEqual(code, 1)
        self.assertIn("未確認", out)
        code, out = run([str(n), "--yomi", str(csv_path), "--allow-candidates"])
        self.assertEqual(code, 0, out)
        write_dict(csv_path, {"KL": "ケーエ'ル"})
        code, out = run([str(n), "--yomi", str(csv_path)])
        self.assertEqual(code, 0, out)

    def test_missing_subtitles_block_exits_2(self):
        n = write(self.d, "n.txt", "ただの文章\n")
        code, out = run([str(n), "--yomi", str(self.dict)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
