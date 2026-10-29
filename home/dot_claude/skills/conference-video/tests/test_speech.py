"""読み上げ前処理(speech.py): 表示用の書き方を ENGINE に渡す前に整える唯一の入口。

字幕は変えず、ENGINE に渡す文だけを規則の表で整える。規則は名前つきで、例を実行して確かめる。
"""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import finish  # noqa: E402
import speech  # noqa: E402

ENTRIES = {
    "SLAM-MER": {"pron": "スラ'マー", "accent": 2, "status": "確認済み", "note": ""},
    "7-Scenes": {
        "pron": "セブンシーンズ",
        "accent": 0,
        "status": "確認済み",
        "note": "",
    },
}
SCRIPTS = HERE.parent / "scripts"


class RuleTableTests(unittest.TestCase):
    """規則の表は、理由と例を持ち、例が実際にその通りに変換される(文書と実装がずれない)。"""

    def test_every_rule_has_id_reason_and_a_working_example(self):
        ids = [r.id for r in speech.RULES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 2)
        for r in speech.RULES:
            with self.subTest(rule=r.id):
                self.assertRegex(r.id, r"^[a-z][a-z0-9-]*$")
                self.assertTrue(r.reason)
                before, after = r.example
                self.assertNotEqual(before, after)
                self.assertEqual(speech.prepare(before, ENTRIES), after)
                self.assertIn(r.id, speech.applied(before, ENTRIES))

    def test_rules_are_documented_in_the_reference(self):
        doc = (HERE.parent / "references" / "yomi.md").read_text(encoding="utf-8")
        for r in speech.RULES:
            self.assertIn(r.id, doc, f"{r.id} を references/yomi.md に書く")


class PrepareTests(unittest.TestCase):
    def test_spaces_next_to_japanese_are_removed(self):
        cases = {
            "精度が 3 倍になる": "精度が3倍になる",
            "CVPR 2026 で発表": "CVPR 2026で発表",  # 英数字同士の空白は残す
            "単眼　SLAM 　です": "単眼SLAMです",
            "GPU を 3 枚": "GPUを3枚",
            "Sparse Voxel Grid": "Sparse Voxel Grid",
            "先頭 と末尾 ": "先頭と末尾 ",
        }
        for src, want in cases.items():
            self.assertEqual(speech.prepare(src, {}), want, src)

    def test_compound_words_are_sent_without_the_hyphen(self):
        self.assertEqual(speech.prepare("SLAM-MER を紹介", ENTRIES), "SLAMMERを紹介")
        self.assertEqual(speech.prepare("7-Scenes でも", ENTRIES), "7Scenesでも")

    def test_applied_names_the_rules_that_changed_the_text(self):
        self.assertEqual(speech.applied("精度が 3 倍", {}), ["ja-space"])
        self.assertEqual(speech.applied("そのまま", {}), [])
        self.assertEqual(
            speech.applied("SLAM-MER を紹介", ENTRIES), ["ja-space", "compound-hyphen"]
        )

    def test_explain_gives_the_spoken_form_per_rule(self):
        out = speech.explain("SLAM-MER を紹介", ENTRIES)
        self.assertEqual([x["rule"] for x in out], ["ja-space", "compound-hyphen"])
        self.assertEqual(out[-1]["after"], "SLAMMERを紹介")

    def test_prepare_is_idempotent(self):
        for t in ["精度が 3 倍", "SLAM-MER を紹介", "Sparse Voxel Grid"]:
            once = speech.prepare(t, ENTRIES)
            self.assertEqual(speech.prepare(once, ENTRIES), once)


class SubtitlesStayAsWrittenTests(unittest.TestCase):
    def test_burned_subtitles_keep_the_original_text(self):
        ts = {
            "subtitles": [
                {"index": 0, "text": "精度が 3 倍に なる", "start_s": 0.0, "end_s": 2.0}
            ]
        }
        ass = finish.build_ass(ts, 1280, 720, "Noto Sans CJK JP")
        self.assertIn("精度が 3 倍に なる", ass)


class GatewayTests(unittest.TestCase):
    """ENGINE に文を渡す経路は決まった場所だけで、読み上げ用の整形を通る(静的検査)。"""

    def calls(self):
        out = {}
        for p in sorted(SCRIPTS.glob("*.py")):
            n = len(re.findall(r"\.audio_query\(", p.read_text(encoding="utf-8")))
            if n and p.name != "voicevox_engine.py":
                out[p.name] = n
        return out

    def test_audio_query_is_called_only_from_the_known_places(self):
        self.assertEqual(
            set(self.calls()),
            {"tts_generate.py", "readings.py", "yomi.py"},
            "新しい呼び出し元は speech.prepare を通し、ここに足す",
        )

    def test_the_synthesis_and_reading_paths_use_prepare(self):
        for name in ("tts_generate.py", "readings.py"):
            src = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("speech.prepare(", src, name)
        self.assertNotIn("def speech_text", (SCRIPTS / "yomi.py").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
