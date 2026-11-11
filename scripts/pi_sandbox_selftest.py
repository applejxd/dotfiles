#!/usr/bin/env python3
"""pi-sandbox-runner の実機確認 (GPU・秘密の隠蔽・docker の遮断・git の保護)。

@yuru7/pi-sandbox 0.5.0 の bwrapProfileArgs (workspace-write) と同じ引数で runner を呼び、
内側から確かめる。確認できない項目 (GPU が無い機など) は SKIP。FAIL があれば終了コード 1。
拡張を更新したら、これを回したうえで、実拡張でも確かめる (see docs/spec/sandbox/pi-sandbox-runner.md#版の固定と更新)。

usage: python3 scripts/pi_sandbox_selftest.py [--runner PATH] [--config PATH]
秘密の中身は読まない。存在と、内側から空に見えるかだけを調べる。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_RUNNER = ROOT / "home" / "dot_local" / "bin" / "executable_pi-sandbox-runner"
REPO_CONFIG = ROOT / "home" / "dot_config" / "pi-sandbox" / "runner.toml"

# PTX を JIT して 1M 要素に 1 を足す。結果が合えば GPU で計算できている (torch は要らない)
CUDA_KERNEL = r"""
import ctypes as C, sys
PTX = b'''
.version 7.0
.target sm_52
.address_size 64
.visible .entry addone(.param .u64 p, .param .u32 n)
{
  .reg .pred %p0; .reg .b32 %r<5>; .reg .b64 %rd<5>; .reg .f32 %f<3>;
  ld.param.u64 %rd1, [p]; ld.param.u32 %r1, [n];
  mov.u32 %r2, %tid.x; mov.u32 %r3, %ctaid.x; mov.u32 %r4, %ntid.x;
  mad.lo.s32 %r2, %r3, %r4, %r2;
  setp.ge.s32 %p0, %r2, %r1;
  @%p0 bra DONE;
  mul.wide.s32 %rd2, %r2, 4; add.s64 %rd3, %rd1, %rd2;
  ld.global.f32 %f1, [%rd3]; add.f32 %f2, %f1, 0f3F800000; st.global.f32 [%rd3], %f2;
DONE: ret;
}
\0'''
cu = C.CDLL("libcuda.so.1")
def chk(rc):
    if rc: print(f"cuda=FAIL rc={rc}"); sys.exit(0)
