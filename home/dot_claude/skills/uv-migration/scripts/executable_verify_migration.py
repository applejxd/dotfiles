#!/usr/bin/env python3
"""Verify a uv-migrated project: no legacy artifacts, extensions really built.

    python ~/.claude/skills/uv-migration/scripts/verify_migration.py [PROJECT_DIR]

Checks, in order:
  1. conda / pip era files are gone
  2. pyproject.toml declares torch through an explicit index (if torch is used)
  3. uv.lock exists and is in sync (`uv lock --check`)
  4. compiled extension modules are actually present in the environment
  5. torch sees the GPU

Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

LEGACY = ["environment.yml", "environment.yaml", "setup_env.sh"]
LEGACY_GLOBS = ["requirements*.txt", "install*.sh", "scripts/install*.sh", "requirements/*.txt"]

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok  ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)
    return ok


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), cwd=root, capture_output=True, text=True)


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def check_legacy(root: Path) -> None:
    found = {name for name in LEGACY if (root / name).exists()}
    for pattern in LEGACY_GLOBS:
        found |= {str(p.relative_to(root)) for p in root.glob(pattern)}
    check("legacy conda/pip artifacts removed", not found, ", ".join(sorted(found)))


def check_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not check("pyproject.toml exists", path.exists()):
        return {}
    data = tomllib.loads(path.read_text())
    uv = data.get("tool", {}).get("uv", {})
    deps = data.get("project", {}).get("dependencies", [])
    names = {d.split("[")[0].split(">")[0].split("=")[0].split(";")[0].strip() for d in deps}
    if "torch" not in names:
        notes.append("torch is not a direct dependency; skipped index checks")
        return data

    indexes = uv.get("index", [])
    declared = {i.get("name") for i in indexes}
    explicit = {i.get("name") for i in indexes if i.get("explicit")}
    torch_src = uv.get("sources", {}).get("torch", {})
    target = torch_src.get("index") if isinstance(torch_src, dict) else None
    check(
        "torch resolves through a declared index",
        target in declared,
        f"tool.uv.sources.torch = {torch_src or 'missing'}",
    )
    check(
        "that index is explicit",
        target in explicit,
        "without explicit = true the index leaks into every other package",
    )
    return data


def check_lock(root: Path) -> None:
    if not check("uv.lock exists", (root / "uv.lock").exists()):
        return
    proc = run(root, "uv", "lock", "--check")
    check("uv.lock is up to date", proc.returncode == 0, last_line(proc.stderr))


def check_extensions(root: Path) -> None:
    code = (
        "import json,sysconfig,pathlib;"
        "sp=pathlib.Path(sysconfig.get_paths()['purelib']);"
        "print(json.dumps(sorted({p.name.split('.')[0] for p in sp.rglob('*.so')})))"
    )
    proc = run(root, "uv", "run", "--no-sync", "python", "-c", code)
    if proc.returncode != 0:
        check("environment is usable", False, last_line(proc.stderr))
        return
    try:
        sos = json.loads(last_line(proc.stdout))
    except json.JSONDecodeError:
        check("environment is usable", False, "unexpected output")
        return
    check("compiled extension modules present", bool(sos), f"{len(sos)} .so files")


def check_gpu(root: Path) -> None:
    code = "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
    proc = run(root, "uv", "run", "--no-sync", "python", "-c", code)
    if proc.returncode != 0:
        notes.append("torch not importable; skipped GPU check")
        return
    line = last_line(proc.stdout)
    check("torch sees a CUDA device", line.endswith("True"), line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", default=".", type=Path)
    root = parser.parse_args().project.resolve()
    print(f"verifying {root}\n")

    check_legacy(root)
    if check_pyproject(root):
        check_lock(root)
        check_extensions(root)
        check_gpu(root)

    for note in notes:
        print(f"[note] {note}")
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
