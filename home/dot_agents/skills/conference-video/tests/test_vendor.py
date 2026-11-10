"""vendor の無改変の保証: UPSTREAM.md のハッシュ表と実ファイルを照合する(特性テスト)。"""

import hashlib
import re
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
UPSTREAM = VENDOR / "UPSTREAM.md"
BASE = VENDOR / "manim-skill"


def manifest() -> dict:
    text = UPSTREAM.read_text(encoding="utf-8")
    return {
        m.group(2): m.group(1)
        for m in re.finditer(r"^([0-9a-f]{64})  (\S+)$", text, re.MULTILINE)
    }


class VendorIntegrityTests(unittest.TestCase):
    def test_every_vendored_file_is_listed_and_unmodified(self):
        listed = manifest()
        self.assertGreaterEqual(len(listed), 7)
        actual = {
            p.relative_to(BASE).as_posix()
            for p in BASE.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        self.assertEqual(
            set(listed), actual, "表にないファイル、または欠けたファイルがある"
        )
        for rel, digest in listed.items():
            with self.subTest(file=rel):
                got = hashlib.sha256((BASE / rel).read_bytes()).hexdigest()
                self.assertEqual(got, digest, f"{rel} が上流から変わっている")

    def test_license_and_source_are_recorded(self):
        self.assertIn("MIT License", (BASE / "LICENSE").read_text(encoding="utf-8"))
        text = UPSTREAM.read_text(encoding="utf-8")
        self.assertRegex(text, r"[0-9a-f]{40}")  # 取得元のコミット
        self.assertIn("github.com/Yusuke710/manim-skill", text)


if __name__ == "__main__":
    unittest.main()
