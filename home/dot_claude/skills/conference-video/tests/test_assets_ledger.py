"""素材台帳(assets.json): 取得した画像・動画の出典・ライセンス・公開可否を管理する。"""

import contextlib
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assets_ledger  # noqa: E402
import state_store  # noqa: E402

FIELDS = [
    "出典URL",
    "作者",
    "ライセンス",
    "状態",
    "場面",
    "メモ",
    "取得日",
    "種別",
    "書誌",
    "位置",
]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = assets_ledger.main(argv)
    return code, out.getvalue() + err.getvalue()


def entry(
    url="",
    author="",
    lic="",
    status="確認済み",
    scene="",
    note="",
    date="",
    kind="",
    cite="",
    loc="",
):
    return dict(
        zip(FIELDS, [url, author, lic, status, scene, note, date, kind, cite, loc])
    )


class LedgerBase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        (self.d / "assets").mkdir()
        (self.d / "assets" / "ar.jpg").write_bytes(b"x")
        (self.d / "assets" / "robot.mp4").write_bytes(b"x")
        self.path = self.d / "assets.json"

    def ledger(self, rows):
        """rows: {ファイル: entry(...)}。窓口を通さず上書きで作る(試験の補助)。"""
        self.path.write_text(
            json.dumps({"schema": 1, "entries": rows}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return str(self.path)


class AssetsLedgerTests(LedgerBase):
    def test_init_creates_an_empty_ledger_and_does_not_overwrite(self):
        code, out = run(["init", str(self.path)])
        self.assertEqual(code, 0, out)
        self.assertEqual(assets_ledger.load(self.path), [])
        before = self.path.read_bytes()
        code, out = run(["init", str(self.path)])
        self.assertEqual(code, 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_load_returns_rows_with_defaults(self):
        p = self.ledger(
            {"assets/ar.jpg": {"出典URL": "https://x.example/a", "ライセンス": "CC0"}}
        )
        row = assets_ledger.load(p)[0]
        self.assertEqual(row["ファイル"], "assets/ar.jpg")
        self.assertEqual(row["状態"], "仮")  # 無ければ仮
        for f in ("作者", "場面", "メモ", "取得日", "種別", "書誌", "位置"):
            self.assertEqual(row[f], "")

    def test_load_rejects_bad_files_and_names_the_entry(self):
        for name, e in [
            ("状態が不正", entry("https://x.example/a", "A", "CC0", "たぶん")),
            (
                "種別が不正",
                entry("https://x.example/a", "A", "CC0", "確認済み", kind="謎"),
            ),
            ("値が文字列でない", {"出典URL": 3}),
        ]:
            with self.subTest(name):
                p = self.ledger({"assets/ar.jpg": e})
                with self.assertRaises(ValueError) as cm:
                    assets_ledger.load(p)
                self.assertIn("assets/ar.jpg", str(cm.exception))
        self.path.write_text("{壊れ", encoding="utf-8")
        with self.assertRaises(ValueError):
            assets_ledger.load(self.path)
        with self.assertRaises(FileNotFoundError):
            assets_ledger.load(self.d / "none.json")

    def test_complete_ledger_passes(self):
        p = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://commons.example/ar", "A氏", "CC BY 4.0", scene="動機: AR"
                ),
                "assets/robot.mp4": entry(
                    "https://videos.example/r",
                    "B社",
                    "Pexels License",
                    scene="動機: ロボット",
                ),
            }
        )
        code, out = run(["check", p])
        self.assertEqual(code, 0, out)
        code, out = run(["check", p, "--public"])
        self.assertEqual(code, 0, out)

    def test_missing_file_url_and_license_are_named(self):
        p = self.ledger(
            {
                "assets/none.jpg": entry("https://x.example/a", "A", "CC0"),
                "assets/ar.jpg": entry("", "A", "CC0"),
                "assets/robot.mp4": entry("https://x.example/r", "", ""),
            }
        )
        code, out = run(["check", p])
        self.assertEqual(code, 1)
        self.assertIn("none.jpg", out)  # ファイルが無い
        self.assertIn("出典URL", out)
        self.assertIn("ライセンス", out)

    def test_provisional_or_unknown_license_blocks_public_only(self):
        p = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://x.example/a", "A", "不明", "仮", "動機: AR"
                )
            }
        )
        code, out = run(["check", p])
        self.assertEqual(code, 0, out)  # 私的な検証なら通る(警告のみ)
        self.assertIn("仮", out)
        code, out = run(["check", p, "--public"])
        self.assertEqual(code, 1)
        self.assertIn("ar.jpg", out)

    def test_attribution_status_needs_author_and_date(self):
        ok = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://x.example/a",
                    "A社",
                    "不明",
                    "出典表示",
                    "動機: AR",
                    date="2026-10-27",
                )
            }
        )
        code, out = run(["check", ok, "--public"])
        self.assertEqual(code, 0, out)  # ライセンス不明でも、出典表示なら公開用で通る
        no_date = self.ledger(
            {"assets/ar.jpg": entry("https://x.example/a", "A社", "不明", "出典表示")}
        )
        code, out = run(["check", no_date])
        self.assertEqual(code, 1)
        self.assertIn("取得日", out)
        no_author = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://x.example/a", "", "不明", "出典表示", date="2026-10-27"
                )
            }
        )
        code, out = run(["check", no_author])
        self.assertEqual(code, 1)
        self.assertIn("作者", out)

    def test_credits_mark_attribution_only_assets(self):
        p = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://x.example/a",
                    "A社",
                    "不明",
                    "出典表示",
                    "動機: AR",
                    date="2026-10-27",
                )
            }
        )
        code, out = run(["credits", p])
        self.assertEqual(code, 0, out)
        self.assertIn("出典表示", out)
        self.assertIn("A社", out)

    def test_short_credit_for_the_screen(self):
        cc = {
            "作者": "A氏",
            "ライセンス": "CC BY 4.0",
            "出典URL": "https://commons.example/x",
            "状態": "確認済み",
        }
        self.assertEqual(assets_ledger.short_credit(cc), "A氏 / CC BY 4.0")
        att = {
            "作者": "B社",
            "ライセンス": "不明",
            "出典URL": "https://www.video.example/watch?v=1",
            "状態": "出典表示",
        }
        self.assertEqual(assets_ledger.short_credit(att), "出典: B社 (video.example)")

    def test_credits_lines(self):
        p = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://commons.example/ar", "A氏", "CC BY 4.0", scene="動機: AR"
                ),
                "assets/robot.mp4": entry(
                    "https://videos.example/r", "B社", "不明", "仮", "動機: ロボット"
                ),
            }
        )
        code, out = run(["credits", p])
        self.assertEqual(code, 0, out)
        for s in ("動機: AR", "A氏", "CC BY 4.0", "https://commons.example/ar", "(仮)"):
            self.assertIn(s, out)


