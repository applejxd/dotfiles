import json
import subprocess
import sys
import unittest

from helpers import SCRIPTS, RepoCase, load

collect_facts = load("collect_facts")

PYPROJECT = """[project]
name = "demo-tool"
version = "0.3.1"
description = "A demo tool"
requires-python = ">=3.11"

[project.scripts]
demo = "demo.cli:main"
"""

PACKAGE_JSON = """{
  "name": "demo-js",
  "version": "1.2.0",
  "description": "JS demo",
  "scripts": {"build": "tsc", "test": "node --test"},
  "engines": {"node": ">=20"},
  "bin": {"demo-js": "bin/cli.js"}
}
"""

MIT = "MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted, free of charge, to any person\n"


def by_key(result, key):
    return [f for f in result["facts"] if f["key"] == key]


class CollectFactsTests(RepoCase):
    def test_ac01_pyproject_facts_with_line_numbers(self):
        self.write("pyproject.toml", PYPROJECT)
        result = collect_facts.collect(self.repo)
        self.assertEqual(by_key(result, "name")[0]["value"], "demo-tool")
        self.assertEqual(by_key(result, "name")[0]["source"], "pyproject.toml:2")
        self.assertEqual(by_key(result, "requires-python")[0]["value"], ">=3.11")
        self.assertEqual(by_key(result, "version")[0]["source"], "pyproject.toml:3")
        scripts = [c for c in result["commands"] if c["kind"] == "console_script"]
        self.assertEqual([c["invocation"] for c in scripts], ["demo"])

    def test_ac02_package_json_facts(self):
        self.write("package.json", PACKAGE_JSON)
        result = collect_facts.collect(self.repo)
        self.assertEqual(by_key(result, "name")[0]["value"], "demo-js")
        self.assertEqual(by_key(result, "engines.node")[0]["value"], ">=20")
        npm = {c["invocation"]: c for c in result["commands"] if c["kind"] == "npm"}
        self.assertEqual(set(npm), {"npm run build", "npm test"})
        self.assertTrue(npm["npm run build"]["source"].startswith("package.json:"))
        self.assertEqual([c["invocation"] for c in result["commands"] if c["kind"] == "bin"], ["demo-js"])

    def test_ac03_make_mise_just_commands(self):
        self.write("Makefile", ".PHONY: test\ntest:\n\tpytest\n\nbuild: ## ビルドする\n\techo\n")
        self.write(
            "mise.toml",
            '[tasks.test]\ndescription = "テストを実行する"\nrun = "pytest"\n\n[tasks."skill:new"]\nrun = "x"\n',
        )
        self.write("justfile", "default:\n    just --list\n\nlint:\n    ruff check\n")
        result = collect_facts.collect(self.repo)
        invocations = {c["invocation"] for c in result["commands"]}
        self.assertTrue({"make test", "make build", "mise run test", "mise run skill:new", "just lint"} <= invocations)
        mise_test = next(c for c in result["commands"] if c["invocation"] == "mise run test")
        self.assertEqual(mise_test["description"], "テストを実行する")
        self.assertEqual(mise_test["source"], "mise.toml:1")
        self.assertNotIn("make .PHONY", invocations)

    def test_ac04_license_detection(self):
        self.write("LICENSE", MIT)
        self.assertEqual(collect_facts.collect(self.repo)["license"], {"present": True, "file": "LICENSE", "spdx": "MIT"})

    def test_ac04_license_absent_is_explicit(self):
        self.assertEqual(collect_facts.collect(self.repo)["license"], {"present": False, "file": None, "spdx": None})

    def test_ac05_existing_readme_and_language(self):
        self.write("README.md", "# デモ\n\nこれは日本語の説明です。インストールして使います。\n")
        result = collect_facts.collect(self.repo)
        self.assertEqual(result["readme"], {"present": True, "path": "README.md", "language": "ja"})

    def test_ac05_english_readme_and_no_readme(self):
        self.write("README.md", "# Demo\n\nThis is a demo of the tool.\n")
        self.assertEqual(collect_facts.collect(self.repo)["readme"]["language"], "en")
        other = self.repo / "empty"
        other.mkdir()
        self.assertEqual(collect_facts.collect(other)["readme"], {"present": False, "path": None, "language": None})

    def test_ac06_broken_manifest_goes_to_warnings(self):
        self.write("pyproject.toml", "[project\nname = ")
        self.write("package.json", "{not json")
        result = collect_facts.collect(self.repo)
        files = {w["file"] for w in result["warnings"]}
        self.assertEqual(files, {"pyproject.toml", "package.json"})

    def test_ac06_does_not_write_into_repo(self):
        self.write("pyproject.toml", PYPROJECT)
        before = sorted(p.name for p in self.repo.rglob("*"))
        collect_facts.collect(self.repo)
        self.assertEqual(sorted(p.name for p in self.repo.rglob("*")), before)

    def test_ci_run_steps_and_tree(self):
        self.write(".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: make test\n      - run: |\n          npm ci\n          npm test\n")
        self.write("src/a.py", "")
        self.write(".hidden/x", "")
        result = collect_facts.collect(self.repo)
        self.assertEqual(result["ci"][0]["file"], ".github/workflows/ci.yml")
        self.assertEqual(result["ci"][0]["run"], ["make test", "npm ci", "npm test"])
        self.assertIn("src/", result["tree"])
        self.assertNotIn(".hidden/", result["tree"])

    def test_ac05_cli_outputs_json(self):
        self.write("pyproject.toml", PYPROJECT)
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "collect_facts.py"), str(self.repo)],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(data["facts"][0]["key"], "name")


if __name__ == "__main__":
    unittest.main()
