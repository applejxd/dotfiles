"""AC-01 / AC-02 / AC-03: VOICEVOX による台本の音声化。"""

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import tts_generate  # noqa: E402
from fake_voicevox import FakeVoicevox, make_query  # noqa: E402
from dict_fixture import write_dict  # noqa: E402

SCRIPT = (
    "subtitles:\n- 単眼の説明です。\n- 次に、地図の話をします。\n- 最後にまとめます。\n"
)


def wav_seconds(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


class TtsGenerateTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "narration.txt").write_text(SCRIPT, encoding="utf-8")
        write_dict(self.d / "yomi.json", {})

    def run_tts(self, url, *extra):
        argv = [
            "--narration",
            str(self.d / "narration.txt"),
            "--engine-url",
            url,
            "--yomi",
            str(self.d / "yomi.json"),
            "--workdir",
            str(self.d),
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tts_generate.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_durations_match_the_real_audio(self):
        with FakeVoicevox() as fake:
            code, log = self.run_tts(fake.url)
        self.assertEqual(code, 0, log)
        ts = json.loads((self.d / "timestamps.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ts["subtitles"]), 3)
        self.assertEqual(ts["subtitles"][0]["text"], "単眼の説明です。")
        total = wav_seconds(self.d / "voiceover.wav")
        self.assertAlmostEqual(ts["total_duration_s"], total, delta=0.05)
        for s in ts["subtitles"]:
            self.assertAlmostEqual(
                s["end_s"] - s["start_s"], s["duration_s"], delta=0.002
            )
            self.assertGreater(s["duration_s"], 0.5)
        # 区間は連続し、重ならない
        for a, b in zip(ts["subtitles"], ts["subtitles"][1:]):
            self.assertAlmostEqual(a["end_s"], b["start_s"], delta=0.002)
        # アクセント句の時刻が行の区間内にある
        second = ts["subtitles"][1]
        self.assertGreaterEqual(len(second["phrases"]), 2)
        self.assertLessEqual(second["phrases"][-1]["end_s"], second["end_s"] + 0.05)

    def test_cache_is_used_and_invalidated(self):
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 3)
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 3)  # 全行キャッシュ
            self.run_tts(fake.url, "--speed", "1.2")
            self.assertEqual(fake.synthesis_count(), 6)  # 速度が変われば再合成
            self.run_tts(fake.url, "--speed", "1.2", "--speaker", "3")
            self.assertEqual(fake.synthesis_count(), 9)  # 話者が変われば再合成
            write_dict(self.d / "yomi.json", {"単眼": "タ'ンガン"})
            self.run_tts(fake.url, "--speed", "1.2", "--speaker", "3")
            # 辞書を変えたときは、その語を含む行(1 行目)だけ再合成する
            self.assertEqual(fake.synthesis_count(), 10)

    def test_log_tells_where_the_dictionary_files_are(self):
        import os

        home = self.d / "home"
        home.mkdir()
        old = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(home)
        try:
            with FakeVoicevox() as fake:
                argv = [
                    "--narration",
                    str(self.d / "narration.txt"),
                    "--engine-url",
                    fake.url,
                    "--workdir",
                    str(self.d),
                ]
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    tts_generate.main(argv)
                before = out.getvalue()
                write_dict(self.d / "yomi.json", {})
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    tts_generate.main(argv)
                after = out.getvalue()
        finally:
            os.environ.pop("CONF_VIDEO_HOME") if old is None else os.environ.update(
                CONF_VIDEO_HOME=old
            )
        self.assertIn("読み辞書", before)
        self.assertIn(
            str(self.d / "yomi.json"), before
        )  # ここに作る/直すという絶対パス
        self.assertIn("無し", before)
        self.assertIn(str(self.d / "yomi.json"), after)
        self.assertIn(str(home / "yomi.json"), after)

    def test_compound_word_is_sent_to_the_engine_without_hyphen(self):
        (self.d / "narration.txt").write_text(
            "subtitles:\n- SLAM-MER を紹介します。\n- 次に地図です。\n",
            encoding="utf-8",
        )
        csv_path = self.d / "yomi.json"
        write_dict(csv_path, {"SLAM-MER": "スラマー"})
        with FakeVoicevox() as fake:
            code, log = self.run_tts(fake.url, "--yomi", str(csv_path))
            self.assertEqual(code, 0, log)
            texts = [q["text"] for m, p, q in fake.calls if p == "/audio_query"]
            self.assertEqual(
                texts[0], "SLAMMER を紹介します。"
            )  # ハイフンを除いて問い合わせる
            self.assertIn("ＳＬＡＭＭＥＲ", fake.words)
            # 字幕(timestamps.json の本文)は元の表記のまま
            ts = json.loads((self.d / "timestamps.json").read_text(encoding="utf-8"))
            self.assertEqual(ts["subtitles"][0]["text"], "SLAM-MER を紹介します。")
            n = fake.synthesis_count()
            # 複合語の読みを変えると、その語を含む 1 行目だけ再合成される
            write_dict(csv_path, {"SLAM-MER": "スラ'マー"})
            self.run_tts(fake.url, "--yomi", str(csv_path))
            self.assertEqual(fake.synthesis_count(), n + 1)

    def test_unchanged_run_reports_no_time_change(self):
        with FakeVoicevox() as fake:
            code, log = self.run_tts(fake.url)
            self.assertNotIn("時間が変わった行", log)  # 初回は比べる前の結果が無い
            self.assertNotIn("時間の変更なし", log)
            code, log = self.run_tts(fake.url)
        self.assertEqual(code, 0, log)
        self.assertIn("時間の変更なし", log)

    def test_speed_change_reports_every_line(self):
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
            code, log = self.run_tts(fake.url, "--speed", "2.0")
        self.assertEqual(code, 0, log)
        self.assertIn("時間が変わった行: 1, 2, 3", log)

    def test_changed_text_is_reported(self):
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
            (self.d / "narration.txt").write_text(
                "subtitles:\n- 単眼の説明です。\n- 次に、地図の話を長くします。\n- 最後にまとめます。\n",
                encoding="utf-8",
            )
            code, log = self.run_tts(fake.url)
        self.assertIn("時間が変わった行: 2", log)

    def test_speed_shortens_audio(self):
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
            a = wav_seconds(self.d / "voiceover.wav")
            self.run_tts(fake.url, "--speed", "2.0")
            b = wav_seconds(self.d / "voiceover.wav")
        self.assertLess(b, a * 0.6)

    def test_unreachable_engine_exits_2_and_keeps_outputs(self):
        (self.d / "timestamps.json").write_text('{"keep": true}', encoding="utf-8")
        t0 = time.time()
        code, log = self.run_tts("http://127.0.0.1:9", "--connect-timeout", "1")
        self.assertEqual(code, 2)
        self.assertIn("docker run", log)  # 起動方法を示す
        self.assertEqual(
            json.loads((self.d / "timestamps.json").read_text()), {"keep": True}
        )
        self.assertFalse((self.d / "voiceover.wav").exists())
        self.assertLess(time.time() - t0, 10)

    def test_each_line_duration_matches_the_expected_audio(self):
        # 偽サーバの長さ = モーラ長の合計 + 前後の無音 0.2 秒。行ごとに実際の長さと照合する
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
        ts = json.loads((self.d / "timestamps.json").read_text(encoding="utf-8"))
        for s in ts["subtitles"]:
            q = make_query(s["text"])
            expected = (
                sum(
                    m["vowel_length"] for ap in q["accent_phrases"] for m in ap["moras"]
                )
                + 0.2
            )
            self.assertAlmostEqual(s["duration_s"], expected, delta=0.05, msg=s["text"])

    def test_dictionary_change_resynthesizes_only_lines_containing_the_word(self):
        with FakeVoicevox() as fake:
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 3)
            # どの行にも現れない語は、再合成を起こさない
            fake.words["ＸＹＺ"] = ("エックス", 1, 5)
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 3)
            # 2 行目にだけ現れる語(別セッションが ENGINE に登録した語)は、その行だけ
            fake.words["地図"] = ("チズ", 1, 5)
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 4)
            # 読みを変えても同じ
            fake.words["地図"] = ("チズ", 2, 5)
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 5)
            self.run_tts(fake.url)
            self.assertEqual(fake.synthesis_count(), 5)  # 変更が無ければ全行キャッシュ

    def test_midway_failure_exits_2_and_keeps_previous_outputs(self):
        (self.d / "timestamps.json").write_text('{"keep": true}', encoding="utf-8")
        (self.d / "voiceover.wav").write_bytes(b"keep")
        with FakeVoicevox() as fake:
            fake.rates = [24000, 16000, 24000]  # 2 行目だけ形式が違う
            code, log = self.run_tts(fake.url)
        self.assertEqual(code, 2, log)
        self.assertEqual(
            json.loads((self.d / "timestamps.json").read_text()), {"keep": True}
        )
        self.assertEqual((self.d / "voiceover.wav").read_bytes(), b"keep")
        self.assertEqual([p.name for p in self.d.glob("*.tmp")], [])

    def test_dictionary_layers_are_used_when_yomi_is_omitted(self):
        import os

        home = self.d / "home"
        home.mkdir()
        write_dict(home / "yomi.json", {"XYZ": "エックス"})
        write_dict(
            self.d / "yomi.json",
            {"SLAM": "ス'ラム", "QRS": ("キュー", "候補", "")},
        )
        old = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(home)
        try:
            with FakeVoicevox() as fake:
                argv = [
                    "--narration",
                    str(self.d / "narration.txt"),
                    "--engine-url",
                    fake.url,
                    "--workdir",
                    str(self.d),
                ]
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    code = tts_generate.main(argv)
                words = dict(fake.words)
        finally:
            os.environ.pop("CONF_VIDEO_HOME") if old is None else os.environ.update(
                CONF_VIDEO_HOME=old
            )
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("ＸＹＺ", words)  # ユーザー共通層
        self.assertEqual(
            words["ＳＬＡＭ"][:2], ("スラム", 1)
        )  # 動画ごとの層と、既定層の上書き
        self.assertNotIn("ＱＲＳ", words)  # 候補は登録しない
        self.assertIn("候補 1 語", out.getvalue())

    def test_empty_script_is_reported(self):
        (self.d / "narration.txt").write_text("subtitles:\n", encoding="utf-8")
        with FakeVoicevox() as fake:
            code, log = self.run_tts(fake.url)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