chk(cu.cuInit(0)); dev = C.c_int(); chk(cu.cuDeviceGet(C.byref(dev), 0))
ctx = C.c_void_p(); chk(cu.cuCtxCreate_v2(C.byref(ctx), 0, dev))
mod = C.c_void_p(); chk(cu.cuModuleLoadData(C.byref(mod), PTX))
fn = C.c_void_p(); chk(cu.cuModuleGetFunction(C.byref(fn), mod, b"addone"))
N = 1 << 20; host = (C.c_float * N)(*([1.0] * N)); d = C.c_uint64()
chk(cu.cuMemAlloc_v2(C.byref(d), C.c_size_t(N * 4))); chk(cu.cuMemcpyHtoD_v2(d, host, C.c_size_t(N * 4)))
n = C.c_int(N); args = (C.c_void_p * 2)(C.cast(C.byref(d), C.c_void_p), C.cast(C.byref(n), C.c_void_p))
chk(cu.cuLaunchKernel(fn, (N + 255) // 256, 1, 1, 256, 1, 1, 0, None, args, None)); chk(cu.cuCtxSynchronize())
out = (C.c_float * N)(); chk(cu.cuMemcpyDtoH_v2(out, d, C.c_size_t(N * 4)))
print("cuda=ok" if all(abs(out[i] - 2.0) < 1e-6 for i in (0, 1, N // 2, N - 1)) else "cuda=WRONG")
"""


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def line(self, status: str, name: str, detail: str = "") -> None:
        if status == "FAIL":
            self.failed += 1
        print(f"{status:<5} {name}" + (f"  ({detail})" if detail else ""))


def git(*args: str, cwd: Path) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


def sandbox(runner: Path, config: Path, workspace: Path, git_roots: list[Path], script: str):
    """拡張 (workspace-write) と同じ引数で runner を呼び、sh -c <script> を内側で実行する。"""
    profile = [
        *("--ro-bind", "/", "/", "--dev", "/dev", "--unshare-pid", "--proc", "/proc"),
        *("--die-with-parent", "--bind", "/tmp", "/tmp", "--bind", str(workspace), str(workspace)),
    ]
    for root in git_roots:
        profile += ["--bind", str(root), str(root)]
    env = {**os.environ, "PI_SANDBOX_RUNNER_CONFIG": str(config)}
    return subprocess.run(
        [sys.executable, str(runner), *profile, "--", "sh", "-c", script],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    home = Path.home()
    deployed = home / ".local" / "bin" / "pi-sandbox-runner"
    deployed_conf = home / ".config" / "pi-sandbox" / "runner.toml"
    parser.add_argument(
        "--runner", type=Path, default=deployed if deployed.exists() else REPO_RUNNER
    )
    parser.add_argument(
        "--config", type=Path, default=deployed_conf if deployed_conf.exists() else REPO_CONFIG
    )
    args = parser.parse_args()
    if shutil.which("bwrap") is None or shutil.which("git") is None:
        print("SKIP  bwrap と git が要る")
        return 0
    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    print(f"runner={args.runner}\nconfig={args.config}")
    report = Report()

    with tempfile.TemporaryDirectory(prefix="pi-sandbox-selftest-") as tmp:
        main_repo, wt = Path(tmp) / "main", Path(tmp) / "wt"
        main_repo.mkdir()
        git("init", "-q", cwd=main_repo)
        git("commit", "--allow-empty", "-qm", "init", cwd=main_repo)
        git("worktree", "add", "-q", str(wt), "-b", "selftest", cwd=main_repo)
        git_roots = [
            main_repo / ".git" / "worktrees" / "wt",
            main_repo / ".git",
        ]  # 拡張が足す gitdir と commondir

        def run(script: str):
            return sandbox(args.runner, args.config, wt, git_roots, script)

        probe = (
            home / f".pi-sandbox-selftest-{os.getpid()}-{os.urandom(4).hex()}"
        )  # 既存のファイルと衝突しない名前
        res = run(
            f'touch "{probe}" 2>/dev/null && echo leak || echo blocked; touch ./w && echo ok || echo FAIL'
        )
        probe.unlink(missing_ok=True)
        out = res.stdout.split()
        report.line(
            "PASS" if out == ["blocked", "ok"] else "FAIL",
            "書き込み: HOME は不可・作業ツリーは可",
            res.stderr.strip(),
        )

        hidden = [
            p for p in cfg.get("hide", {}).get("dirs", []) + cfg.get("hide", {}).get("files", [])
        ]
        present = [Path(str(p).replace("~", str(home), 1)) for p in hidden]
        present = [p for p in present if p.exists() and (not p.is_dir() or any(p.iterdir()))]
        if not present:
            report.line("SKIP", "秘密の隠蔽", "隠す対象が、この機に (中身つきで) 無い")
        else:
            bad = []
            for path in present:
                test = (
                    f'[ -z "$(ls -A "{path}" 2>/dev/null)" ]'
                    if path.is_dir()
                    else f'[ ! -s "{path}" ]'
                )
                if run(f"{test} && echo hidden || echo VISIBLE").stdout.strip() != "hidden":
                    bad.append(str(path))
            report.line(
                "FAIL" if bad else "PASS", f"秘密の隠蔽 ({len(present)} 件)", ", ".join(bad)
            )

        docker_wanted = cfg.get("docker", {}).get("block", True) and shutil.which("docker")
        host_docker = (
            docker_wanted
            and subprocess.run(
                ["docker", "ps"], capture_output=True, timeout=30, check=False
            ).returncode
            == 0
        )
        if host_docker:  # ホストで届かない環境では、遮断を確認したことにならない
            res = run("timeout 10 docker ps >/dev/null 2>&1 && echo reachable || echo blocked")
            report.line(
                "PASS" if res.stdout.strip() == "blocked" else "FAIL", "docker: 内側から届かない"
            )
        else:
            report.line(
                "SKIP", "docker の遮断", "docker が無い・block = false・ホストからも届かない"
            )

        res = run(
            'echo x > "$(git rev-parse --git-common-dir)/hooks/pre-commit" 2>/dev/null && echo hooks=writable || echo hooks=ro; '
            "git -c user.name=t -c user.email=t@example.invalid commit --allow-empty -qm t && echo commit=ok || echo commit=failed"
        )
        report.line(
            "PASS" if res.stdout.split() == ["hooks=ro", "commit=ok"] else "FAIL",
            "git: worktree で commit できて、hooks は読み取り専用",
            res.stdout.strip().replace("\n", " "),
        )

    gpu_wanted = bool(cfg.get("gpu", {}).get("devices"))
    gpu_present = any(Path(p).exists() for p in ("/dev/dxg", "/dev/nvidiactl"))
    if not gpu_wanted or not gpu_present:
        report.line("SKIP", "GPU (CUDA カーネル)", "設定で無効か、この機に GPU が無い")
    else:
        with tempfile.TemporaryDirectory(prefix="pi-sandbox-selftest-") as tmp:
            (Path(tmp) / "kernel.py").write_text(CUDA_KERNEL, encoding="utf-8")
            res = sandbox(args.runner, args.config, Path(tmp), [], "python3 kernel.py")
        report.line(
            "PASS" if res.stdout.strip() == "cuda=ok" else "FAIL",
            "GPU: 内側で CUDA カーネルが動く",
            (res.stdout + res.stderr).strip()[-120:],
        )

    print("結果:", "FAIL あり" if report.failed else "すべて PASS (SKIP を除く)")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
