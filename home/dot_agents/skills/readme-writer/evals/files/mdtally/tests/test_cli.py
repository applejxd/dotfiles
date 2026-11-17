import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mdtally.cli import count_words, reading_minutes  # noqa: E402


class CountTests(unittest.TestCase):
    def test_code_blocks_are_ignored(self):
        self.assertEqual(count_words("hello world\n```\nignored words here\n```\n"), 2)

    def test_japanese_counts_per_character(self):
        self.assertEqual(count_words("日本語です"), 5)

    def test_reading_minutes(self):
        self.assertEqual(reading_minutes(0), 0)
        self.assertEqual(reading_minutes(1), 1)
        self.assertEqual(reading_minutes(231), 2)


if __name__ == "__main__":
    unittest.main()
