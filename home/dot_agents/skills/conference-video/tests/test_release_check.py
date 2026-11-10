"""公開前チェック(release_check.py): 機械で確かめられる項目と、人が確かめる 4 項目。"""

import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import release_check as rc  # noqa: E402
import review_sheet  # noqa: E402
from dict_fixture import write_assets, write_dict  # noqa: E402

ASSET = {
    "出典URL": "https://example.org/a",
    "作者": "太郎",
    "ライセンス": "CC BY 4.0",
    "状態": "確認済み",
    "場面": "動機",
    "メモ": "",
    "取得日": "2026-10-27",
    "種別": "",
    "書誌": "",
    "位置": "",
}


def touch_later(path: Path, base: float):
    os.utime(path, (base, base))


class ReleaseBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)
        self._old_home = os.environ.get("CONF_VIDEO_HOME")
        os.environ["CONF_VIDEO_HOME"] = str(self.d / "home")  # 利用者の辞書を使わない
        self.addCleanup(self._restore_home)
        (self.d / "assets").mkdir()
        (self.d / "assets" / "a.png").write_bytes(b"png")
        write_assets(self.d / "assets.json", {"assets/a.png": ASSET})
        write_dict(self.d / "yomi.json", {"SLAM": "ス'ラム"})
        (self.d / "narration.txt").write_text(
            "subtitles:\n- 単眼 SLAM です。\n", "utf-8"
        )
        (self.d / "script.py").write_text("x = 1\n", encoding="utf-8")
        (self.d / "timestamps.json").write_text("{}", encoding="utf-8")
        (self.d / "voiceover.wav").write_bytes(b"RIFF")
        (self.d / "description.txt").write_text("題名\nVOICEVOX:四国めたん\n", "utf-8")
        base = time.time() - 100
        for n in (
            "narration.txt",
            "script.py",
            "timestamps.json",
            "voiceover.wav",
            "assets.json",
            "yomi.json",
        ):
            touch_later(self.d / n, base)
        (self.d / "video.mp4").write_bytes(b"mp4")  # 入力より新しい

    def _restore_home(self):
        if self._old_home is None:
            os.environ.pop("CONF_VIDEO_HOME", None)
        else:
            os.environ["CONF_VIDEO_HOME"] = self._old_home

    def by_id(self, checks):
        return {c.id: c for c in checks}


