"""聞き取りシート(review.csv)と指摘(notes.json): 行・時刻・本文・読み・指摘。

review.csv は書き出し専用(Excel で見る)。指摘の正本は notes.json で、窓口(state_store)だけが書く。
"""

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import review_sheet  # noqa: E402
import state_store  # noqa: E402

TS = {
    "total_duration_s": 75.0,
    "subtitles": [
        {
            "index": 0,
            "text": "単眼 SLAM です。",
            "start_s": 0.0,
            "end_s": 4.5,
            "duration_s": 4.5,
            "phrases": [{"text": "タンガン"}, {"text": "スラム"}, {"text": "デス"}],
        },
        {
            "index": 1,
            "text": "次に地図です。",
            "start_s": 4.5,
            "end_s": 75.0,
            "duration_s": 70.5,
            "phrases": [{"text": "ツギニ"}, {"text": "チズデス"}],
        },
    ],
}


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = review_sheet.main(argv)
    return code, out.getvalue()


class ReviewSheetTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / "timestamps.json").write_text(
            json.dumps(TS, ensure_ascii=False), encoding="utf-8"
        )

    def rows(self, name="review.csv"):
        with (self.d / name).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def add_note(self, line, note, text, at="2026-10-29T08:00:00+09:00", status="open"):
        e = review_sheet.make_entry(line, text, note, status=status, at=at)
        review_sheet.notes_store(self.d).update(review_sheet.note_key(text), None, e)

    def test_sheet_has_time_text_reading_and_empty_note(self):
        code, out = run(["--workdir", str(self.d)])
        self.assertEqual(code, 0, out)
        rows = self.rows()
        self.assertEqual(rows[0], ["行", "開始", "本文", "読み", "指摘"])
        self.assertEqual(
            rows[1], ["1", "0:00", "単眼 SLAM です。", "タンガン|スラム|デス", ""]
        )
        self.assertEqual(rows[2][:2], ["2", "0:04"])
        self.assertEqual(rows[2][3], "ツギニ|チズデス")

    def test_time_format_handles_minutes(self):
        ts = {
            "subtitles": [
                {"index": 0, "text": "あ", "start_s": 75.4, "end_s": 80, "phrases": []}
            ]
        }
        (self.d / "timestamps.json").write_text(json.dumps(ts), encoding="utf-8")
        run(["--workdir", str(self.d)])
        self.assertEqual(self.rows()[1][1], "1:15")

    def test_sheet_is_an_export_of_notes_and_is_regenerated_every_time(self):
        self.add_note(2, "ここで間が長い", "次に地図です。")
        run(["--workdir", str(self.d)])
        self.assertEqual(self.rows()[2][4], "ここで間が長い")
        # 手で書き込んでも取り込まない: 作り直すと正本(notes.json)の内容に戻る(上書きしてよい)
        (self.d / "review.csv").write_text(
            "行,開始,本文,読み,指摘\n1,0:00,a,b,手書き\n", encoding="utf-8-sig"
        )
        code, out = run(["--workdir", str(self.d)])
        self.assertEqual(code, 0, out)
        rows = self.rows()
        self.assertEqual(rows[1][4], "")
        self.assertEqual(rows[2][4], "ここで間が長い")

    def test_notes_lists_notes_from_notes_json_in_line_order(self):
        self.add_note(2, "ここで間が長い", "次に地図です。")
        self.add_note(1, "読みを確認", "単眼 SLAM です。")
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        self.assertLess(out.index("1行目"), out.index("2行目"))
        self.assertIn("ここで間が長い", out)
        self.assertIn("指摘 2 件", out)

    def test_notes_with_none_prints_zero(self):
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        self.assertIn("指摘 0 件", out)

    def test_notes_marks_a_note_whose_line_text_changed(self):
        self.add_note(1, "読みを確認", "古い本文")
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        self.assertIn(
            "古い", out
        )  # 台本が変わった後の指摘は、別の行へ付け直さず「古い」と示す

    def test_notes_are_judged_stale_against_the_current_narration_not_the_old_timestamps(
        self,
    ):
        """D-04 / C-05: 台本を直しただけ(再合成前)でも、「古い」の判定はいまの narration.txt を基準にする。"""
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 単眼 SLAM です。\n- 次に地図です。\n", encoding="utf-8"
        )
        self.add_note(1, "読み", "単眼 SLAM です。")
        self.add_note(2, "間", "次に地図です。")
        # 台本の 1 行目だけを直す(timestamps.json は古いまま)
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 経路推定です。\n- 次に地図です。\n", encoding="utf-8"
        )
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        first = out.split("2行目")[0]
        self.assertIn("古い", first)  # 1 行目は古い
        self.assertNotIn("古い", out.split("2行目")[1])  # 2 行目は不変

    def test_exported_sheet_marks_stale_notes_instead_of_attaching_them_silently(self):
        """C-05: review.csv も、本文が変わった行の指摘を無印で結合しない。"""
        self.add_note(1, "読みを確認", "もっと古い本文")
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 単眼 SLAM です。\n- 次に地図です。\n", encoding="utf-8"
        )
        run(["--workdir", str(self.d)])
        cell = self.rows()[1][4]
        self.assertIn("読みを確認", cell)
        self.assertIn("古い", cell)

    def test_corrupt_notes_json_stops_without_change(self):
        (self.d / "notes.json").write_text("{壊れ", encoding="utf-8")
        for argv in (["--workdir", str(self.d), "--notes"], ["--workdir", str(self.d)]):
            code, out = run(argv)
            self.assertEqual(code, 2, out)
        self.assertEqual((self.d / "notes.json").read_text(encoding="utf-8"), "{壊れ")

    def test_missing_timestamps_exits_2(self):
        (self.d / "timestamps.json").unlink()
        code, out = run(["--workdir", str(self.d)])
        self.assertEqual(code, 2)


class NotesStoreTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)

    def test_key_is_made_from_the_line_text(self):
        k = review_sheet.note_key("単眼 SLAM です。")
        self.assertEqual(k, review_sheet.note_key("単眼 SLAM です。"))
        self.assertNotEqual(k, review_sheet.note_key("別の行"))
        self.assertRegex(k, r"^n[0-9a-f]{10}$")

    def test_validation_of_entries(self):
        st = review_sheet.notes_store(self.d)
        good = review_sheet.make_entry(
            1, "本文", "指摘", at="2026-10-29T00:00:00+09:00"
        )
        for key, val in [
            ("1", good),  # 旧形式(行番号キー)
            ("nzzzzzzzzzz", good),
            (review_sheet.note_key("本文"), {**good, "note": ""}),
            (review_sheet.note_key("別"), good),  # キーが本文と合わない
            (review_sheet.note_key("本文"), {**good, "status": "閉じた"}),
            (review_sheet.note_key("本文"), {**good, "line": 0}),
            (review_sheet.note_key("本文"), {**good, "extra": 1}),
            (review_sheet.note_key("本文"), {"note": "x"}),
        ]:
            with self.subTest(key=key, val=val):
                with self.assertRaises(state_store.Invalid):
                    st.update(key, None, val)
        self.assertEqual(st.read().entries, {})
        st.update(review_sheet.note_key("本文"), None, good)
        self.assertEqual(list(st.read().entries), [review_sheet.note_key("本文")])

    def test_read_notes_follows_the_text_and_marks_missing_text_as_stale(self):
        st = review_sheet.notes_store(self.d)
        for line, text in [(1, "同じ"), (2, "古い"), (3, "行が無くなった")]:
            st.update(
                review_sheet.note_key(text),
                None,
                review_sheet.make_entry(line, text, f"n{line}", at="x"),
            )
        # 台本: 「同じ」が 2 行目へ動き、「古い」は変わった
        got = {
            n["note"]: (n["line"], n["stale"], n["moved"])
            for n in review_sheet.read_notes(self.d, ["新しい", "同じ"])
        }
        self.assertEqual(
            got,
            {"n1": (2, False, True), "n2": (2, True, False), "n3": (3, True, False)},
        )


class NoteLifecycleTests(unittest.TestCase):
    """指摘の状態(open / fixed)と CLI(--fix / --reopen / --remove / --all)。直した指摘が残り続けない。"""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 単眼 SLAM です。\n- 次に地図です。\n", encoding="utf-8"
        )
        self.st = review_sheet.notes_store(self.d)
        self.a = review_sheet.note_key("単眼 SLAM です。")
        self.b = review_sheet.note_key("次に地図です。")
        self.st.update(
            self.a,
            None,
            review_sheet.make_entry(1, "単眼 SLAM です。", "読みを確認", at="x"),
        )
        self.st.update(
            self.b,
            None,
            review_sheet.make_entry(2, "次に地図です。", "間が長い", at="x"),
        )

    def test_notes_show_ids_and_open_ones_only_by_default(self):
        run(["--workdir", str(self.d), "--fix", self.a])
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        self.assertIn(self.b, out)
        self.assertNotIn(self.a, out)
        self.assertIn("指摘 1 件", out)
        code, out = run(["--workdir", str(self.d), "--notes", "--all"])
        self.assertIn(self.a, out)
        self.assertIn("対応済み", out)

    def test_fix_reopen_and_remove(self):
        code, out = run(["--workdir", str(self.d), "--fix", self.a, self.b])
        self.assertEqual(code, 0, out)
        e = self.st.read().entries
        self.assertEqual(e[self.a]["status"], "fixed")
        self.assertIn("fixed_at", e[self.a])
        code, out = run(["--workdir", str(self.d), "--reopen", self.a])
        self.assertEqual(code, 0, out)
        e = self.st.read().entries
        self.assertEqual(e[self.a]["status"], "open")
        self.assertNotIn("fixed_at", e[self.a])
        code, out = run(["--workdir", str(self.d), "--remove", self.b])
        self.assertEqual(code, 0, out)
        self.assertEqual(list(self.st.read().entries), [self.a])

    def test_unknown_id_exits_2_and_changes_nothing(self):
        before = (self.d / "notes.json").read_bytes()
        code, out = run(["--workdir", str(self.d), "--fix", self.a, "nffffffffff"])
        self.assertEqual(code, 2, out)
        self.assertIn("nffffffffff", out)
        self.assertEqual((self.d / "notes.json").read_bytes(), before)

    def test_inserting_a_line_does_not_make_the_notes_stale(self):
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 増えた行です。\n- 単眼 SLAM です。\n- 次に地図です。\n",
            encoding="utf-8",
        )
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("古い", out)
        self.assertIn("2行目", out)  # 単眼 SLAM の行が 2 行目へ動いた
        self.assertIn("3行目", out)

    def test_a_note_does_not_close_itself_when_the_text_changes(self):
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 経路推定です。\n- 次に地図です。\n", encoding="utf-8"
        )
        code, out = run(["--workdir", str(self.d), "--notes"])
        self.assertIn(self.a, out)  # もともとの指摘を失わず、「古い」と示す
        self.assertIn("古い", out)
        self.assertEqual(self.st.read().entries[self.a]["status"], "open")


if __name__ == "__main__":
    unittest.main()
