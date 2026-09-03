#!/usr/bin/env python
"""Check *how* a CUDA extension was built, not just that it imports.

    python check_cuda_build.py pointnet2_ops._ext [more.modules ...]

Reports, and fails with a non-zero exit code on, the four ways a
CUDA-version migration goes wrong while still looking successful:

* the extension silently degraded to a build without CUDA kernels
* the import fell back to JIT compilation at runtime
* the extension was linked against a different torch than the runtime one
* the fatbin has no code that can run on this machine's GPU
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys

OK, BAD, WARN = "ok  ", "FAIL", "warn"


class Report:
    def __init__(self) -> None:
        self.failed = False

    def __call__(self, status: str, message: str) -> None:
        if status == BAD:
            self.failed = True
        print(f"[{status}] {message}")


def check_env(say: Report) -> tuple[int | None, int | None]:
    import torch

    torch_cuda = torch.version.cuda
    if torch_cuda is None:
        say(BAD, "torch is a CPU build (torch.version.cuda is None)")
        return None, None
    torch_major = int(torch_cuda.split(".")[0])
    say(OK, f"torch {torch.__version__} (CUDA {torch_cuda})")

    if not torch.cuda.is_available():
        say(BAD, "torch.cuda.is_available() is False")
        return torch_major, None
    cap = torch.cuda.get_device_capability(0)
    say(OK, f"device {torch.cuda.get_device_name(0)} sm_{cap[0]}{cap[1]}")

    nvcc_major = None
    cuda_home = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    nvcc = None
    if cuda_home:
        candidate = pathlib.Path(cuda_home) / "bin" / "nvcc"
        nvcc = str(candidate) if candidate.exists() else None
    nvcc = nvcc or shutil.which("nvcc")
    if nvcc is None:
        say(WARN, "nvcc not found; cannot compare toolkit against torch")
    else:
        out = subprocess.run([nvcc, "--version"], capture_output=True, text=True).stdout
        m = re.search(r"release (\d+)\.(\d+)", out)
        if m:
            nvcc_major = int(m.group(1))
            where = "CUDA_HOME" if cuda_home and nvcc.startswith(cuda_home) else "PATH"
            label = f"nvcc {m.group(1)}.{m.group(2)} ({where}: {nvcc})"
            if nvcc_major == torch_major:
                say(OK, f"{label} matches torch CUDA major")
            else:
                say(BAD, f"{label} but torch was built against CUDA {torch_cuda}")

    return torch_major, cap[0] * 10 + cap[1]


def check_module(name: str, sm: int | None, say: Report) -> None:
    try:
        spec = importlib.util.find_spec(name)
    except ImportError as exc:  # a parent package failed to import
        say(BAD, f"{name}: {exc}")
        return
    if spec is None or not spec.origin:
        say(BAD, f"{name}: not found (degraded build without CUDA kernels?)")
        return

    path = pathlib.Path(spec.origin)
    if path.suffix != ".so":
        say(BAD, f"{name}: {path} is not a compiled extension")
        return
    if "torch_extensions" in str(path):
        say(BAD, f"{name}: JIT-compiled at import time ({path})")
        return
    say(OK, f"{name}: {path}")

    try:
        importlib.import_module(name)
        say(OK, f"{name}: links against the installed torch")
    except ImportError as exc:
        say(BAD, f"{name}: ABI mismatch or missing symbol: {exc}")
        return

    check_fatbin(path, sm, say)


def check_fatbin(path: pathlib.Path, sm: int | None, say: Report) -> None:
    cuobjdump = shutil.which("cuobjdump")
    if cuobjdump is None:
        say(WARN, "cuobjdump not on PATH; cannot inspect the fatbin")
        return

    def archs(flag: str) -> set[int]:
        out = subprocess.run(
            [cuobjdump, flag, str(path)], capture_output=True, text=True
        ).stdout
        return {int(a) for a in re.findall(r"sm_(\d+)", out)}

    sass, ptx = archs("--list-elf"), archs("--list-ptx")
    say(OK, f"{path.name}: SASS {sorted(sass) or '-'} PTX {sorted(ptx) or '-'}")
    if sm is None:
        return
    if sm in sass:
        say(OK, f"{path.name}: has SASS for sm_{sm}")
    elif any(a <= sm for a in ptx):
        say(WARN, f"{path.name}: no SASS for sm_{sm}; relies on PTX JIT (slow start)")
    else:
        say(
            BAD,
            f"{path.name}: nothing runnable on sm_{sm}; kernels will raise "
            "'no kernel image is available for execution on the device'",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="+", help="e.g. pointnet2_ops._ext")
    args = parser.parse_args()

    say = Report()
    _, sm = check_env(say)
    for name in args.modules:
        check_module(name, sm, say)
    return 1 if say.failed else 0


if __name__ == "__main__":
    sys.exit(main())
