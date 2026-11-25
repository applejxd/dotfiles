"""PowerShell の起動と打鍵・Enter の遅延を、ConPTY の対話セッションで測る。

実行 (Windows。pywinpty は ConPTY を Python から扱うための依存):

    uv run --with pywinpty --no-project python scripts/windows/measure_pwsh_latency.py startup --shell pwsh
    uv run --with pywinpty --no-project python scripts/windows/measure_pwsh_latency.py enter --shell pwsh

- startup: 起動からプロンプト (pure テーマの ❯) が出るまでの時間と、プロンプトの `--delays` 秒後に
  1 文字 (`Q`) を打ったときの反映までの時間 (起動後の idle の処理が打鍵を止める長さ)。
- enter: 起動後に落ち着くのを待ってから Enter を連打し、押してから次のプロンプトが出るまでの時間
  (1 コマンドごとのプロンプトの遅延)。`--cwd` を git の作業ツリーにすると git セグメントも含む。

`--profile-file` を付けると、配備済みのプロファイルではなく、そのファイルを `-NoProfile` 起動のあとに
dot-source して測る (適用前の変更の比較用)。配備済みのプロファイルを測るなら付けない。
測った結果の記録は docs/research/shell/powershell-slow-2026-11.md。
"""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import statistics
import time

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
PROMPT_MARK = "\u276f"  # pure テーマのプロンプト記号
# 打鍵の反映の目印。プロンプト (ユーザー名・ブランチ名・実行時間) や警告に現れにくい文字にする
PROBE_CHAR = "Q"


def spawn(winpty, shell: str, profile_file: str, cwd: str):
    executable = shutil.which(shell)
    if not executable:
        raise SystemExit(f"{shell} が見つからない")
    args = [executable, "-NoLogo"]
    if profile_file:
        args += ["-NoProfile", "-NoExit", "-Command", f". '{profile_file}'"]
    process = winpty.PtyProcess.spawn(args, dimensions=(40, 200), cwd=cwd, backend=1)
    process.fileobj.settimeout(0.005)
    return process


class Screen:
    """pty の出力を蓄積し、制御列を除いた文字列を返す。"""

    def __init__(self, process) -> None:
        self.process = process
        self.raw = ""

    def pump(self) -> None:
        with contextlib.suppress(TimeoutError):
            self.raw += self.process.read(65536)

    @property
    def text(self) -> str:
        return ANSI.sub("", self.raw).replace("\r", "")


def startup_once(winpty, shell, profile_file, cwd, delay, mark):
    """(プロンプトまでの秒, 打鍵が反映されるまでの秒) を返す。"""
    started = time.monotonic()
    process = spawn(winpty, shell, profile_file, cwd)
    screen = Screen(process)
    t_prompt = t_sent = t_echo = None
    sent_at = 0
    try:
        while time.monotonic() - started < 30:
            screen.pump()
            now = time.monotonic()
            text = screen.text
            if t_prompt is None and mark in text:
                t_prompt = now - started
            if t_prompt is not None and t_sent is None and now - started >= t_prompt + delay:
                sent_at = len(text)
                process.write(PROBE_CHAR)
                t_sent = now
            if t_sent is not None and PROBE_CHAR in text[sent_at:]:
                t_echo = now - t_sent
                break
        return t_prompt, t_echo
    finally:
        process.terminate(force=True)


def enter_once(winpty, shell, profile_file, cwd, count, settle, mark):
    """Enter を押してから次のプロンプトが出るまでの秒の一覧。"""
    process = spawn(winpty, shell, profile_file, cwd)
    screen = Screen(process)
    try:
        started = time.monotonic()
        while mark not in screen.text and time.monotonic() - started < 30:
            screen.pump()
        # 起動直後の idle の処理 (ZLocation の読み込みなど) が終わるまで待つ
        end = time.monotonic() + settle
        while time.monotonic() < end:
            screen.pump()
        times = []
        for i in range(count):
            start_len = len(screen.text)
            process.write(f"'M{i}'\r")
            sent = time.monotonic()
            while time.monotonic() - sent < 15:
                screen.pump()
                found = re.search(rf"\nM{i}\n(.*)", screen.text[start_len:], re.DOTALL)
                if found and mark in found.group(1):
                    times.append(time.monotonic() - sent)
                    break
            time.sleep(0.3)
        return times
    finally:
        process.terminate(force=True)


def summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (
        f"中央値 {statistics.median(values) * 1000:.0f} ms "
        f"(最小 {min(values) * 1000:.0f} / 最大 {max(values) * 1000:.0f}, n={len(values)})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("mode", choices=["startup", "enter"])
    parser.add_argument("--shell", default="pwsh", help="pwsh または powershell")
    parser.add_argument(
        "--n", type=int, default=5, help="起動の回数 (enter は 1 回の起動での Enter の回数)"
    )
    parser.add_argument(
        "--delays", default="0.0,0.4,0.8", help="startup: プロンプトの何秒後に打つか"
    )
    parser.add_argument("--cwd", default=".", help="起動時の作業ディレクトリ")
    parser.add_argument("--profile-file", default="")
    parser.add_argument(
        "--mark", default=PROMPT_MARK, help="プロンプトの印。-NoProfile の素の起動は 'PS C:'"
    )
    args = parser.parse_args()

    import winpty  # Windows 専用の依存。--help を依存なしで動かすため、ここで読み込む

    if args.mode == "startup":
        for delay in (float(x) for x in args.delays.split(",")):
            prompts, echoes = [], []
            for _ in range(args.n):
                prompt, echo = startup_once(
                    winpty, args.shell, args.profile_file, args.cwd, delay, args.mark
                )
                if prompt is not None:
                    prompts.append(prompt)
                if echo is not None:
                    echoes.append(echo)
                time.sleep(0.5)
            print(
                f"{args.shell} 打鍵 +{delay}s: プロンプト {summary(prompts)} | 打鍵の反映 {summary(echoes)}"
            )
    else:
        times = enter_once(winpty, args.shell, args.profile_file, args.cwd, args.n, 2.0, args.mark)
        print(f"{args.shell} cwd={args.cwd}: Enter→プロンプト {summary(times)}")


if __name__ == "__main__":
    main()
