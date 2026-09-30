#!/usr/bin/env python3
"""Verify a uv-migrated project. Checks depend on the project kind.

    python ~/.claude/skills/uv-migration/scripts/verify_migration.py [PROJECT_DIR]
        [--profile general|torch-cpu|torch-cuda]
        [--expect-module PKG.MOD ...] [--extension-dir DIR ...]
        [--retire GLOB ...] [--keep PATH:REASON ...]

Always: uv.lock exists and is in sync (`uv lock --check`); legacy files
that were decided to be retired are gone.
--profile general    (default) plain Python project; torch is not checked
--profile torch-cpu  torch must import (CPU build is fine)
--profile torch-cuda torch must import, be a CUDA build and see a GPU
--expect-module      each named module must import, be loaded by
                     ExtensionFileLoader with a valid extension suffix, and
                     live under the environment's purelib/platlib (not the
                     JIT cache, not an outside dir reached via PYTHONPATH)
--extension-dir DIR  extra allowed location (e.g. editable build dir). Passes
                     with a note: "not JIT" is not proven there
--retire GLOB        files to require absent. Default when omitted:
                     environment.y*ml, setup_env.sh, requirements*.txt,
                     install*.sh, scripts/install*.sh, requirements/*.txt
--keep PATH:REASON   file deliberately kept for compatibility; excluded
                     from the retire check. A reason is mandatory.

pyproject.toml torch index checks run whenever torch is a direct dependency.
Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

DEFAULT_RETIRE = [
    "environment.yml",
    "environment.yaml",
    "setup_env.sh",
    "requirements*.txt",
    "install*.sh",
    "scripts/install*.sh",
    "requirements/*.txt",
]

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


def check_legacy(root: Path, retire: list[str], keep: dict[str, str]) -> None:
    found: set[str] = set()
    for pattern in retire:
        found |= {str(p.relative_to(root)) for p in root.glob(pattern)}
    kept = found & set(keep)
    for path in sorted(kept):
        notes.append(f"kept {path}: {keep[path]}")
    found -= kept
    check("files decided to be retired are gone", not found, ", ".join(sorted(found)))


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


def check_modules(root: Path, modules: list[str], extension_dirs: list[str]) -> None:
    code = (
        "import sys,json,importlib,importlib.util as u,importlib.machinery as m,sysconfig,os\n"
        "out={'_env':{'dirs':[sysconfig.get_path(k) for k in ('purelib','platlib')],\n"
        "             'suffixes':list(m.EXTENSION_SUFFIXES)}}\n"
        "for n in sys.argv[1:]:\n"
        "    try:\n"
        "        s=u.find_spec(n)\n"
        "    except Exception as e:\n"
        "        out[n]=['error','find_spec: '+str(e)];continue\n"
        "    if s is None or not s.origin:\n"
        "        out[n]=['missing','']\n"
        "        continue\n"
        "    try:\n"
        "        mod=importlib.import_module(n)\n"
        "    except Exception as e:\n"
        "        out[n]=['error',s.origin+': '+str(e)];continue\n"
        "    s=getattr(mod,'__spec__',None) or s\n"
        "    out[n]=['ok',os.path.realpath(s.origin),\n"
        "            isinstance(s.loader,m.ExtensionFileLoader)]\n"
        "print(json.dumps(out))\n"
    )
    proc = run(root, "uv", "run", "--no-sync", "python", "-c", code, *modules)
    if proc.returncode != 0:
        check("environment is usable", False, last_line(proc.stderr))
        return
    try:
        result = json.loads(last_line(proc.stdout))
    except json.JSONDecodeError:
        check("environment is usable", False, "unexpected output")
        return
    env = result.get("_env", {})
    suffixes = tuple(env.get("suffixes", [".so"]))
    env_dirs = [Path(d).resolve() for d in env.get("dirs", []) if d]
    extra_dirs = [Path(d).resolve() for d in extension_dirs]

    def under(path: Path, dirs: list[Path]) -> bool:
        return any(path.is_relative_to(d) for d in dirs)

    for name in modules:
        state, detail, *rest = result.get(name, ["error", "no result"])
        if state != "ok":
            check(f"extension {name} imports", False, f"{state}: {detail}")
            continue
        path = Path(detail)
        if not rest[0]:
            check(f"extension {name} is loaded by ExtensionFileLoader", False, detail)
        elif not path.name.endswith(suffixes):
            check(f"extension {name} has an extension suffix {suffixes}", False, detail)
        elif "torch_extensions" in path.parts:
            check(f"extension {name} is prebuilt, not JIT", False, detail)
        elif under(path, env_dirs):
            check(f"extension {name} is a compiled module in the environment", True, detail)
        elif under(path, extra_dirs):
            check(f"extension {name} is a compiled module in --extension-dir", True, detail)
            notes.append(
                f"{name}: {path} is outside the environment's site-packages; "
                "placement was allowed explicitly, and that it was not JIT-built is not proven"
            )
        else:
            check(
                f"extension {name} lives in the environment (or an --extension-dir)",
                False,
                f"{detail} (site-packages: {', '.join(map(str, env_dirs))})",
            )


def check_torch(root: Path, need_cuda: bool) -> None:
    code = "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
    proc = run(root, "uv", "run", "--no-sync", "python", "-c", code)
    if not check("torch imports", proc.returncode == 0, last_line(proc.stderr)):
        return
    line = last_line(proc.stdout)
    if need_cuda:
        check("torch sees a CUDA device", line.endswith("True"), line)
    else:
        notes.append(f"torch (CPU profile): {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--profile", choices=["general", "torch-cpu", "torch-cuda"], default="general"
    )
    parser.add_argument("--expect-module", action="append", default=[])
    parser.add_argument("--extension-dir", action="append", default=[], metavar="DIR")
    parser.add_argument("--retire", action="append", default=[])
    parser.add_argument("--keep", action="append", default=[], metavar="PATH:REASON")
    args = parser.parse_args()
    root = args.project.resolve()

    keep: dict[str, str] = {}
    for item in args.keep:
        path, _, reason = item.partition(":")
        if not path or not reason.strip():
            parser.error(f"--keep needs PATH:REASON, got {item!r}")
        keep[path] = reason.strip()

    print(f"verifying {root} (profile: {args.profile})\n")

    check_legacy(root, args.retire or DEFAULT_RETIRE, keep)
    if check_pyproject(root):
        check_lock(root)
        if args.profile != "general":
            check_torch(root, need_cuda=args.profile == "torch-cuda")
        if args.expect_module:
            check_modules(root, args.expect_module, args.extension_dir)
        else:
            notes.append("no --expect-module given; extension build not checked")

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
