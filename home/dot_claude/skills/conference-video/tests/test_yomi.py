"""AC-06: 読み辞書の正規化と登録(冪等)。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import speech  # noqa: E402
import yomi  # noqa: E402
from fake_voicevox import FakeVoicevox  # noqa: E402
from voicevox_engine import Engine  # noqa: E402


class YomiTests(unittest.TestCase):
    def test_surface_is_normalized_to_fullwidth(self):
        self.assertEqual(yomi.to_fullwidth("SLAM"), "ＳＬＡＭ")
        self.assertEqual(yomi.to_fullwidth("ISAM2"), "ＩＳＡＭ２")
        self.assertEqual(yomi.to_fullwidth("MASt3R"), "ＭＡＳｔ３Ｒ")
        self.assertEqual(yomi.to_fullwidth("単眼"), "単眼")

    def test_load_rejects_bad_entries(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "y.json"
            p.write_text(json.dumps({"SLAM": {"pron": "スラム"}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                yomi.load(p)
            p.write_text(
                json.dumps({"SLAM": {"pron": "slam", "accent": 1}}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):  # 読みはカタカナのみ
                yomi.load(p)

    def test_register_is_idempotent(self):
        entries = {
            "SLAM": {"pron": "スラム", "accent": 1},
            "KL": {"pron": "ケーエル", "accent": 3},
        }
        with FakeVoicevox() as fake:
            eng = Engine(fake.url)
            self.assertEqual(yomi.register(eng, entries), 2)
            self.assertEqual(yomi.register(eng, entries), 0)
            self.assertEqual(set(fake.words), {"ＳＬＡＭ", "ＫＬ"})
            entries["SLAM"]["pron"] = "エスラム"
            self.assertEqual(yomi.register(eng, entries), 1)  # 変更は反映する
            self.assertEqual(len(fake.words), 2)  # 旧語を消して置き換え、重複しない
            self.assertEqual(fake.words["ＳＬＡＭ"][0], "エスラム")

    def test_words_are_registered_with_high_priority(self):
        with FakeVoicevox() as fake:
            yomi.register(Engine(fake.url), {"AR": {"pron": "エーアール", "accent": 3}})
            self.assertEqual(fake.words["ＡＲ"][2], 9)

    def test_priority_change_replaces_existing_word(self):
        with FakeVoicevox() as fake:
            fake.words["ＡＲ"] = ("エーアール", 3, 5)  # 優先度が低い既存登録
            n = yomi.register(
                Engine(fake.url), {"AR": {"pron": "エーアール", "accent": 3}}
            )
            self.assertEqual(n, 1)
            self.assertEqual(len(fake.words), 1)
            self.assertEqual(fake.words["ＡＲ"][2], 9)

    def test_compound_surface_is_registered_without_hyphen_and_text_is_rewritten(self):
        entries = {
            "SLAM-MER": {
                "pron": "スラマー",
                "accent": 0,
                "status": "確認済み",
                "note": "",
            },
            "7-Scenes": {
                "pron": "セブンシーンズ",
                "accent": 0,
                "status": "確認済み",
                "note": "",
            },
        }
        self.assertEqual(yomi.engine_surface("SLAM-MER"), "SLAMMER")
        self.assertEqual(yomi.engine_surface("KL"), "KL")
        self.assertEqual(yomi.engine_surface("疎な"), "疎な")
        self.assertEqual(speech.prepare("SLAM-MER を紹介", entries), "SLAMMERを紹介")
        self.assertEqual(speech.prepare("SLAM と MER", entries), "SLAMとMER")
        self.assertEqual(speech.prepare("7-Scenes でも", entries), "7Scenesでも")
        # ENGINE の辞書はハイフン入りの表記に一致しないので、ハイフンを除いた形で登録する
        with FakeVoicevox() as fake:
            yomi.register(Engine(fake.url), entries)
            self.assertIn("ＳＬＡＭＭＥＲ", fake.words)
            self.assertIn("７Ｓｃｅｎｅｓ", fake.words)
            self.assertNotIn("ＳＬＡＭ－ＭＥＲ", fake.words)

    def test_stripped_form_in_the_text_is_also_covered(self):
        entries = {
            "7-Scenes": {
                "pron": "セブンシーンズ",
                "accent": 0,
                "status": "確認済み",
                "note": "",
            }
        }
        self.assertEqual(yomi.missing("7Scenes でも", entries), [])
        self.assertEqual(yomi.present_compounds("7Scenes でも", entries), ["7-Scenes"])

    def test_compound_surface_covers_its_tokens(self):
        entries = {
            "SLAM-MER": {
                "pron": "スラマー",
                "accent": 0,
                "status": "確認済み",
                "note": "",
            },
            "7-Scenes": {
                "pron": "セブンシーンズ",
                "accent": 0,
                "status": "確認済み",
                "note": "",
            },
            "C": {"pron": "シー", "accent": 1, "status": "確認済み", "note": ""},
        }
        # 複合語を 1 つの表記として扱う(ハイフンでつながる語を分けない)
        self.assertEqual(yomi.missing("SLAM-MER を紹介します", entries), [])
        self.assertEqual(yomi.missing("7-Scenes を使う", entries), [])
        # 分かれて現れるときは、複合語の表記ではない
        self.assertEqual(yomi.missing("SLAM と MER", entries), ["SLAM", "MER"])
        # 1 文字の表記(C)が他の語の一部を隠さない
        self.assertEqual(yomi.missing("CVPR で発表", entries), ["CVPR"])

    def test_present_compounds_report_candidates(self):
        entries = {
            "SLAM-MER": {"pron": "スラマー", "accent": 0, "status": "候補", "note": ""},
        }
        self.assertEqual(yomi.present_compounds("SLAM-MER です", entries), ["SLAM-MER"])
        self.assertEqual(yomi.present_compounds("SLAM です", entries), [])

    def test_latin_tokens_and_missing(self):
        text = "単眼 SLAM では KL 発散と ISAM2 を使う"
        self.assertEqual(yomi.latin_tokens(text), ["SLAM", "KL", "ISAM2"])
        self.assertEqual(
            yomi.missing(text, {"SLAM": {"pron": "スラム", "accent": 1}}),
            ["KL", "ISAM2"],
        )

    def test_digest_changes_with_content(self):
        a = {"SLAM": {"pron": "スラム", "accent": 1}}
        b = {"SLAM": {"pron": "スラム", "accent": 2}}
        self.assertNotEqual(yomi.digest(a), yomi.digest(b))
        self.assertEqual(yomi.digest(a), yomi.digest(dict(a)))


if __name__ == "__main__":
    unittest.main()