class CitationTests(LedgerBase):
    """論文の図・公式動画の引用(references/attribution.md): 書誌と位置を持ち、論文の書式で出す。"""

    CITE = "Piedade et al., SLAM-MER, CVPR 2026"

    def cited(self, **kw):
        base = dict(
            url="https://example.org/paper",
            author="Piedade ほか",
            lic="不明",
            status="出典表示",
            scene="冒頭: 概要図",
            date="2026-10-28",
            kind="論文の図",
            cite=self.CITE,
            loc="Fig. 2",
        )
        base.update(kw)
        return entry(**base)

    def test_short_credit_uses_the_citation_format(self):
        row = {**self.cited(), "ファイル": "assets/ar.jpg"}
        self.assertEqual(
            assets_ledger.short_credit(row),
            "Piedade et al., SLAM-MER, CVPR 2026, Fig. 2",
        )
        row["位置"] = ""
        self.assertEqual(
            assets_ledger.short_credit(row), self.CITE
        )  # 位置が無くても書誌は出る

    def test_credit_line_has_citation_and_locator_and_url(self):
        p = self.ledger({"assets/ar.jpg": self.cited(kind="公式動画", loc="0:45–0:58")})
        code, out = run(["credits", p])
        self.assertEqual(code, 0, out)
        for s in (self.CITE, "0:45–0:58", "https://example.org/paper", "出典表示"):
            self.assertIn(s, out)

    def test_citation_kinds_require_bibliography_and_locator(self):
        for kind in ("論文の図", "公式動画"):
            for missing, word in [("cite", "書誌"), ("loc", "位置")]:
                with self.subTest(kind=kind, missing=missing):
                    p = self.ledger(
                        {"assets/ar.jpg": self.cited(kind=kind, **{missing: ""})}
                    )
                    code, out = run(["check", p])
                    self.assertEqual(code, 1, out)
                    self.assertIn(word, out)

    def test_cc_material_does_not_need_bibliography(self):
        p = self.ledger(
            {
                "assets/ar.jpg": entry(
                    "https://x.example/a", "A", "CC BY 4.0", kind="CC素材"
                )
            }
        )
        self.assertEqual(run(["check", p, "--public"])[0], 0)

    def test_provisional_citation_is_blocked_for_public_use(self):
        p = self.ledger({"assets/ar.jpg": self.cited(status="仮")})
        code, out = run(["check", p, "--public"])
        self.assertEqual(code, 1)
        self.assertIn("仮", out)


