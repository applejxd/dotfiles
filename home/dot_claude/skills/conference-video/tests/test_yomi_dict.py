"""読み辞書(JSON 窓口): 記法・検証・層・CLI・候補抽出・試聴。"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import yomi  # noqa: E402
from fake_voicevox import FakeVoicevox  # noqa: E402

YOMI_PY = HERE.parent / "scripts" / "yomi.py"


def write_dict(path, words):
    """words: {表記: 読み('記法)} か {表記: (読み, 状態, メモ)}。窓口を通して作る。"""
    store = yomi.dict_store(path)
    for surface, v in words.items():
        reading, status, note = (v, yomi.CONFIRMED, "") if isinstance(v, str) else v
        store.update(surface, None, yomi.make_entry(reading, status, note))


class ReadingNotationTests(unittest.TestCase):
    def test_parse_reading_accent_positions(self):
        self.assertEqual(yomi.parse_reading("ス'ラム"), ("スラム", 1))
        self.assertEqual(yomi.parse_reading("アイサ'ムツー"), ("アイサムツー", 3))
        self.assertEqual(yomi.parse_reading("スラム"), ("スラム", 0))  # 平板
        self.assertEqual(
            yomi.parse_reading("キョ'ウ"), ("キョウ", 1)
        )  # 拗音は 1 モーラ
        self.assertEqual(
            yomi.parse_reading("ニッポ'ン"), ("ニッポン", 3)
        )  # 促音・撥音は 1 モーラ
        self.assertEqual(
            yomi.parse_reading("ケーエ'ル"), ("ケーエル", 3)
        )  # 長音は 1 モーラ

    def test_parse_reading_rejects_bad_input(self):
        for bad in [
            "'スラム",
            "ス'ラ'ム",
            "スラム'1",
            "slam",
            "スラム ",
            "ス'ラ ム",
            "",
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    yomi.parse_reading(bad)

    def test_format_reading_roundtrip(self):
        for text in ["ス'ラム", "アイサ'ムツー", "スラム", "キョ'ウ"]:
            kana, accent = yomi.parse_reading(text)
            self.assertEqual(yomi.format_reading(kana, accent), text)


class DictFileTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)

    def test_load_reads_entries_with_defaults(self):
        write_dict(
            self.d / "y.json",
            {
                "SLAM": ("ス'ラム", "確認済み", "論文名"),
                "KL": ("ケーエ'ル", "候補", ""),
            },
        )
        e = yomi.load(self.d / "y.json")
        self.assertEqual(
            e["SLAM"],
            {"pron": "スラム", "accent": 1, "status": "確認済み", "note": "論文名"},
        )
        self.assertEqual(e["KL"]["status"], "候補")
        self.assertEqual(e["KL"]["accent"], 3)

    def test_missing_status_and_note_default(self):
        (self.d / "y.json").write_text(
            json.dumps(
                {"schema": 1, "entries": {"SLAM": {"pron": "スラム", "accent": 0}}}
            ),
            encoding="utf-8",
        )
        e = yomi.load(self.d / "y.json")
        self.assertEqual(e["SLAM"]["status"], "確認済み")
        self.assertEqual(e["SLAM"]["note"], "")

    BAD_ENTRIES = [
        ("pron がカタカナでない", {"pron": "slam", "accent": 0}),
        ("pron が無い", {"accent": 0}),
        ("accent が負", {"pron": "スラム", "accent": -1}),
        ("accent が bool", {"pron": "スラム", "accent": True}),
        ("accent が文字列", {"pron": "スラム", "accent": "1"}),
        ("状態が不正", {"pron": "スラム", "accent": 0, "status": "たぶん"}),
        ("note が文字列でない", {"pron": "スラム", "accent": 0, "note": 3}),
        ("辞書でない", "スラム"),
    ]

    def test_bad_entries_are_named_and_rejected_on_load(self):
        for name, entry in self.BAD_ENTRIES:
            with self.subTest(name):
                (self.d / "y.json").write_text(
                    json.dumps(
                        {"schema": 1, "entries": {"SLAM": entry}}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError) as cm:
                    yomi.load(self.d / "y.json")
                self.assertIn("SLAM", str(cm.exception))

    def test_bad_file_and_missing_file(self):
        (self.d / "y.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            yomi.load(self.d / "y.json")
        with self.assertRaises(FileNotFoundError):
            yomi.load(self.d / "none.json")

    def test_digest_ignores_note_and_status(self):
        a = {"SLAM": {"pron": "スラム", "accent": 1, "status": "候補", "note": "a"}}
        b = {"SLAM": {"pron": "スラム", "accent": 1, "status": "確認済み", "note": "b"}}
        c = {"SLAM": {"pron": "スラム", "accent": 2, "status": "確認済み", "note": "b"}}
        self.assertEqual(yomi.digest(a), yomi.digest(b))
        self.assertNotEqual(yomi.digest(a), yomi.digest(c))

    def test_confirmed_and_candidates(self):
        write_dict(
            self.d / "y.json",
            {"A": ("エ'ー", "確認済み", ""), "B": ("ビ'ー", "候補", "")},
        )
        e = yomi.load(self.d / "y.json")
        self.assertEqual(list(yomi.confirmed(e)), ["A"])
        self.assertEqual(yomi.candidates_in(e), ["B"])


class LayerTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self._old = os.environ.get("CONF_VIDEO_HOME")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("CONF_VIDEO_HOME", None)
        else:
            os.environ["CONF_VIDEO_HOME"] = self._old

    def test_later_layers_override_earlier_ones(self):
        home, session, default = (
            self.d / "home",
            self.d / "session",
            self.d / "default.json",
        )
        home.mkdir()
        session.mkdir()
        write_dict(default, {"SLAM": "スラム", "KL": "ケーエル", "AR": "エーアール"})
        write_dict(home / "yomi.json", {"KL": "ケ'ーエル"})
        write_dict(session / "yomi.json", {"AR": "エ'ーアール"})
        os.environ["CONF_VIDEO_HOME"] = str(home)
        e = yomi.load_layers(session, default=default)
        self.assertEqual(e["SLAM"]["accent"], 0)  # 既定
        self.assertEqual(e["KL"]["accent"], 1)  # ユーザー共通が既定を上書き
        self.assertEqual(e["AR"]["accent"], 1)  # 動画ごとが最優先

    def test_missing_layers_are_skipped(self):
        os.environ["CONF_VIDEO_HOME"] = str(self.d / "nohome")
        self.assertEqual(yomi.load_layers(self.d, default=self.d / "none.json"), {})

    def test_describe_layers_lists_absolute_json_paths(self):
        os.environ["CONF_VIDEO_HOME"] = str(self.d / "nohome")
        lines = yomi.describe_layers(self.d)
        self.assertTrue(
            any(str(self.d / "yomi.json") in ln and "ここを直す" in ln for ln in lines)
        )
        self.assertTrue(all(".csv" not in ln for ln in lines))

    def test_default_asset_is_valid(self):
        e = yomi.load(yomi.DEFAULT_JSON)
        self.assertIn("SLAM", e)
        self.assertTrue(all(v["status"] == "確認済み" for v in e.values()))


class CliBase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        self.f = self.d / "yomi.json"

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = yomi.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def entries(self):
        return yomi.read_entries(self.f)


class EditCommandTests(CliBase):
    def test_set_creates_a_confirmed_entry_with_accent(self):
        code, out, _ = self.run_cli("set", "SLAM", "ス'ラム", "--file", str(self.f))
        self.assertEqual(code, 0)
        self.assertEqual(
            self.entries()["SLAM"],
            {"pron": "スラム", "accent": 1, "status": "確認済み", "note": ""},
        )
        self.assertIn(str(self.f), out)

    def test_set_overwrites_reading_keeps_note_and_confirms(self):
        write_dict(self.f, {"KL": ("ケーエル", "候補", "下書き")})
        self.run_cli("set", "KL", "ケーエ'ル", "--file", str(self.f))
        e = self.entries()["KL"]
        self.assertEqual(
            (e["accent"], e["status"], e["note"]), (3, "確認済み", "下書き")
        )
        self.run_cli(
            "set", "KL", "ケーエ'ル", "--note", "聞いて直した", "--file", str(self.f)
        )
        self.assertEqual(self.entries()["KL"]["note"], "聞いて直した")

    def test_set_with_status_candidate(self):
        self.run_cli("set", "KL", "ケーエル", "--status", "候補", "--file", str(self.f))
        self.assertEqual(self.entries()["KL"]["status"], "候補")

    def test_bad_reading_is_rejected_and_file_untouched(self):
        write_dict(self.f, {"SLAM": "ス'ラム"})
        before = self.f.read_bytes()
        code, _, err = self.run_cli("set", "SLAM", "slam", "--file", str(self.f))
        self.assertEqual(code, 2)
        self.assertIn("カタカナ", err)
        self.assertEqual(self.f.read_bytes(), before)

    def test_corrupt_file_is_refused_without_change(self):
        self.f.write_text("{broken", encoding="utf-8")
        for argv in (["set", "A", "エー"], ["rm", "A"], ["confirm", "A"]):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv, "--file", str(self.f))
                self.assertEqual(code, 2)
                self.assertEqual(self.f.read_text(encoding="utf-8"), "{broken")

    def test_rm_and_rm_missing(self):
        write_dict(self.f, {"A": "エ'ー", "B": "ビ'ー"})
        self.assertEqual(self.run_cli("rm", "A", "--file", str(self.f))[0], 0)
        self.assertEqual(list(self.entries()), ["B"])
        code, out, _ = self.run_cli("rm", "A", "--file", str(self.f))
        self.assertEqual(code, 1)
        self.assertIn("無い", out)

    def test_confirm_marks_existing_and_reports_missing(self):
        write_dict(self.f, {"A": ("エ'ー", "候補", ""), "B": ("ビ'ー", "候補", "")})
        code, out, _ = self.run_cli("confirm", "A", "--file", str(self.f))
        self.assertEqual(code, 0)
        self.assertEqual(self.entries()["A"]["status"], "確認済み")
        self.assertEqual(self.entries()["B"]["status"], "候補")
        code, _, err = self.run_cli("confirm", "B", "ZZ", "--file", str(self.f))
        self.assertEqual(code, 1)
        self.assertIn("ZZ", err)
        self.assertEqual(self.entries()["B"]["status"], "確認済み")

    def test_list_prints_tab_separated_rows(self):
        write_dict(self.f, {"SLAM": ("ス'ラム", "確認済み", "メモ")})
        code, out, _ = self.run_cli("list", "--file", str(self.f))
        self.assertEqual(code, 0)
        self.assertIn("SLAM\tス'ラム\t確認済み\tメモ", out)

    def test_user_flag_edits_the_user_dictionary(self):
        old = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(self.d / "home")
        try:
            self.run_cli("set", "KL", "ケ'ーエル", "--user")
            self.assertEqual(
                yomi.read_entries(self.d / "home" / "yomi.json")["KL"]["accent"], 1
            )
        finally:
            if old is None:
                os.environ.pop("CONF_VIDEO_HOME")
            else:
                os.environ["CONF_VIDEO_HOME"] = old

    def test_concurrent_cli_processes_lose_no_word(self):
        words = [f"W{i}" for i in range(8)]
        ps = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(YOMI_PY),
                    "set",
                    w,
                    "エ'ー",
                    "--file",
                    str(self.f),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for w in words
        ]
        for p in ps:
            _, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(sorted(self.entries()), sorted(words))


class CandidatesAndAuditionTests(CliBase):
    def setUp(self):
        super().setUp()
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 単眼 SLAM と KL 発散を使う。\n- SLAM をもう一度。\n",
            encoding="utf-8",
        )

    def candidates(self, fake):
        fake.kana.update({"ＫＬ": "ケーエル", "ＳＬＡＭ": "スラム"})
        return self.run_cli(
            "candidates",
            str(self.d / "narration.txt"),
            "--out",
            str(self.f),
            "--yomi",
            str(self.f),
            "--engine-url",
            fake.url,
        )

    def test_candidates_adds_only_missing_tokens_as_candidates(self):
        write_dict(self.f, {"SLAM": "ス'ラム"})
        with FakeVoicevox() as fake:
            code, out, err = self.candidates(fake)
        self.assertEqual(code, 0, out + err)
        e = self.entries()
        self.assertEqual(e["SLAM"]["accent"], 1)  # 既存は変えない
        self.assertEqual(e["SLAM"]["status"], "確認済み")
        self.assertEqual(e["KL"]["status"], "候補")
        self.assertEqual(sorted(e), ["KL", "SLAM"])

    def test_candidates_twice_is_idempotent(self):
        write_dict(self.f, {"SLAM": "ス'ラム"})
        with FakeVoicevox() as fake:
            self.candidates(fake)
            first = self.f.read_bytes()
            self.candidates(fake)
        self.assertEqual(self.f.read_bytes(), first)

    def test_candidates_creates_the_dictionary_when_absent(self):
        with FakeVoicevox() as fake:
            fake.kana.update({"ＫＬ": "ケーエル", "ＳＬＡＭ": "スラム"})
            code, out, err = self.run_cli(
                "candidates",
                str(self.d / "narration.txt"),
                "--out",
                str(self.f),
                "--yomi",
                "--engine-url",
                fake.url,
            )
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(self.entries()), ["KL", "SLAM"])

    def test_audition_writes_one_wav_per_entry_and_a_combined_file(self):
        write_dict(self.f, {"SLAM": "ス'ラム", "KL": "ケーエ'ル"})
        out_dir = self.d / "audition"
        with FakeVoicevox() as fake:
            code, out, err = self.run_cli(
                "audition",
                "--yomi",
                str(self.f),
                "--out",
                str(out_dir),
                "--engine-url",
                fake.url,
            )
        self.assertEqual(code, 0, out + err)
        wavs = sorted(p.name for p in out_dir.glob("[0-9][0-9]_*.wav"))
        self.assertEqual(len(wavs), 2)
        with wave.open(str(out_dir / "all.wav")) as w:
            self.assertGreater(w.getnframes() / w.getframerate(), 0.5)
        self.assertIn("SLAM", (out_dir / "index.csv").read_text(encoding="utf-8-sig"))

    def test_register_command_applies_the_dictionary(self):
        write_dict(self.f, {"SLAM": "ス'ラム"})
        with FakeVoicevox() as fake:
            code, out, err = self.run_cli(
                "register", str(self.f), "--engine-url", fake.url
            )
            self.assertEqual(code, 0, out + err)
            self.assertEqual(fake.words["ＳＬＡＭ"][:2], ("スラム", 1))


if __name__ == "__main__":
    unittest.main()
