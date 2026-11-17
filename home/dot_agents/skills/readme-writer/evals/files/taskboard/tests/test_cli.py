import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from taskboard import cli, store  # noqa: E402


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["TB_DATA_DIR"] = self.tmp.name

    def test_add_done_rm(self):
        self.assertEqual(cli.main(["add", "write docs", "--tag", "docs"]), 0)
        self.assertEqual(store.load()[0]["title"], "write docs")
        self.assertEqual(cli.main(["done", "1"]), 0)
        self.assertTrue(store.load()[0]["done"])
        self.assertEqual(cli.main(["rm", "1"]), 0)
        self.assertEqual(store.load(), [])

    def test_unknown_id(self):
        self.assertEqual(cli.main(["done", "9"]), 1)

    def test_bad_due(self):
        self.assertEqual(cli.main(["add", "x", "--due", "tomorrow"]), 2)


if __name__ == "__main__":
    unittest.main()