class EditCommandTests(LedgerBase):
    def add(self, *extra, file="assets/ar.jpg"):
        return run(
            [
                "add",
                str(self.path),
                file,
                "--url",
                "https://x.example/a",
                "--author",
                "A氏",
                "--license",
                "CC BY 4.0",
                *extra,
            ]
        )

    def test_add_creates_the_ledger_and_defaults_to_provisional_with_todays_date(self):
        code, out = self.add("--scene", "動機: AR")
        self.assertEqual(code, 0, out)
        row = assets_ledger.load(self.path)[0]
        self.assertEqual(
            (row["状態"], row["場面"], row["作者"]), ("仮", "動機: AR", "A氏")
        )
        self.assertRegex(row["取得日"], r"^\d{4}-\d{2}-\d{2}$")

    def test_add_with_citation_fields(self):
        code, out = self.add(
            "--status",
            "出典表示",
            "--kind",
            "論文の図",
            "--citation",
            "X et al., 2026",
            "--locator",
            "Fig. 1",
        )
        self.assertEqual(code, 0, out)
        row = assets_ledger.load(self.path)[0]
        self.assertEqual(
            (row["種別"], row["書誌"], row["位置"]),
            ("論文の図", "X et al., 2026", "Fig. 1"),
        )

    def test_add_existing_file_is_a_conflict_and_changes_nothing(self):
        self.add()
        before = self.path.read_bytes()
        code, out = self.add("--scene", "別")
        self.assertEqual(code, 3, out)
        self.assertEqual(self.path.read_bytes(), before)

    def test_add_rejects_bad_status_or_kind(self):
        self.add()
        before = self.path.read_bytes()
        self.assertEqual(self.add("--status", "たぶん", file="assets/robot.mp4")[0], 2)
        self.assertEqual(self.add("--kind", "謎", file="assets/robot.mp4")[0], 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_set_changes_only_given_fields(self):
        self.add("--scene", "動機: AR")
        code, out = run(
            [
                "set",
                str(self.path),
                "assets/ar.jpg",
                "--status",
                "確認済み",
                "--note",
                "縮小のみ",
            ]
        )
        self.assertEqual(code, 0, out)
        row = assets_ledger.load(self.path)[0]
        self.assertEqual(
            (row["状態"], row["メモ"], row["場面"], row["作者"]),
            ("確認済み", "縮小のみ", "動機: AR", "A氏"),
        )

    def test_set_and_rm_missing_entry(self):
        self.add()
        self.assertEqual(
            run(["set", str(self.path), "assets/none.jpg", "--note", "x"])[0], 1
        )
        self.assertEqual(run(["rm", str(self.path), "assets/none.jpg"])[0], 1)

    def test_rm_removes_only_the_record_not_the_file(self):
        self.add()
        self.add(file="assets/robot.mp4")
        code, out = run(["rm", str(self.path), "assets/ar.jpg"])
        self.assertEqual(code, 0, out)
        self.assertEqual(
            [r["ファイル"] for r in assets_ledger.load(self.path)], ["assets/robot.mp4"]
        )
        self.assertTrue(
            (self.d / "assets" / "ar.jpg").exists()
        )  # 素材ファイルは消さない

    def test_list_prints_one_line_per_asset(self):
        self.add("--scene", "動機: AR")
        code, out = run(["list", str(self.path)])
        self.assertEqual(code, 0, out)
        self.assertIn("assets/ar.jpg", out)
        self.assertIn("仮", out)

    def test_corrupt_ledger_is_refused_without_change(self):
        self.path.write_text("{壊れ", encoding="utf-8")
        for argv in (
            [
                "add",
                str(self.path),
                "assets/ar.jpg",
                "--url",
                "https://x",
                "--license",
                "CC0",
            ],
            ["set", str(self.path), "assets/ar.jpg", "--note", "x"],
            ["rm", str(self.path), "assets/ar.jpg"],
        ):
            with self.subTest(argv=argv[0]):
                self.assertEqual(run(argv)[0], 2)
                self.assertEqual(self.path.read_text(encoding="utf-8"), "{壊れ")

    def test_export_writes_an_excel_friendly_csv(self):
        self.add("--scene", "動機: AR, 写真")
        out_csv = self.d / "assets.csv"
        code, out = run(["export", str(self.path), "--out", str(out_csv)])
        self.assertEqual(code, 0, out)
        raw = out_csv.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        with out_csv.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(
            rows[0][:5], ["ファイル", "出典URL", "作者", "ライセンス", "状態"]
        )
        self.assertEqual(rows[1][0], "assets/ar.jpg")
        self.assertIn("動機: AR, 写真", rows[1])

    def test_concurrent_adds_lose_no_asset(self):
        names = [f"assets/f{i}.jpg" for i in range(6)]
        ps = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPTS / "assets_ledger.py"),
                    "add",
                    str(self.path),
                    n,
                    "--url",
                    "https://x.example/a",
                    "--license",
                    "CC0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for n in names
        ]
        for p in ps:
            _, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(
            sorted(r["ファイル"] for r in assets_ledger.load(self.path)), sorted(names)
        )

    def test_init_racing_with_adds_never_wipes_them(self):
        """A-03: init と add が同時でも、追加済みの素材を空の台帳で消さない。"""
        names = [f"assets/g{i}.jpg" for i in range(5)]
        script = str(SCRIPTS / "assets_ledger.py")
        procs = [
            subprocess.Popen(
                [
                    sys.executable,
                    script,
                    "add",
                    str(self.path),
                    n,
                    "--url",
                    "https://x.example/a",
                    "--license",
                    "CC0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for n in names
        ]
        procs += [
            subprocess.Popen(
                [sys.executable, script, "init", str(self.path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(3)
        ]
        for p in procs:
            p.communicate(timeout=60)
        self.assertEqual(
            sorted(r["ファイル"] for r in assets_ledger.load(self.path)), sorted(names)
        )


class StoreFormatTests(LedgerBase):
    def test_ledger_is_written_through_state_store_format(self):
        run(["init", str(self.path)])
        run(
            [
                "add",
                str(self.path),
                "assets/ar.jpg",
                "--url",
                "https://x.example/a",
                "--license",
                "CC0",
            ]
        )
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], 1)
        self.assertIn("assets/ar.jpg", doc["entries"])
        self.assertEqual(state_store.Store(self.path).read().entries, doc["entries"])


if __name__ == "__main__":
    unittest.main()
