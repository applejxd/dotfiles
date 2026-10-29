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


class SpokenDifferenceTests(unittest.TestCase):
    """表示(字幕)と ENGINE に渡す文が違う行を、規則名つきで事前に示す(既定は要約のみ、0 を返す)。"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.dict = write_dict(Path(self.d) / "yomi.json", {"SLAM-MER": "スラ'マー"})
        self.n = write(
            self.d,
            "n.txt",
            "subtitles:\n- 精度が 3 倍になります。\n- SLAM-MER を紹介します。\n- 次に地図です。\n",
        )

    def test_summary_only_by_default_and_exit_zero(self):
        code, out = run([str(self.n), "--yomi", str(self.dict)])
        self.assertEqual(code, 0, out)
        self.assertIn("読み上げ前の整形: 2 行", out)
        self.assertIn("ja-space", out)
        self.assertIn("compound-hyphen", out)
        self.assertNotIn("読み上げでは", out)  # 一覧は --show-spoken で

    def test_show_spoken_lists_each_line_with_the_rule_names(self):
        code, out = run([str(self.n), "--yomi", str(self.dict), "--show-spoken"])
        self.assertEqual(code, 0, out)
        self.assertIn("1行目", out)
        self.assertIn("精度が3倍になります。", out)
        self.assertIn("2行目", out)
        self.assertIn("SLAMMERを紹介します。", out)
        self.assertNotIn("3行目", out)  # 変わらない行は出さない

    def test_strict_turns_the_difference_into_an_issue(self):
        code, out = run([str(self.n), "--yomi", str(self.dict), "--strict"])
        self.assertEqual(code, 1, out)
        self.assertIn("読み上げでは", out)

    def test_no_difference_prints_nothing_about_it(self):
        n = write(self.d, "m.txt", "subtitles:\n- 次に地図です。\n")
        code, out = run([str(n), "--yomi", str(self.dict), "--strict"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("整形", out)


class KanaReadingInSubtitleTests(unittest.TestCase):
    """字幕は正式名称で書き、読みは辞書に任せる。読み(カタカナ)を字幕に書いて音を合わせると、字幕が誤表記になる。"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.dict = write_dict(
            Path(self.d) / "yomi.json",
            {"SLAM": "ス'ラム", "SLAM-MER": "スラ'マー", "EL": "エ'ル"},
        )

    def check(self, line, *extra):
        n = write(self.d, "n.txt", f"subtitles:\n- {line}\n")
        return run([str(n), "--yomi", str(self.dict), *extra])

    def test_reading_written_instead_of_the_official_name_is_named(self):
        code, out = self.check("スラムを使います。")
        self.assertEqual(code, 1, out)
        self.assertIn("1行目", out)
        self.assertIn("スラム", out)
        self.assertIn("SLAM", out)  # 直すべき正式名称を示す

    def test_compound_official_name_is_suggested(self):
        code, out = self.check("スラマーを紹介します。")
        self.assertEqual(code, 1, out)
        self.assertIn("SLAM-MER", out)

    def test_official_name_with_a_gloss_is_not_flagged(self):
        code, out = self.check("SLAM-MER(スラマー)を紹介します。")
        self.assertEqual(code, 0, out)

    def test_reading_inside_a_longer_katakana_word_is_not_flagged(self):
        code, out = self.check("エルサルバドルの話です。")
        self.assertEqual(code, 0, out)

    def test_can_be_allowed_per_run(self):
        code, out = self.check("スラムを使います。", "--allow-kana")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
