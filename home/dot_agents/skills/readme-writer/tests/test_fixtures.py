"""同梱の評価用リポジトリ(evals/files/mdtally)に対する、台帳と検査の通し試験。"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, load

collect_facts = load("collect_facts")
check_readme = load("check_readme")

FIXTURE = SKILL / "evals" / "files" / "mdtally"
STALE = SKILL / "evals" / "files" / "stale-README.md"


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "mdtally"
        shutil.copytree(FIXTURE, self.repo)

    def test_facts_match_the_fixture(self):
        facts = collect_facts.collect(self.repo)
        values = {f["key"]: f["value"] for f in facts["facts"]}
        self.assertEqual(values["name"], "mdtally")
        self.assertEqual(values["requires-python"], ">=3.11")
        invocations = {c["invocation"] for c in facts["commands"]}
        self.assertEqual(invocations, {"mdtally", "make test"})
        self.assertEqual(facts["license"]["spdx"], "MIT")
        self.assertEqual(facts["ci"][0]["run"], ["make test"])
        self.assertFalse(facts["readme"]["present"])
        self.assertEqual(facts["warnings"], [])

    def test_stale_readme_is_caught(self):
        readme = self.repo / "README.md"
        shutil.copy(STALE, readme)
        findings = check_readme.check(readme, self.repo)
        ids = {f["id"] for f in findings}
        for expected in ("command-missing", "link-missing", "license-mismatch", "placeholder-todo", "badges-many", "hype-words", "fence-no-lang"):
            self.assertIn(expected, ids)
        missing = " ".join(f["message"] for f in findings if f["id"] == "command-missing")
        self.assertIn("make lint", missing)
        self.assertIn("scripts/run.py", missing)

    def test_eval_cases_point_at_existing_fixtures(self):
        data = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(data["skill_name"], SKILL.name)
        for case in data["evals"]:
            for name in case["files"]:
                with self.subTest(case=case["id"], fixture=name):
                    path = (SKILL / name).resolve()
                    self.assertTrue(path.is_relative_to(SKILL.resolve()))
                    self.assertTrue(path.exists())

    def test_trigger_evals_are_balanced(self):
        data = json.loads((SKILL / "evals" / "trigger-evals.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(sum(1 for d in data if d["should_trigger"]), 3)
        self.assertGreaterEqual(sum(1 for d in data if not d["should_trigger"]), 3)


class MoreFixtureTests(unittest.TestCase):
    """評価用リポジトリ taskboard(Python)と pingcheck(Node.js)。"""

    def facts(self, name):
        return collect_facts.collect(SKILL / "evals" / "files" / name)

    def test_taskboard_facts(self):
        facts = self.facts("taskboard")
        values = {f["key"]: f["value"] for f in facts["facts"]}
        self.assertEqual(values["name"], "taskboard-cli")
        self.assertEqual(values["requires-python"], ">=3.10")
        invocations = {c["invocation"] for c in facts["commands"]}
        self.assertEqual(invocations, {"tb", "make test", "make lint", "make fmt"})
        self.assertEqual(facts["license"]["spdx"], "Apache-2.0")

    def test_taskboard_drifted_readme_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "taskboard"
            shutil.copytree(SKILL / "evals" / "files" / "taskboard", repo)
            shutil.copy(SKILL / "evals" / "files" / "taskboard-drifted-README.md", repo / "README.md")
            ids = {f["id"] for f in check_readme.check(repo / "README.md", repo)}
        self.assertIn("install-name-differs", ids)

    def test_pingcheck_facts(self):
        facts = self.facts("pingcheck")
        values = {f["key"]: f["value"] for f in facts["facts"]}
        self.assertEqual(values["name"], "pingcheck")
        self.assertEqual(values["engines.node"], ">=18")
        invocations = {c["invocation"] for c in facts["commands"]}
        self.assertEqual(invocations, {"npm start", "npm test", "npm run lint", "pingcheck"})
        self.assertEqual(facts["license"]["spdx"], "MIT")
        self.assertEqual(facts["ci"][0]["run"], ["npm ci", "npm test"])

    def test_all_eval_cases_reference_existing_fixtures(self):
        data = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in data["evals"]], list(range(1, 9)))


if __name__ == "__main__":
    unittest.main()
