#!/usr/bin/env python
"""Check *how* a CUDA extension was built, not just that it imports.

    python check_cuda_build.py pointnet2_ops._ext [more.modules ...]
        [--built-torch 2.10.0] [--built-cuda 12.8] [--target-sm "8.6;9.0"]

Detects the ways a CUDA-version migration goes wrong while still looking
successful:

* the extension silently degraded to a build without CUDA kernels
* the import fell back to JIT compilation at runtime
* the extension fails to link against the runtime torch
* the fatbin has no code that can run on this machine's GPU

Exit status: 0 = every check ran and passed, 1 = a check failed,
2 = nothing failed but a required check could not run (nvcc, cuobjdump or
a GPU is missing). 2 is "unverified", never a pass.

What this proves: the environment *now* (nvcc, torch, import). It cannot
see which toolkit / torch built the .so. Pass --built-torch / --built-cuda /
--target-sm, taken from the build log, to compare the recorded build
against the current environment and the fatbin.
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

OK, BAD, WARN, SKIP = "ok  ", "FAIL", "warn", "n/a "


class Report:
    def __init__(self) -> None:
        self.failed = False
        self.unverified = False

    def __call__(self, status: str, message: str) -> None:
        if status == BAD:
            self.failed = True
        elif status == SKIP:
            self.unverified = True
        print(f"[{status}] {message}")


def check_env(
    say: Report, built_torch: str | None, built_cuda: str | None
) -> tuple[int | None, int | None]:
    try:
        import torch
    except ImportError as exc:
        say(BAD, f"torch is not importable: {exc}")
        return None, None

    torch_cuda = torch.version.cuda
    if torch_cuda is None:
        say(BAD, "torch is a CPU build (torch.version.cuda is None)")
        return None, None
    torch_major = int(torch_cuda.split(".")[0])
    say(OK, f"torch {torch.__version__} (CUDA {torch_cuda})")
    if built_torch:
        same = torch.__version__.split("+")[0] == built_torch.split("+")[0]
        say(
            OK if same else BAD,
            f"runtime torch {torch.__version__} vs build-log torch {built_torch}",
        )
    if built_cuda:
        # toolkit vs torch wheel: major must match, minor may differ
        # (see references/version-matrix.md)
        built_major = built_cuda.split(".")[0]
        say(
            OK if built_major == str(torch_major) else BAD,
            f"build-log toolkit {built_cuda} vs torch CUDA {torch_cuda} (major must match)",
        )

    sm = None
    if not torch.cuda.is_available():
        say(SKIP, "no usable GPU; cannot check the fatbin against this machine's SM")
    else:
        cap = torch.cuda.get_device_capability(0)
        sm = cap[0] * 10 + cap[1]
        say(OK, f"device {torch.cuda.get_device_name(0)} sm_{sm}")

    nvcc_major = None
    cuda_home = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    nvcc = None
    if cuda_home:
        candidate = pathlib.Path(cuda_home) / "bin" / "nvcc"
        nvcc = str(candidate) if candidate.exists() else None
    nvcc = nvcc or shutil.which("nvcc")
    if nvcc is None:
        say(SKIP, "nvcc not found; cannot compare toolkit against torch")
    else:
        out = subprocess.run([nvcc, "--version"], capture_output=True, text=True).stdout
        m = re.search(r"release (\d+)\.(\d+)", out)
        if not m:
            say(SKIP, f"could not parse `{nvcc} --version`")
        else:
            nvcc_major = int(m.group(1))
            where = "CUDA_HOME" if cuda_home and nvcc.startswith(cuda_home) else "PATH"
            label = f"nvcc {m.group(1)}.{m.group(2)} ({where}: {nvcc})"
            if nvcc_major == torch_major:
                say(OK, f"{label} matches torch CUDA major (current env only)")
            else:
                say(BAD, f"{label} but torch was built against CUDA {torch_cuda}")
            if built_cuda:
                # same kind of value (toolkit vs toolkit): exact match on the given parts
                cur = f"{m.group(1)}.{m.group(2)}"
                same = cur == built_cuda or cur.startswith(built_cuda + ".")
                say(
                    OK if same else BAD,
                    f"current nvcc {cur} vs build-log toolkit {built_cuda}",
                )

    return torch_major, sm


def check_module(
    name: str, sm: int | None, targets: list[tuple[int, bool]], say: Report
) -> None:
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

    check_fatbin(path, sm, targets, say)


def check_fatbin(
    path: pathlib.Path, sm: int | None, targets: list[tuple[int, bool]], say: Report
) -> None:
    cuobjdump = shutil.which("cuobjdump")
    if cuobjdump is None:
        say(SKIP, f"{path.name}: cuobjdump not on PATH; cannot inspect the fatbin")
        return

    def archs(flag: str) -> set[int]:
        out = subprocess.run(
            [cuobjdump, flag, str(path)], capture_output=True, text=True
        ).stdout
        return {int(a) for a in re.findall(r"sm_(\d+)", out)}

    sass, ptx = archs("--list-elf"), archs("--list-ptx")
    say(OK, f"{path.name}: SASS {sorted(sass) or '-'} PTX {sorted(ptx) or '-'}")
    if sm is None:
        say(SKIP, f"{path.name}: no GPU, so runnability on this machine is unchecked")
    elif sm in sass:
        say(OK, f"{path.name}: has SASS for sm_{sm}")
    elif any(a <= sm for a in ptx):
        say(WARN, f"{path.name}: no SASS for sm_{sm}; relies on PTX JIT (slow start)")
    else:
        say(
            BAD,
            f"{path.name}: nothing runnable on sm_{sm}; kernels will raise "
            "'no kernel image is available for execution on the device'",
        )
    # Separate from runnability above: did the build emit what was recorded?
    for t, want_ptx in targets:
        if t not in sass:
            say(BAD, f"{path.name}: recorded target sm_{t} has no SASS in the fatbin")
        else:
            say(OK, f"{path.name}: SASS for recorded target sm_{t}")
        if want_ptx:
            if t in ptx:
                say(OK, f"{path.name}: PTX for recorded target sm_{t}+PTX")
            else:
                say(BAD, f"{path.name}: recorded sm_{t}+PTX has no PTX in the fatbin")


def parse_targets(text: str) -> list[tuple[int, bool]]:
    """'8.6;9.0+PTX' -> [(86, False), (90, True)]. Raises ValueError on anything else.

    Grammar is TORCH_CUDA_ARCH_LIST's: '<major>.<minor>' with optional '+PTX',
    separated by ';' or whitespace. Names such as 'Ampere' are rejected.
    """
    items = [i for i in re.split(r"[;\s]+", text.strip()) if i]
    if not items:
        raise ValueError("no targets given")
    result = []
    for item in items:
        m = re.fullmatch(r"(\d+)\.(\d)(\+PTX)?", item)
        if not m:
            raise ValueError(
                f"invalid target {item!r}; expected '<major>.<minor>' or '<major>.<minor>+PTX'"
            )
        result.append((int(m[1]) * 10 + int(m[2]), m[3] is not None))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="+", help="e.g. pointnet2_ops._ext")
    parser.add_argument("--built-torch", help="torch version in the build log")
    parser.add_argument("--built-cuda", help="toolkit version in the build log, e.g. 12.8")
    parser.add_argument("--target-sm", help='TORCH_CUDA_ARCH_LIST of the build, e.g. "8.6;9.0+PTX"')
    args = parser.parse_args()

    targets: list[tuple[int, bool]] = []
    if args.target_sm is not None:
        try:
            targets = parse_targets(args.target_sm)
        except ValueError as e:
            parser.error(f"--target-sm: {e}")

    say = Report()
    _, sm = check_env(say, args.built_torch, args.built_cuda)
    for name in args.modules:
        check_module(name, sm, targets, say)
    if not (args.built_torch and args.built_cuda and targets):
        say(SKIP, "build record not given; build-time toolkit/torch/SM are unproven")
    if say.failed:
        return 1
    return 2 if say.unverified else 0


if __name__ == "__main__":
    sys.exit(main())
