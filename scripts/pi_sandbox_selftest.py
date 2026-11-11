#!/usr/bin/env python3
"""pi-sandbox-runner の実機確認 (見える範囲・書き込み・秘密の隠蔽・環境変数・docker・git・GPU・通信の遮断)。

実際の runner を、シェルモード (``-c <コマンド>``。pi の shellPath 経由と同じ呼び方) で動かし、内側から確かめる。
確認できない項目 (GPU が無い機など) は SKIP。FAIL があれば終了コード 1。
pi の本体を通した確認 (bash・bg_run・利用者の bash・子エージェントが囲いを通るか) は、docs の「導入と確認」の手順で行う。

usage: python3 scripts/pi_sandbox_selftest.py [--runner PATH] [--config PATH]
秘密の中身は読まない。存在と、内側から見えないかだけを調べる。
see docs/spec/sandbox/pi-sandbox-runner.md#導入と確認
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


def sandbox(
    runner: Path,
    config: Path,
    workspace: Path,
    script: str,
    *,
    offline: bool = False,
    env_extra=None,
):
    """runner をシェルモードで呼び、``bash -c <script>`` を内側で実行する (pi の shellPath 経由と同じ形)。"""
    env = {**os.environ, "PI_SANDBOX_RUNNER_CONFIG": str(config), **(env_extra or {})}
    flags = ["--offline"] if offline else []
    return subprocess.run(
        [sys.executable, str(runner), *flags, "-c", script],
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
    args.runner, args.config = (
        args.runner.resolve(),
        args.config.resolve(),
    )  # 作業ディレクトリを変えて呼ぶので、絶対パスにする
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

        def run(script: str, **kw):
            return sandbox(args.runner, args.config, wt, script, **kw)

        # 書き込み: ホームの中は空の tmpfs なので、書けても外へ届かない。作業ツリーは書ける
        probe = home / f".pi-sandbox-selftest-{os.getpid()}-{os.urandom(4).hex()}"
        res = run(f'touch "{probe}" 2>/dev/null; touch ./w && echo work=ok || echo work=FAIL')
        reached = probe.exists()
        probe.unlink(missing_ok=True)
        ok = res.stdout.split() == ["work=ok"] and not reached and (wt / "w").exists()
        report.line(
            "PASS" if ok else "FAIL",
            "書き込み: 作業ツリーは可・ホームへの書き込みは外へ届かない",
            res.stderr.strip(),
        )

        # 見える範囲: ホームの履歴・Windows のドライブ・共有の /tmp とソケットが見えない
        shared = Path(tempfile.mkdtemp(prefix="pib-selftest-", dir="/tmp"))
        (shared / "marker").write_text("x", encoding="utf-8")
        try:
            probes = {
                "ホームの履歴": [home / ".bash_history", home / ".zsh_history"],
                "Windows のドライブ": [Path("/mnt/c"), Path("/mnt/d")],
                "共有の /tmp": [shared / "marker"],
                "tmux・X11 のソケット": [*Path("/tmp").glob("tmux-*"), Path("/tmp/.X11-unix")],
            }
            for name, paths in probes.items():
                present = [p for p in paths if p.exists()]
                if not present:
                    report.line("SKIP", f"見えない: {name}", "この機に無い")
                    continue
                shown = [
                    p
                    for p in present
                    if run(f'test -e "{p}" && echo VISIBLE || echo hidden').stdout.strip()
                    != "hidden"
                ]
                report.line(
                    "FAIL" if shown else "PASS", f"見えない: {name}", ", ".join(map(str, shown))
                )
        finally:
            shutil.rmtree(shared, ignore_errors=True)

        # 秘密の隠蔽: 設定の hide のうち、この機にあるもの (見せた場所の中にあっても隠れる)
        hide = cfg.get("hide", {})
        present = [
            Path(str(p).replace("~", str(home), 1))
            for p in [*hide.get("dirs", []), *hide.get("files", [])]
        ]
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

        # git の認証 (store ヘルパー) が、内側から見つからない
        found = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=30,
            check=False,
        )
        if found.returncode != 0:
            report.line("SKIP", "git の認証が見つからない", "ホストにも github.com の認証が無い")
        else:
            res = run(
                'printf "protocol=https\\nhost=github.com\\n\\n" | GIT_TERMINAL_PROMPT=0 git credential fill >/dev/null 2>&1; echo rc=$?'
            )
            report.line(
                "PASS" if res.stdout.strip() not in ("rc=0", "") else "FAIL",
                "git の認証が内側から見つからない",
                res.stdout.strip(),
            )

        # 環境変数: 設定の unset に入れた名前は渡らず、他は渡る
        names = cfg.get("env", {}).get("unset", [])
        if names:
            name = names[0]
            res = run(
                f"printenv {name} >/dev/null && echo {name}=set || echo {name}=unset; printenv SELFTEST_KEEP",
                env_extra={name: "x", "SELFTEST_KEEP": "kept"},
            )
            report.line(
                "PASS" if res.stdout.split() == [f"{name}=unset", "kept"] else "FAIL",
                "環境変数: 一覧の名前は消え、他は渡る",
                res.stdout.strip().replace("\n", " "),
            )
        else:
            report.line("SKIP", "環境変数の遮断", "設定の env.unset が空")

        host_dns = (
            shutil.which("getent")
            and subprocess.run(
                ["getent", "hosts", "example.com"], capture_output=True, timeout=30, check=False
            ).returncode
            == 0
        )
        if host_dns:  # ホストで引けない環境では、内側の確認にならない。WSL2 の resolv.conf は /mnt の下 (覆うと壊れる)
            res = run("getent hosts example.com >/dev/null && echo resolved || echo failed")
            report.line(
                "PASS" if res.stdout.strip() == "resolved" else "FAIL", "名前解決が内側でも動く"
            )
        else:
            report.line("SKIP", "名前解決", "ホストでも名前解決できない・getent が無い")

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
            "git: worktree で commit できて、共有の hooks は読み取り専用",
            (res.stdout + res.stderr).strip().replace("\n", " "),
        )

        res = run("awk -F: 'NR>2 {gsub(/ /, \"\", $1); print $1}' /proc/net/dev", offline=True)
        report.line(
            "PASS" if res.stdout.split() == ["lo"] else "FAIL",
            "--offline: ネットワークのインターフェースが lo だけ",
            res.stdout.strip(),
        )

    gpu_wanted = bool(cfg.get("gpu", {}).get("devices"))
    gpu_present = any(Path(p).exists() for p in ("/dev/dxg", "/dev/nvidiactl"))
    if not gpu_wanted or not gpu_present:
        report.line("SKIP", "GPU (CUDA カーネル)", "設定で無効か、この機に GPU が無い")
    else:
        with tempfile.TemporaryDirectory(prefix="pi-sandbox-selftest-") as tmp:
            (Path(tmp) / "kernel.py").write_text(CUDA_KERNEL, encoding="utf-8")
            res = sandbox(args.runner, args.config, Path(tmp), "python3 kernel.py")
        report.line(
            "PASS" if res.stdout.strip() == "cuda=ok" else "FAIL",
            "GPU: 内側で CUDA カーネルが動く",
            (res.stdout + res.stderr).strip()[-120:],
        )

    print("結果:", "FAIL あり" if report.failed else "すべて PASS (SKIP を除く)")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
