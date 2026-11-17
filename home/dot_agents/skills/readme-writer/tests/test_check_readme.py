import json
import subprocess
import sys
import unittest

from helpers import SCRIPTS, RepoCase, load

check_readme = load("check_readme")

GOOD = """# Demo

A small tool that counts words in Markdown files.

## Install

```bash
pip install demo
```

## Usage

```bash
demo README.md
```

## License

MIT. See [LICENSE](LICENSE).
"""

MIT = "MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted, free of charge, to any person\n"


class CheckReadmeTests(RepoCase):
    def check(self, text, **files):
        for name, body in files.items():
            self.write(name.replace("__", "/").replace("_dot_", "."), body)
        path = self.write("README.md", text)
        return check_readme.check(path, self.repo)

    def ids(self, findings, severity=None):
        return {f["id"] for f in findings if severity is None or f["severity"] == severity}

    def test_clean_readme_has_no_errors(self):
        findings = self.check(GOOD, LICENSE=MIT)
        self.assertEqual(self.ids(findings, "error"), set(), findings)

    def test_ac07_missing_relative_link_target(self):
        findings = self.check(GOOD + "\nSee [guide](docs/guide.md).\n", LICENSE=MIT)
        self.assertIn("link-missing", self.ids(findings, "error"))

    def test_ac07_existing_link_and_anchor_ok(self):
        findings = self.check(
            GOOD + "\n[g](docs/guide.md#getting-started) [u](#usage)\n",
            LICENSE=MIT, docs__guide_dot_md="# Guide\n\n## Getting Started\n",
        )
        self.assertEqual(self.ids(findings, "error"), set(), findings)

    def test_ac07_missing_anchor(self):
        findings = self.check(
            GOOD + "\n[g](docs/guide.md#nope) [u](#nowhere)\n",
            LICENSE=MIT, docs__guide_dot_md="# Guide\n",
        )
        errors = [f for f in findings if f["id"] == "anchor-missing"]
        self.assertEqual(len(errors), 2)

    def test_ac07_links_in_code_blocks_are_ignored(self):
        findings = self.check(GOOD + "\n```md\n[x](nothing.md)\n```\n", LICENSE=MIT)
        self.assertNotIn("link-missing", self.ids(findings))

    def test_ac08_images(self):
        findings = self.check(GOOD + "\n![](img/a.png) ![diagram](img/b.png)\n", LICENSE=MIT, img__b_dot_png="x")
        self.assertIn("image-missing", self.ids(findings, "error"))
        self.assertIn("image-alt", self.ids(findings, "warning"))
        self.assertEqual(len([f for f in findings if f["id"] == "image-missing"]), 1)

    def test_ac09_make_npm_mise_just_targets(self):
        readme = GOOD + "\n```bash\nmake test\nmake nope\nnpm run build\nnpm run ghost\nmise run lint\nmise run ghost2\njust fmt\njust ghost3\n```\n"
        findings = self.check(
            readme, LICENSE=MIT,
            Makefile="test:\n\tx\n",
            package_dot_json='{"scripts": {"build": "x"}}',
            mise_dot_toml='[tasks.lint]\nrun = "x"\n',
            justfile="fmt:\n    x\n",
        )
        missing = sorted(f["message"] for f in findings if f["id"] == "command-missing")
        self.assertEqual(len(missing), 4, missing)
        for ghost in ("make nope", "npm run ghost", "mise run ghost2", "just ghost3"):
            self.assertTrue(any(ghost in m for m in missing), (ghost, missing))

    def test_ac09_script_paths(self):
        readme = GOOD + "\n```bash\npython scripts/run.py --x\nbash scripts/missing.sh\nuv run tools/gone.py\n```\n"
        findings = self.check(readme, LICENSE=MIT, scripts__run_dot_py="")
        missing = [f["message"] for f in findings if f["id"] == "command-missing"]
        self.assertEqual(len(missing), 2, missing)

    def test_ac09_prompt_prefix_and_shell_fence_variants(self):
        readme = GOOD + "\n```console\n$ make ghost\n```\n"
        findings = self.check(readme, LICENSE=MIT, Makefile="test:\n\tx\n")
        self.assertIn("command-missing", self.ids(findings, "error"))

    def test_ac09_install_name_must_match_manifest_or_dependencies(self):
        readme = GOOD + "\n```bash\npip install demo[extra]\npip install numpy\npip install demos\npip install .\npip install -e .\n```\n"
        findings = self.check(
            readme, LICENSE=MIT,
            pyproject_dot_toml='[project]\nname = "demo"\ndependencies = ["numpy>=1"]\n',
        )
        wrong = [f["message"] for f in findings if f["id"] == "install-name-differs"]
        self.assertEqual(len(wrong), 1, wrong)
        self.assertIn("`demos`", wrong[0])
        self.assertEqual(self.ids(findings, "error"), set())

    def test_ac09_npm_install_name(self):
        readme = GOOD + "\n```bash\nnpm install -g demo\nnpm i @scope/other\nnpm install left-pad\nnpm install demos\n```\n"
        findings = self.check(readme, LICENSE=MIT, package_dot_json='{"name": "demo", "dependencies": {"left-pad": "1"}}')
        wrong = [f["message"] for f in findings if f["id"] == "install-name-differs"]
        self.assertEqual(len(wrong), 1, wrong)
        self.assertIn("`demos`", wrong[0])

    def test_ac10_placeholders(self):
        findings = self.check(GOOD + "\nTODO: write this\n\nclone <your-repo-url>\n", LICENSE=MIT)
        self.assertIn("placeholder-todo", self.ids(findings, "error"))
        self.assertIn("placeholder-hole", self.ids(findings, "warning"))

    def test_ac11_license_claimed_without_file(self):
        findings = self.check(GOOD)
        self.assertIn("license-missing-file", self.ids(findings, "error"))

    def test_ac11_license_mismatch(self):
        findings = self.check(GOOD.replace("MIT.", "Apache-2.0."), LICENSE=MIT)
        self.assertIn("license-mismatch", self.ids(findings, "error"))

    def test_ac11_license_file_but_unmentioned(self):
        text = GOOD.split("## License")[0]
        findings = self.check(text, LICENSE=MIT)
        self.assertIn("license-unmentioned", self.ids(findings, "warning"))
        self.assertNotIn("license-missing-file", self.ids(findings))

    def test_ac12_headings(self):
        findings = self.check("## Only h2\n\ntext\n", LICENSE=MIT)
        self.assertIn("h1-missing", self.ids(findings, "error"))
        findings = self.check("# A\n\ntext\n\n# B\n", LICENSE=MIT)
        self.assertIn("h1-multiple", self.ids(findings, "error"))

    def test_ac12_no_summary_and_no_install(self):
        findings = self.check("# Demo\n\n## Notes\n\ntext\n", LICENSE=MIT)
        self.assertIn("summary-missing", self.ids(findings, "warning"))
        self.assertIn("usage-missing", self.ids(findings, "warning"))

    def test_ac12_japanese_usage_headings_recognized(self):
        text = "# デモ\n\nMarkdown の語数を数える道具です。\n\n## インストール\n\nx\n\n## 使い方\n\ny\n"
        findings = self.check(text)
        self.assertNotIn("usage-missing", self.ids(findings))

    def test_ac13_style_warnings(self):
        badges = "\n".join(f"![b{i}](https://img.shields.io/badge/{i}-ok-green)" for i in range(7))
        text = GOOD.replace("# Demo\n", "# Demo\n\n" + badges + "\n", 1) + "\nA blazing fast tool.\n\n```\nplain\n```\n"
        findings = self.check(text, LICENSE=MIT)
        warnings = self.ids(findings, "warning")
        self.assertTrue({"badges-many", "hype-words", "fence-no-lang"} <= warnings, warnings)
        self.assertEqual(self.ids(findings, "error"), set())

    def test_ac14_external_links_are_listed_not_checked(self):
        findings = self.check(GOOD + "\n[x](https://example.invalid/page)\n", LICENSE=MIT)
        self.assertEqual(self.ids(findings, "error"), set())
        info = [f for f in findings if f["id"] == "external-unchecked"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["severity"], "info")
        self.assertIn("https://example.invalid/page", info[0]["message"])

    def test_inline_path_mentions(self):
        findings = self.check(GOOD + "\nSee `docs/real.md` and `docs/ghost.md`.\n", LICENSE=MIT, docs__real_dot_md="x")
        ghosts = [f for f in findings if f["id"] == "path-missing"]
        self.assertEqual(len(ghosts), 1)
        self.assertEqual(ghosts[0]["severity"], "warning")

    def test_ac15_exit_codes_and_json(self):
        self.write("LICENSE", MIT)
        self.write("README.md", GOOD)
        run = lambda *a: subprocess.run(
            [sys.executable, str(SCRIPTS / "check_readme.py"), str(self.repo / "README.md"), "--repo", str(self.repo), *a],
            capture_output=True, text=True,
        )
        self.assertEqual(run().returncode, 0)
        self.write("README.md", GOOD + "\n[x](nope.md)\n")
        proc = run("--json")
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any(f["id"] == "link-missing" for f in json.loads(proc.stdout)["findings"]))
        self.write("README.md", GOOD + "\nA blazing fast tool.\n")
        self.assertEqual(run().returncode, 0)
        self.assertEqual(run("--strict").returncode, 1)

    def test_find_repo_prefers_the_project_dir_over_an_outer_git_root(self):
        self.write(".git/HEAD", "")
        inner = self.write("tools/app/pyproject.toml", "[project]\nname='x'\n").parent
        readme = self.write("tools/app/README.md", GOOD)
        self.assertEqual(check_readme.find_repo(readme), inner.resolve())
        plain = self.write("docs/guide/README.md", GOOD)
        self.assertEqual(check_readme.find_repo(plain), self.repo.resolve())

    def test_ac15_text_output_is_human_readable(self):
        self.write("README.md", GOOD + "\n[x](nope.md)\n")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_readme.py"), str(self.repo / "README.md")],
            capture_output=True, text=True,
        )
        self.assertIn("error", proc.stdout)
        self.assertIn("link-missing", proc.stdout)
        self.assertIn("README.md:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
