"""独立レビュー(2026-11-16)の指摘を回帰テストにしたもの: 安全・堅牢性・Markdown と GitHub の規則との一致。"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import SCRIPTS, RepoCase, load

collect_facts = load("collect_facts")
check_readme = load("check_readme")

GOOD = """# Demo

A small tool that counts words.

## Install

```bash
pip install demo
```

## Usage

```bash
demo README.md
```
"""
MIT = "MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted, free of charge, to any person\n"


class Base(RepoCase):
    """repo はテンポラリの 1 段下に作り、外側(兄弟)に秘密のファイルを置けるようにする。"""

    def setUp(self):
        self._outer = tempfile.TemporaryDirectory()
        self.addCleanup(self._outer.cleanup)
        self.outer = Path(self._outer.name)
        self.repo = self.outer / "repo"
        self.repo.mkdir()

    def check(self, text):
        path = self.write("README.md", text)
        return check_readme.check(path, self.repo)

    def ids(self, findings, severity=None):
        return {f["id"] for f in findings if severity is None or f["severity"] == severity}


class OutsideRepoTests(Base):
    def test_links_outside_the_repo_are_not_read(self):
        (self.outer / "private.md").write_text("# Secret\n", encoding="utf-8")
        for target in ("../private.md#secret", "%2e%2e/private.md#secret"):
            with self.subTest(target=target):
                findings = self.check(GOOD + f"\n[x]({target})\n")
                self.assertIn("link-outside-repo", self.ids(findings, "warning"))
                self.assertNotIn("anchor-missing", self.ids(findings))
                self.assertNotIn("link-missing", self.ids(findings))

    def test_symlink_pointing_outside_is_not_followed(self):
        (self.outer / "private.md").write_text("# Secret\n", encoding="utf-8")
        (self.repo / "link.md").symlink_to(self.outer / "private.md")
        findings = self.check(GOOD + "\n[x](link.md#secret)\n")
        self.assertIn("link-outside-repo", self.ids(findings))
        self.assertNotIn("anchor-missing", self.ids(findings))

    def test_inner_dotdot_that_stays_inside_is_fine(self):
        self.write("docs/a.md", "# A\n")
        self.write("docs/sub/b.md", "# B\n")
        findings = self.check(GOOD + "\n[x](docs/sub/../a.md#a)\n")
        self.assertEqual(self.ids(findings, "error"), set(), findings)

    def test_manifest_symlink_outside_is_not_read(self):
        (self.outer / "evil.toml").write_text('[project]\nname = "leaked"\n', encoding="utf-8")
        (self.repo / "pyproject.toml").symlink_to(self.outer / "evil.toml")
        result = collect_facts.collect(self.repo)
        self.assertEqual(result["facts"], [])
        self.assertTrue(any("外" in w["message"] for w in result["warnings"]))

    def test_workflow_directory_symlink_outside_is_not_read(self):
        (self.outer / "wf").mkdir()
        (self.outer / "wf" / "x.yml").write_text("steps:\n  - run: leaked\n", encoding="utf-8")
        (self.repo / ".github").mkdir()
        (self.repo / ".github" / "workflows").symlink_to(self.outer / "wf")
        result = collect_facts.collect(self.repo)
        self.assertEqual(result["ci"], [])
        self.assertTrue(result["warnings"])


class LimitTests(Base):
    def test_huge_files_are_skipped_with_a_warning(self):
        self.write("LICENSE", MIT + "x" * (collect_facts.MAX_READ + 10))
        result = collect_facts.collect(self.repo)
        self.assertFalse(result["license"]["present"])
        self.assertTrue(any(w["file"] == "LICENSE" for w in result["warnings"]))

    def test_huge_readme_is_an_error_and_is_read_only_partially(self):
        findings = self.check(GOOD + "x" * (520 * 1024))
        self.assertIn("github-truncates", self.ids(findings, "error"))

    def test_linked_huge_markdown_is_not_parsed(self):
        self.write("docs/big.md", "# Big\n" + "x" * (collect_facts.MAX_READ + 10))
        findings = self.check(GOOD + "\n[x](docs/big.md#nope)\n")
        self.assertNotIn("anchor-missing", self.ids(findings))

    def test_pathological_lines_finish_quickly(self):
        evil = ["# A" + " " * 300000 + "B", "![" * 100000, "[a" * 100000, "<img " * 100000, "`" + "a" * 100000]
        start = time.monotonic()
        for line in evil:
            self.check(GOOD + "\n" + line + "\n")
        self.assertLess(time.monotonic() - start, 5)

    def test_parse_heading_is_linear_and_correct(self):
        self.assertEqual(check_readme.parse_heading("## Title ##"), (2, "Title"))
        self.assertEqual(check_readme.parse_heading("# C#"), (1, "C#"))
        self.assertIsNone(check_readme.parse_heading("#NoSpace"))
        self.assertIsNone(check_readme.parse_heading("    # indented code"))


class ReadOnlyTests(Base):
    def test_cli_does_not_write_bytecode_next_to_the_scripts(self):
        scripts = self.outer / "scripts"
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        self.write("README.md", GOOD)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run(
            [sys.executable, str(scripts / "check_readme.py"), str(self.repo / "README.md"), "--repo", str(self.repo)],
            capture_output=True, text=True, env=env,
        )
        self.assertFalse((scripts / "__pycache__").exists())


class MalformedManifestTests(Base):
    def test_type_confused_manifests_become_warnings(self):
        cases = {
            "package.json": "[]",
            "pyproject.toml": "[project]\nscripts = 1\ndependencies = 5\n",
        }
        for name, body in cases.items():
            with self.subTest(file=name):
                self.write(name, body)
                result = collect_facts.collect(self.repo)
                self.assertTrue(result["warnings"], result)
                self.write("README.md", GOOD)
                check_readme.check(self.repo / "README.md", self.repo)  # 例外を出さない

    def test_wrong_inner_types(self):
        self.write("package.json", '{"scripts": ["a"], "engines": 3, "bin": 5, "dependencies": []}')
        self.write("mise.toml", "tasks = 1\ntools = 2\n")
        result = collect_facts.collect(self.repo)
        self.assertTrue(result["warnings"])

    def test_string_bin_points_at_the_bin_line(self):
        self.write("package.json", '{\n  "name": "demo",\n  "bin": "cli.js"\n}\n')
        commands = collect_facts.collect(self.repo)["commands"]
        self.assertEqual(commands[0]["source"], "package.json:3")


class AnchorTests(Base):
    def test_percent_encoded_fragment_matches_a_japanese_heading(self):
        findings = self.check("# デモ\n\n説明です。\n\n## 使い方\n\nx\n\n[a](#%E4%BD%BF%E3%81%84%E6%96%B9)\n")
        self.assertNotIn("anchor-missing", self.ids(findings))

    def test_duplicate_headings_follow_github_suffixes(self):
        doc = check_readme.Doc("# Foo\n\n## Foo\n\n## Foo-1\n")
        self.assertEqual(doc.anchors(), {"foo", "foo-1", "foo-1-1"})


class MarkdownTests(Base):
    def test_longer_fence_is_not_closed_by_a_shorter_one(self):
        text = GOOD + "\n````text\n```\n[x](missing.md)\n```\n````\n"
        self.assertNotIn("link-missing", self.ids(self.check(text)))

    def test_mixed_fence_chars_do_not_close(self):
        text = GOOD + "\n```text\n~~~\n[x](missing.md)\n```\n"
        self.assertNotIn("link-missing", self.ids(self.check(text)))

    def test_setext_headings(self):
        findings = self.check("Demo\n====\n\nA small tool that counts words.\n\nInstall\n-------\n\nx\n")
        self.assertNotIn("h1-missing", self.ids(findings))

    def test_h1_html_inside_code_is_not_counted(self):
        findings = self.check("# Real\n\nA tool.\n\n## Usage\n\n```html\n<h1>x</h1>\n```\n")
        self.assertNotIn("h1-multiple", self.ids(findings))

    def test_front_matter_is_skipped(self):
        findings = self.check("---\ntitle: x\n---\n# Demo\n\nA tool.\n\n## Usage\n\nx\n")
        self.assertEqual(self.ids(findings, "error"), set(), findings)

    def test_parentheses_in_link_destination(self):
        self.write("docs/a(b).md", "x")
        self.assertNotIn("link-missing", self.ids(self.check(GOOD + "\n[g](docs/a(b).md)\n")))


class CommandTests(Base):
    def test_pip_via_python_module_is_checked(self):
        self.write("pyproject.toml", '[project]\nname = "demo"\n')
        findings = self.check(GOOD.replace("pip install demo", "python3 -m pip install demos"))
        self.assertIn("install-name-differs", self.ids(findings))

    def test_script_path_without_extension(self):
        findings = self.check(GOOD + "\n```bash\nbash scripts/run\n```\n")
        self.assertIn("command-missing", self.ids(findings, "error"))

    def test_make_option_values_are_not_targets(self):
        self.write("Makefile", "test:\n\tx\n")
        findings = self.check(GOOD + "\n```bash\nmake -j 2 test\nmake -j4 test\n```\n")
        self.assertNotIn("command-missing", self.ids(findings))


class LicenseTests(Base):
    def test_lgpl_versions_are_distinguished(self):
        self.write("LICENSE", "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n")
        self.assertEqual(collect_facts.collect(self.repo)["license"]["spdx"], "LGPL-2.1")
        findings = self.check(GOOD + "\n## License\n\nLGPL-2.1\n")
        self.assertNotIn("license-mismatch", self.ids(findings))

    def test_honest_no_license_statement_is_not_a_claim(self):
        findings = self.check(GOOD + "\n## License\n\nNo license has been chosen yet.\n")
        self.assertNotIn("license-missing-file", self.ids(findings))


if __name__ == "__main__":
    unittest.main()
