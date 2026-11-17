#!/usr/bin/env python3
"""README に書く事実を、リポジトリの実体から集めて JSON で返す(事実台帳)。

読むだけ: ネットワークに出ず、対象のコマンドを実行せず、リポジトリへ書き込まない。
使い方: python3 collect_facts.py <リポジトリのパス>
各項目は `source`(`ファイル:行`)を持つ。台帳に無い値は README に書かない。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from itertools import islice
from pathlib import Path

LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING", "COPYING.md")
README_NAMES = ("README.md", "README.markdown", "README.rst", "README.txt", "README")
SKIP_TREE = {"node_modules", "__pycache__", "venv", "target"}
MAX_READ = 1_000_000  # 1 ファイルあたりに読む上限(バイト)。超えたら読まず warnings に残す
MAX_ENTRIES = 2000  # ディレクトリの列挙の上限
MAX_WORKFLOWS = 50

# (SPDX, 全部含まれるべき語) を上から順に判定する。
LICENSE_RULES = (
    ("AGPL-3.0", ("gnu affero general public license",)),
    ("LGPL-3.0", ("gnu lesser general public license", "version 3")),
    ("LGPL-2.1", ("gnu lesser general public license",)),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("GPL-2.0", ("gnu general public license", "version 2")),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license",)),
    ("MIT", ("mit license",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms", "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("ISC", ("isc license",)),
    ("Unlicense", ("this is free and unencumbered software",)),
)


def is_inside(path: Path, root: Path) -> bool:
    """path を解決(symlink・`..` を展開)した先が root の中か。外を指すものは読まない。"""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def guess_spdx(text: str) -> str | None:
    head = text[:4000].lower()
    for spdx, words in LICENSE_RULES:
        if all(word in head for word in words):
            return spdx
    return None


def find_key_line(text: str, section: str | None, key: str) -> int | None:
    """TOML で `[section]` の中の `key =` の行番号(1 始まり)。見つからなければ None。"""
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        header = re.match(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*(#.*)?$", line)
        if header:
            current = header.group(1).replace('"', "")
            continue
        if current == section and re.match(rf"^\s*{re.escape(key)}\s*=", line):
            return number
    return None


def find_regex_line(text: str, pattern: str) -> int | None:
    for number, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line):
            return number
    return None


def language_of(text: str) -> str | None:
    letters = re.findall(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", text)
    if not letters:
        return None
    japanese = sum(1 for c in letters if ord(c) > 0x3000)
    return "ja" if japanese / len(letters) >= 0.2 else "en"


class Collector:
    def __init__(self, repo: Path):
        self.repo = repo
        self.facts: list[dict] = []
        self.commands: list[dict] = []
        self.warnings: list[dict] = []

    def fact(self, key, value, source):
        self.facts.append({"key": key, "value": value, "source": source})

    def command(self, kind, name, invocation, source, description=""):
        self.commands.append(
            {"kind": kind, "name": name, "invocation": invocation, "source": source, "description": description}
        )

    def warn(self, file, message):
        self.warnings.append({"file": file, "message": message})

    def read(self, name: str) -> str | None:
        path = self.repo / name
        if not path.is_file():
            return None
        if not is_inside(path, self.repo):
            self.warn(name, "リポジトリの外を指すため読まない")
            return None
        try:
            if path.stat().st_size > MAX_READ:
                self.warn(name, f"大きすぎる(> {MAX_READ} バイト)ため読まない")
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.warn(name, f"読めない: {error}")
            return None

    def toml(self, name: str):
        text = self.read(name)
        if text is None:
            return None, None
        try:
            return text, tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            self.warn(name, f"TOML として解釈できない: {error}")
            return text, None

    # --- 各 manifest -------------------------------------------------
    def pyproject(self):
        text, data = self.toml("pyproject.toml")
        if data is None:
            return
        project = data.get("project", {})
        if not isinstance(project, dict):
            self.warn("pyproject.toml", "[project] が表ではない")
            return
        for key in ("name", "version", "description", "requires-python"):
            if isinstance(project.get(key), str):
                line = find_key_line(text, "project", key)
                self.fact(key, project[key], f"pyproject.toml:{line}" if line else "pyproject.toml")
        license_value = project.get("license")
        if isinstance(license_value, dict):
            license_value = license_value.get("text") or license_value.get("file")
        if isinstance(license_value, str) and license_value:
            self.fact("license", license_value, f"pyproject.toml:{find_key_line(text, 'project', 'license') or 1}")
        if isinstance(project.get("dependencies"), list):
            line = find_key_line(text, "project", "dependencies") or 1
            self.fact("dependencies", [d for d in project["dependencies"] if isinstance(d, str)], f"pyproject.toml:{line}")
        scripts = project.get("scripts", {})
        if not isinstance(scripts, dict):
            self.warn("pyproject.toml", "[project.scripts] が表ではない")
            scripts = {}
        for script in scripts:
            line = find_key_line(text, "project.scripts", script) or 1
            self.command("console_script", script, script, f"pyproject.toml:{line}")

    def package_json(self):
        text = self.read("package.json")
        if text is None:
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            self.warn("package.json", f"JSON として解釈できない: {error}")
            return
        if not isinstance(data, dict):
            self.warn("package.json", "トップレベルがオブジェクトではない")
            return

        def line_of(key):
            return find_regex_line(text, rf'"{re.escape(key)}"\s*:') or 1

        def table(key):
            value = data.get(key)
            if value is None:
                return {}
            if not isinstance(value, dict):
                self.warn("package.json", f"{key} がオブジェクトではない")
                return {}
            return value

        for key in ("name", "version", "description", "license"):
            if isinstance(data.get(key), str):
                self.fact(key, data[key], f"package.json:{line_of(key)}")
        for key, value in table("engines").items():
            self.fact(f"engines.{key}", value, f"package.json:{line_of(key)}")
        deps = [*table("dependencies"), *table("devDependencies"), *table("peerDependencies")]
        if deps:
            self.fact("dependencies", deps, f"package.json:{line_of('dependencies')}")
        for name in table("scripts"):
            invocation = {"test": "npm test", "start": "npm start"}.get(name, f"npm run {name}")
            self.command("npm", name, invocation, f"package.json:{line_of(name)}")
        bins, bin_line = data.get("bin"), line_of("bin")
        if isinstance(bins, str) and isinstance(data.get("name"), str):
            bins = {data["name"].split("/")[-1]: bins}
        elif not isinstance(bins, dict):
            bins = {}
        for name in bins:
            line = bin_line if isinstance(data.get("bin"), str) else line_of(name)
            self.command("bin", name, name, f"package.json:{line}")

    def cargo(self):
        text, data = self.toml("Cargo.toml")
        if data is None:
            return
        package = data.get("package")
        for key, value in (package.items() if isinstance(package, dict) else []):
            if key in ("name", "version", "description", "edition", "license", "rust-version") and isinstance(value, str):
                line = find_key_line(text, "package", key)
                self.fact(key, value, f"Cargo.toml:{line}" if line else "Cargo.toml")

    def go_mod(self):
        text = self.read("go.mod")
        if text is None:
            return
        for key, pattern in (("module", r"^module\s+(\S+)"), ("go", r"^go\s+(\S+)")):
            for number, line in enumerate(text.splitlines(), 1):
                match = re.match(pattern, line)
                if match:
                    self.fact(key, match.group(1), f"go.mod:{number}")
                    break

    def makefile(self):
        for name in ("Makefile", "makefile", "GNUmakefile"):
            text = self.read(name)
            if text is None:
                continue
            seen = set()
            for number, line in enumerate(text.splitlines(), 1):
                if line.startswith(("\t", " ", "#", ".")):
                    continue
                match = re.match(r"^([^\s:=#$%][^:=#$%]*?)\s*:(?!=)(.*)$", line)
                if not match:
                    continue
                note = re.search(r"##\s*(.*)$", match.group(2))
                for target in match.group(1).split():
                    if target not in seen:
                        seen.add(target)
                        self.command("make", target, f"make {target}", f"{name}:{number}", note.group(1).strip() if note else "")
            return

    def mise(self):
        for name in ("mise.toml", ".mise.toml"):
            text, data = self.toml(name)
            if data is None:
                continue
            tools, tasks = data.get("tools", {}), data.get("tasks", {})
            if not isinstance(tools, dict) or not isinstance(tasks, dict):
                self.warn(name, "[tools] か [tasks] が表ではない")
                tools, tasks = (tools if isinstance(tools, dict) else {}), (tasks if isinstance(tasks, dict) else {})
            for tool, version in tools.items():
                line = find_key_line(text, "tools", tool) or 1
                self.fact(f"tools.{tool}", version, f"{name}:{line}")
            for task, body in tasks.items():
                line = find_regex_line(text, rf'^\s*\[tasks\.("?){re.escape(task)}\1\]') or 1
                description = body.get("description", "") if isinstance(body, dict) else ""
                self.command("mise", task, f"mise run {task}", f"{name}:{line}", description if isinstance(description, str) else "")
            return

    def justfile(self):
        for name in ("justfile", "Justfile", ".justfile"):
            text = self.read(name)
            if text is None:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                match = re.match(r"^@?([A-Za-z_][\w-]*)(?:\s+[^:=]*)?:(?!=)", line)
                if match and not line.startswith((" ", "\t")):
                    self.command("just", match.group(1), f"just {match.group(1)}", f"{name}:{number}")
            return

    def ci(self) -> list[dict]:
        result = []
        workflows = self.repo / ".github" / "workflows"
        if workflows.is_dir() and not is_inside(workflows, self.repo):
            self.warn(".github/workflows", "リポジトリの外を指すため読まない")
            return result
        names = sorted(p.name for p in islice(workflows.iterdir(), MAX_ENTRIES) if p.suffix in (".yml", ".yaml")) if workflows.is_dir() else []
        for name in names[:MAX_WORKFLOWS]:
            relative = f".github/workflows/{name}"
            text = self.read(relative)
            if text is None:
                continue
            lines = text.splitlines()
            runs: list[str] = []
            index = 0
            while index < len(lines):
                match = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[index])
                index += 1
                if not match:
                    continue
                indent, rest = len(match.group(1)), match.group(2).strip()
                if rest in ("|", ">", "|-", ">-", "|+", ">+"):
                    while index < len(lines):
                        nxt = lines[index]
                        if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                            break
                        if nxt.strip():
                            runs.append(nxt.strip())
                        index += 1
                elif rest:
                    runs.append(rest)
            result.append({"file": relative, "run": runs})
        if len(names) > MAX_WORKFLOWS:
            self.warn(".github/workflows", f"{MAX_WORKFLOWS} 件を超える workflow は読まない")
        return result

    def license(self) -> dict:
        for name in LICENSE_NAMES:
            text = self.read(name)
            if text is not None:
                return {"present": True, "file": name, "spdx": guess_spdx(text)}
        return {"present": False, "file": None, "spdx": None}

    def readme(self) -> dict:
        for name in README_NAMES:
            text = self.read(name)
            if text is not None:
                return {"present": True, "path": name, "language": language_of(text)}
        return {"present": False, "path": None, "language": None}

    def tree(self) -> list[str]:
        entries = []
        with os.scandir(self.repo) as scan:
            sample = list(islice(scan, MAX_ENTRIES))
        for entry in sorted(sample, key=lambda e: e.name.lower()):
            if entry.name.startswith(".") or entry.name in SKIP_TREE:
                continue
            entries.append(entry.name + ("/" if entry.is_dir() else ""))
        return entries[:60]


def collect(repo: Path) -> dict:
    repo = Path(repo)
    c = Collector(repo)
    for step in (c.pyproject, c.package_json, c.cargo, c.go_mod, c.makefile, c.mise, c.justfile):
        try:
            step()
        except Exception as error:  # noqa: BLE001 - 想定外の形でも落とさず、warnings に残す
            c.warn(step.__name__, f"想定外の形で読めなかった: {type(error).__name__}: {error}")
    return {
        "repo": str(repo),
        "facts": c.facts,
        "commands": c.commands,
        "license": c.license(),
        "readme": c.readme(),
        "ci": c.ci(),
        "tree": c.tree(),
        "warnings": c.warnings,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", type=Path, help="リポジトリのパス")
    args = parser.parse_args(argv)
    if not args.repo.is_dir():
        print(f"ディレクトリではない: {args.repo}", file=sys.stderr)
        return 2
    print(json.dumps(collect(args.repo), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
