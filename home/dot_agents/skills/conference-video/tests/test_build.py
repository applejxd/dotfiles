"""下書きビルド(build.py): 変更のあったシーンだけを再描画し、下書き動画を作る。

偽の manim(tests/fake_manim.py)・実 ffmpeg・(統合試験だけ)偽 VOICEVOX を使う。
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import build  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FAKE = f"{sys.executable} {HERE / 'fake_manim.py'}"

SCRIPT = '''"""試験用のシーンスクリプト(実行はしない。build.py は構文を読むだけ)。"""
SHARED = "v1"


class Clock:
    pass


class SceneA(Scene):
    LINES = [0, 1]


class SceneB(Scene):
    LINES = [2]


class SceneC(Scene):
    LINES = [3]
    CLIP = "clips/a.mp4"
'''
TEXTS = ["一行目です。", "二行目です。", "三行目です。", "四行目です。"]


def write_ts(d: Path, texts=TEXTS, durs=(2.0, 2.0, 3.0, 4.0)):
    subs, t = [], 0.0
    for i, (x, du) in enumerate(zip(texts, durs)):
        subs.append(
            {"index": i, "text": x, "start_s": t, "end_s": t + du, "duration_s": du}
        )
        t += du
    (d / "timestamps.json").write_text(
        json.dumps({"total_duration_s": t, "subtitles": subs}, ensure_ascii=False),
        encoding="utf-8",
    )
    narr = "subtitles:\n" + "".join(f"- {x}\n" for x in texts)
    (d / "narration.txt").write_text(narr, encoding="utf-8")
    with wave.open(str(d / "voiceover.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * t))


class BuildBase(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        (self.d / "script.py").write_text(SCRIPT, encoding="utf-8")
        (self.d / "clips").mkdir()
        (self.d / "clips" / "a.mp4").write_bytes(b"clip-a-v1")
        write_ts(self.d)

    def build(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = build.main(
                [
                    "--workdir",
                    str(self.d),
                    "--manim",
                    FAKE,
                    "--no-tts",
                    "--no-lint",
                    *extra,
                ]
            )
        return code, out.getvalue()

    def calls(self):
        p = self.d / "manim_calls.log"
        return p.read_text(encoding="utf-8").split() if p.is_file() else []

    def clear_calls(self):
        (self.d / "manim_calls.log").unlink(missing_ok=True)

    def edit_script(self, old, new):
        p = self.d / "script.py"
        s = p.read_text(encoding="utf-8")
        assert old in s
        p.write_text(s.replace(old, new, 1), encoding="utf-8")

    def manifest(self):
        p = self.d / "build.json"
        return (
            json.loads(p.read_text(encoding="utf-8"))["entries"] if p.is_file() else {}
        )


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class BuildTests(BuildBase):
    def test_first_build_renders_every_scene_and_makes_the_draft(self):
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])
        self.assertTrue((self.d / "draft_silent.mp4").is_file())
        self.assertTrue((self.d / "draft.mp4").is_file())
        self.assertFalse((self.d / "video.mp4").exists())
        self.assertEqual(sorted(self.manifest()), ["SceneA", "SceneB", "SceneC"])
        concat = (self.d / "concat.draft.txt").read_text(encoding="utf-8")
        self.assertLess(concat.index("SceneA"), concat.index("SceneB"))
        self.assertLess(concat.index("SceneB"), concat.index("SceneC"))

    def test_second_build_with_no_change_renders_nothing(self):
        self.build()
        self.clear_calls()
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [])
        self.assertIn("再利用", out)

    def test_changing_the_duration_of_one_line_renders_only_its_scene(self):
        self.build()
        self.clear_calls()
        write_ts(self.d, durs=(2.0, 2.0, 3.5, 4.0))  # 3 行目だけ長くなる
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), ["SceneB"])
        self.assertIn("3 行目", out)  # 理由を示す

    def test_changing_the_text_of_one_line_renders_only_its_scene(self):
        self.build()
        self.clear_calls()
        write_ts(self.d, texts=[TEXTS[0], TEXTS[1], TEXTS[2], "書き換えた四行目です。"])
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneC"])

    def test_changing_one_scene_class_renders_only_it(self):
        self.build()
        self.clear_calls()
        self.edit_script("LINES = [2]", "LINES = [2]\n    EXTRA = 1")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneB"])

    def test_changing_shared_code_renders_every_scene(self):
        self.build()
        self.clear_calls()
        self.edit_script('SHARED = "v1"', 'SHARED = "v2"')
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])

    def test_changing_a_referenced_clip_renders_only_the_scene_using_it(self):
        self.build()
        self.clear_calls()
        (self.d / "clips" / "a.mp4").write_bytes(b"clip-a-v2-longer")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneC"])

    def test_full_and_rerender_force_scenes(self):
        self.build()
        self.clear_calls()
        self.assertEqual(self.build("--full")[0], 0)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])
        self.clear_calls()
        self.assertEqual(self.build("--rerender", "SceneA")[0], 0)
        self.assertEqual(self.calls(), ["SceneA"])

    def test_a_deleted_scene_video_is_rendered_again(self):
        self.build()
        self.clear_calls()
        (self.d / "media/videos/script/480p15/SceneB.mp4").unlink()
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneB"])

    def test_a_failed_scene_stops_before_concat_and_keeps_the_old_draft(self):
        self.build()
        before = (self.d / "draft.mp4").read_bytes()
        self.clear_calls()
        write_ts(self.d, durs=(2.0, 2.0, 3.5, 4.0))
        self.edit_script("LINES = [2]", "LINES = [2]\n    FAIL = True")
        code, out = self.build()
        self.assertEqual(code, 1, out)
        self.assertIn("SceneB", out)
        self.assertEqual(
            (self.d / "draft.mp4").read_bytes(), before
        )  # 結合・仕上げに進まない
        self.assertIn("SceneA", self.manifest())  # 成功済みの記録は残る
        # 直したら、失敗したシーンだけ描画し直す
        self.edit_script("    FAIL = True", "    OK = True")
        self.clear_calls()
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), ["SceneB"])

    def test_a_failed_concat_is_redone_on_the_next_run(self):
        """結合だけが失敗したあとの再実行で、古い draft_silent.mp4 を再利用しない(レビュー MAJOR 5)。"""
        self.build()
        write_ts(self.d, durs=(2.0, 2.0, 3.5, 4.0))  # 合計 11.0 → 11.5 秒
        real = subprocess.run

        def fail_concat(cmd, *a, **k):
            if isinstance(cmd, list) and cmd[:1] == ["ffmpeg"] and "concat" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "boom")
            return real(cmd, *a, **k)

        with mock.patch.object(build.subprocess, "run", fail_concat):
            code, out = self.build()
        self.assertEqual(code, 1, out)
        self.clear_calls()
        code, out = self.build()  # シーンは再利用。結合と仕上げはやり直す
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [])
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(self.d / "draft_silent.mp4"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertAlmostEqual(float(r.stdout), 11.5, delta=0.3)

    def test_a_scene_without_subtitles_is_always_rendered_again(self):
        """字幕(srt)が無いシーンは、使う行を判定できないので毎回描画する(安全側)。"""
        self.edit_script("LINES = [2]", "LINES = [2]\n    NOSRT = True")
        self.build()
        self.clear_calls()
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneB"])

    def test_lines_with_the_same_text_are_all_treated_as_dependencies(self):
        """同じ本文の行が複数あるとき、どれを使ったかを推定せず、候補のすべてを見る。"""
        texts = ["一行目です。", "同じ文です。", "同じ文です。", "四行目です。"]
        write_ts(self.d, texts=texts)
        self.build()
        self.clear_calls()
        write_ts(
            self.d, texts=texts, durs=(2.0, 2.0, 3.5, 4.0)
        )  # 後ろの同文行(3 行目)だけ長くなる
        self.assertEqual(self.build()[0], 0)
        self.assertIn("SceneB", self.calls())  # この行を使うシーン
        self.assertNotIn("SceneC", self.calls())

    def test_a_helper_module_change_renders_every_scene(self):
        """script.py が import する補助モジュール(作業フォルダの .py)を直したら、全シーンを描画する。"""
        (self.d / "helpers.py").write_text("X = 1\n", encoding="utf-8")
        self.build()
        self.clear_calls()
        (self.d / "helpers.py").write_text("X = 2\n", encoding="utf-8")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])

    def test_declared_data_files_are_dependencies(self):
        """DEPENDS(モジュール先頭 = 全シーン、クラス属性 = そのシーン)で宣言したデータの変更を見る。"""
        (self.d / "data").mkdir()
        (self.d / "data" / "all.csv").write_text("1", encoding="utf-8")
        (self.d / "data" / "b.csv").write_text("1", encoding="utf-8")
        self.edit_script('SHARED = "v1"', 'SHARED = "v1"\nDEPENDS = ["data/all.csv"]')
        self.edit_script("LINES = [2]", 'LINES = [2]\n    DEPENDS = ["data/b.csv"]')
        self.build()
        self.clear_calls()
        (self.d / "data" / "b.csv").write_text("2", encoding="utf-8")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(self.calls(), ["SceneB"])
        self.clear_calls()
        (self.d / "data" / "all.csv").write_text("2", encoding="utf-8")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])

    def test_a_declared_directory_depends_on_every_file_inside(self):
        (self.d / "data" / "sub").mkdir(parents=True)
        (self.d / "data" / "sub" / "x.csv").write_text("1", encoding="utf-8")
        self.edit_script('SHARED = "v1"', 'SHARED = "v1"\nDEPENDS = ["data"]')
        self.build()
        self.clear_calls()
        (self.d / "data" / "sub" / "x.csv").write_text("2", encoding="utf-8")
        self.assertEqual(self.build()[0], 0)
        self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])

    def test_a_missing_declared_file_is_reported_before_rendering(self):
        self.edit_script('SHARED = "v1"', 'SHARED = "v1"\nDEPENDS = ["data/none.csv"]')
        code, out = self.build()
        self.assertEqual(code, 2, out)
        self.assertIn("data/none.csv", out)
        self.assertEqual(self.calls(), [])

    def test_missing_clip_is_reported_before_any_rendering(self):
        (self.d / "clips" / "a.mp4").unlink()
        code, out = self.build()
        self.assertEqual(code, 2, out)
        self.assertIn("clips/a.mp4", out)
        self.assertEqual(self.calls(), [])

    def test_missing_manim_is_reported_before_any_rendering(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = build.main(
                [
                    "--workdir",
                    str(self.d),
                    "--manim",
                    "no-such-manim-cmd",
                    "--no-tts",
                    "--no-lint",
                ]
            )
        self.assertEqual(code, 2, out.getvalue())
        self.assertIn("no-such-manim-cmd", out.getvalue())

    def test_missing_script_or_timestamps_exit_2(self):
        (self.d / "timestamps.json").unlink()
        code, out = self.build()
        self.assertEqual(code, 2, out)
        self.assertIn("timestamps.json", out)

    def test_corrupt_manifest_is_refused_not_overwritten(self):
        (self.d / "build.json").write_text("{壊れ", encoding="utf-8")
        code, out = self.build()
        self.assertEqual(code, 2, out)
        self.assertIn("build.json", out)
        self.assertEqual((self.d / "build.json").read_text(encoding="utf-8"), "{壊れ")

    def test_script_that_is_not_python_is_reported(self):
        (self.d / "script.py").write_text("class (:", encoding="utf-8")
        code, out = self.build()
        self.assertEqual(code, 2, out)
        self.assertIn("script.py", out)

    def test_draft_is_not_rebuilt_when_nothing_changed(self):
        self.build()
        first = (self.d / "draft.mp4").stat().st_mtime_ns
        code, out = self.build()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.d / "draft.mp4").stat().st_mtime_ns, first)

    def test_stage_times_are_reported(self):
        code, out = self.build()
        self.assertEqual(code, 0, out)
        for key in ("render SceneA", "concat", "finish", "合計"):
            self.assertIn(key, out)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class BuildWithTtsTests(BuildBase):
    """音声合成(モック VOICEVOX)まで通し、本文を直すとその行のシーンだけが描画される。"""

    def build_tts(self, url, *extra):
        from dict_fixture import write_dict

        yomi = self.d / "yomi.json"
        if not yomi.exists():
            write_dict(yomi, {})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = build.main(
                [
                    "--workdir",
                    str(self.d),
                    "--manim",
                    FAKE,
                    "--no-lint",
                    "--engine-url",
                    url,
                    "--yomi",
                    str(yomi),
                    "--connect-timeout",
                    "2",
                    *extra,
                ]
            )
        return code, out.getvalue()

    def setUp(self):
        super().setUp()
        for n in ("timestamps.json", "voiceover.wav"):
            (self.d / n).unlink()  # 合成で作る

    def test_editing_one_line_resynthesizes_and_renders_only_its_scene(self):
        from fake_voicevox import FakeVoicevox

        with FakeVoicevox() as fake:
            code, out = self.build_tts(fake.url)
            self.assertEqual(code, 0, out)
            self.assertEqual(sorted(self.calls()), ["SceneA", "SceneB", "SceneC"])
            self.assertIn("[tts]", out)
            self.clear_calls()
            code, out = self.build_tts(fake.url)  # 変更なし
            self.assertEqual(code, 0, out)
            self.assertEqual(self.calls(), [])
            narr = self.d / "narration.txt"
            narr.write_text(
                narr.read_text(encoding="utf-8").replace(
                    "三行目です。", "三行目は、もう少し長い文章に直しました。"
                ),
                encoding="utf-8",
            )
            code, out = self.build_tts(fake.url)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.calls(), ["SceneB"])

    def test_unreachable_engine_stops_before_rendering(self):
        code, out = self.build_tts("http://127.0.0.1:9")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.d / "draft.mp4").exists())


class AnalysisTests(unittest.TestCase):
    """script.py の読み取り(構文だけ)。シーンの検出、依存の切り分け、素材の参照。"""

    def test_scene_classes_are_found_in_file_order_including_subclasses(self):
        src = (
            "class Base(Scene):\n    pass\n\n"
            "class Child(Base):\n    pass\n\n"
            "class Helper:\n    pass\n\n"
            "class Other(MovingCameraScene):\n    pass\n"
        )
        tree = build.parse_script_text(src)
        self.assertEqual(list(build.scene_classes(tree)), ["Base", "Child", "Other"])

    def test_a_scene_depends_on_its_base_scene_but_not_on_siblings(self):
        src = (
            "X = 1\n\nclass Base(Scene):\n    A = 1\n\n"
            "class Child(Base):\n    B = 2\n\n"
            "class Sibling(Scene):\n    C = 3\n"
        )
        tree = build.parse_script_text(src)
        fa = build.fingerprints(tree, src, "q")
        src2 = src.replace("C = 3", "C = 4")
        fb = build.fingerprints(build.parse_script_text(src2), src2, "q")
        self.assertEqual(fa["Child"], fb["Child"])
        self.assertNotEqual(fa["Sibling"], fb["Sibling"])
        src3 = src.replace("A = 1", "A = 9")
        fc = build.fingerprints(build.parse_script_text(src3), src3, "q")
        self.assertNotEqual(fa["Child"], fc["Child"])  # 親シーンの変更は子に効く

    def test_declared_dependencies_are_read_from_the_script(self):
        src = (
            'DEPENDS = ["data.csv"]\n'
            "class S(Scene):\n"
            '    DEPENDS = ("x.json", "dir")\n'
            "    def construct(self):\n        pass\n"
        )
        tree = build.parse_script_text(src)
        self.assertEqual(
            build.media_refs(tree, src), {"S": ["data.csv", "dir", "x.json"]}
        )

    def test_media_references_are_string_literals_with_media_extensions(self):
        src = (
            "class S(Scene):\n    def construct(self):\n"
            '        VideoMobject("clips/a.mp4")\n        x = "not media.txt"\n'
            '        ImageMobject("assets/p.png")\n'
        )
        tree = build.parse_script_text(src)
        self.assertEqual(
            build.media_refs(tree, src), {"S": ["assets/p.png", "clips/a.mp4"]}
        )

    def test_lint_runs_in_the_same_environment_as_manim(self):
        """リンタは script.py を実行するので、manim と同じ環境(venv)の python で動かす。"""
        f = build.python_cmd_for
        self.assertEqual(
            f("uv run --project /s manim"), ["uv", "run", "--project", "/s", "python"]
        )
        self.assertEqual(f("/v/bin/manim"), ["/v/bin/python"])
        self.assertEqual(f("manim"), ["python"])
        self.assertEqual(
            f("/v/bin/manimce"), [sys.executable]
        )  # 判定できないときはこの python
        self.assertEqual(f(f"{sys.executable} fake_manim.py"), [sys.executable])
        self.assertEqual(f("manim", override="/x/py -u"), ["/x/py", "-u"])

    def test_srt_blocks_are_mapped_to_script_lines_in_order(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\nあ\n\n2\n00:00:02,000 --> 00:00:04,000\nい\n"
        self.assertEqual(build.read_srt_texts(srt), ["あ", "い"])
        ts = [{"text": "い"}, {"text": "あ"}, {"text": "あ"}]
        # 同じ本文が複数あるときは、どれかを推定せず、候補をすべて依存とする(安全側)
        self.assertEqual(
            build.match_candidates(["あ", "い", "あ"], ts), [[1, 2], [0], [1, 2]]
        )
        self.assertEqual(build.match_candidates(["未知"], ts), [[]])


if __name__ == "__main__":
    unittest.main()