class MachineChecksTests(ReleaseBase):
    def test_a_releasable_workdir_passes_every_check(self):
        checks = rc.machine_checks(self.d)
        self.assertEqual(
            [c.id for c in checks], ["assets", "yomi", "notes", "fresh", "credit"]
        )
        self.assertEqual(rc.failures(checks), [], [c.detail for c in checks])

    def test_a_provisional_or_incomplete_asset_fails(self):
        write_assets(self.d / "assets.json", {"assets/a.png": {**ASSET, "状態": "仮"}})
        c = self.by_id(rc.machine_checks(self.d))["assets"]
        self.assertFalse(c.ok)
        self.assertIn("assets/a.png", c.detail)

    def test_a_missing_ledger_is_not_a_failure_when_nothing_is_referenced(self):
        (self.d / "assets.json").unlink()
        self.assertTrue(self.by_id(rc.machine_checks(self.d))["assets"].ok)

    def test_remaining_yomi_candidates_fail(self):
        write_dict(self.d / "yomi.json", {"KL": ("ケ'ーエル", "候補", "")})
        c = self.by_id(rc.machine_checks(self.d))["yomi"]
        self.assertFalse(c.ok)
        self.assertIn("KL", c.detail)

    def test_open_notes_fail_but_fixed_notes_do_not(self):
        st = review_sheet.notes_store(self.d)
        e = review_sheet.make_entry(1, "単眼 SLAM です。", "読みを確認")
        st.update(review_sheet.note_key("単眼 SLAM です。"), None, e)
        c = self.by_id(rc.machine_checks(self.d))["notes"]
        self.assertFalse(c.ok)
        self.assertIn("1 件", c.detail)
        review_sheet.change_status(
            self.d, [review_sheet.note_key("単眼 SLAM です。")], review_sheet.FIXED
        )
        self.assertTrue(self.by_id(rc.machine_checks(self.d))["notes"].ok)

    def test_rewrapping_stale_audio_into_a_new_video_is_not_fresh(self):
        """音声が現在の台本・辞書より古いまま、仕上げだけやり直して video.mp4 だけが新しい場合(レビュー MAJOR 1)。"""
        now = time.time()
        os.utime(self.d / "yomi.json", (now - 10, now - 10))  # 辞書を直した
        os.utime(self.d / "voiceover.wav", (now - 50, now - 50))  # 再合成していない
        os.utime(self.d / "timestamps.json", (now - 50, now - 50))
        c = self.by_id(rc.machine_checks(self.d))["fresh"]
        self.assertFalse(c.ok)
        self.assertIn("再合成", c.detail)

    def test_silent_video_older_than_the_timestamps_is_not_fresh(self):
        (self.d / "video_silent.mp4").write_bytes(b"silent")
        now = time.time()
        os.utime(self.d / "video_silent.mp4", (now - 90, now - 90))
        os.utime(self.d / "timestamps.json", (now - 20, now - 20))
        os.utime(self.d / "voiceover.wav", (now - 20, now - 20))
        c = self.by_id(rc.machine_checks(self.d))["fresh"]
        self.assertFalse(c.ok)
        self.assertIn("描画", c.detail)

    def test_a_consistent_chain_is_fresh(self):
        (self.d / "video_silent.mp4").write_bytes(b"silent")
        now = time.time()
        for name, ago in (
            ("narration.txt", 90),
            ("yomi.json", 90),
            ("voiceover.wav", 60),
            ("timestamps.json", 60),
            ("script.py", 80),
            ("video_silent.mp4", 40),
        ):
            os.utime(self.d / name, (now - ago, now - ago))
        os.utime(self.d / "video.mp4", (now - 10, now - 10))
        self.assertTrue(self.by_id(rc.machine_checks(self.d))["fresh"].ok)

    def test_release_rev_changes_with_the_video_description_or_ledger(self):
        a = rc.release_rev(self.d)
        self.assertEqual(a, rc.release_rev(self.d))
        for name, content in (
            ("video.mp4", b"other video"),
            ("description.txt", "違う説明\nVOICEVOX:x\n".encode()),
            ("assets.json", b'{"schema": 1, "entries": {}}'),
        ):
            with self.subTest(name=name):
                before = rc.release_rev(self.d)
                (self.d / name).write_bytes(content)
                self.assertNotEqual(before, rc.release_rev(self.d))

    def test_video_older_than_an_input_is_not_fresh(self):
        old = time.time() - 1000
        os.utime(self.d / "video.mp4", (old, old))
        c = self.by_id(rc.machine_checks(self.d))["fresh"]
        self.assertFalse(c.ok)
        self.assertIn("作り直す", c.detail)

    def test_missing_video_is_not_fresh(self):
        (self.d / "video.mp4").unlink()
        self.assertFalse(self.by_id(rc.machine_checks(self.d))["fresh"].ok)

    def test_credit_is_required_in_the_description(self):
        (self.d / "description.txt").write_text("題名だけ\n", encoding="utf-8")
        self.assertFalse(self.by_id(rc.machine_checks(self.d))["credit"].ok)
        (self.d / "description.txt").unlink()
        self.assertFalse(self.by_id(rc.machine_checks(self.d))["credit"].ok)

    def test_pre_checks_skip_what_depends_on_the_finished_video(self):
        (self.d / "video.mp4").unlink()
        (self.d / "description.txt").unlink()
        checks = rc.machine_checks(self.d, pre=True)
        self.assertEqual([c.id for c in checks], ["assets", "yomi", "notes"])
        self.assertEqual(rc.failures(checks), [])

    def test_unreadable_sources_fail_instead_of_passing_silently(self):
        (self.d / "yomi.json").write_text("{壊れ", encoding="utf-8")
        (self.d / "assets.json").write_text("{壊れ", encoding="utf-8")
        (self.d / "notes.json").write_text("{壊れ", encoding="utf-8")
        got = self.by_id(rc.machine_checks(self.d))
        for k in ("assets", "yomi", "notes"):
            self.assertFalse(got[k].ok, k)
            self.assertIn("読めない", got[k].detail, k)

    def test_report_has_checks_and_the_four_human_items(self):
        r = rc.report(self.d)
        self.assertEqual(
            [h["id"] for h in r["human"]], ["source", "rights", "reading", "numbers"]
        )
        self.assertTrue(all("label" in h for h in r["human"]))
        self.assertTrue(r["ok"])
        self.assertEqual(rc.HUMAN_IDS, ["source", "rights", "reading", "numbers"])


class CliTests(ReleaseBase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rc.main(["--workdir", str(self.d), *argv])
        return code, out.getvalue()

    def test_exit_zero_when_all_pass_and_one_when_not(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        write_dict(self.d / "yomi.json", {"KL": ("ケ'ーエル", "候補", "")})
        code, out = self.run_cli()
        self.assertEqual(code, 1, out)
        self.assertIn("KL", out)
        self.assertIn("人が確かめる", out)

    def test_pre_flag(self):
        (self.d / "video.mp4").unlink()
        code, _ = self.run_cli("--pre")
        self.assertEqual(code, 0)
        code, _ = self.run_cli()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
