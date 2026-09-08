"""Opt-in integration tests for the deployed Windows PowerShell profiles."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY integration")

ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
PROBE = r"""
$startupErrors = @($Error | ForEach-Object { $_.ToString() })
$jobErrors = @(Get-Job | ForEach-Object {
    $_.Error | ForEach-Object { $_.ToString() }
})
$commands = @(Get-Command chezmoi, mise, uv, fzf -ErrorAction Stop |
    ForEach-Object { $_.Name })
$modules = @(Get-Module | ForEach-Object { $_.Name })
$wantedChords = @('Ctrl+d', 'Ctrl+x,Ctrl+g', 'Ctrl+x,Ctrl+f')
$chords = @{}
Get-PSReadLineKeyHandler -Bound |
    Where-Object { $wantedChords -contains $_.Key } |
    ForEach-Object { $chords[$_.Key] = $_.Function }
$functions = @('pbcopy', 'pwgen', 'ccd', 'xg', 'xf', 'sshf', 'wslls', 'dls' |
    Where-Object { Get-Command $_ -CommandType Function -ErrorAction Ignore })
$optional = @{}
foreach ($tool in 'ghq', 'z') {
    $optional[$tool] = [bool](Get-Command $tool -ErrorAction Ignore)
}
$result = @{
    startupErrors = $startupErrors
    jobErrors = $jobErrors
    inputRedirected = [Console]::IsInputRedirected
    outputRedirected = [Console]::IsOutputRedirected
    commands = $commands
    modules = $modules
    chords = $chords
    functions = $functions
    optional = $optional
    pathDuplicates = @(
        $env:Path -split ';' | Where-Object { $_ } | Group-Object |
            Where-Object Count -gt 1 | ForEach-Object { $_.Name }
    )
}
Write-Output ('CONPTY_RESULT:' + ($result | ConvertTo-Json -Compress))
Write-Output 'CONPTY_DONE'
"""


class PtyTimeout(Exception):
    """マーカーに到達しないまま待ち時間を使い切った。"""


class PtyReader:
    """pty からの読み取りを蓄積する。

    再送のたびに新しいバッファで読み直すと、前の試行で読んだ
    `CONPTY_RESULT:` を取りこぼして原因の分かりにくい失敗になるため、
    出力は試行をまたいで持ち越す。
    """

    def __init__(self, process):
        self.process = process
        self.raw = ""

    @property
    def text(self) -> str:
        return ANSI_ESCAPE.sub("", self.raw).replace("\r", "")

    def read_until(self, marker: str, timeout: float = 45) -> str:
        deadline = time.monotonic() + timeout
        while marker not in self.text:
            if time.monotonic() >= deadline:
                raise PtyTimeout(f"did not reach {marker!r}: {self.raw!r}")
            try:
                self.raw += self.process.read(65536)
            except TimeoutError:
                continue
            except EOFError:
                pytest.fail(f"PowerShell exited before {marker!r}: {self.text}")
        return self.text

    def send_until(self, command: str, marker: str, attempts: int = 3) -> str:
        """PSReadLine が最初のプロンプトを描き終える前の入力は捨てられることがある。

        キャッシュが空の初回起動ではプロンプト到達が遅れるため、応答が無ければ
        同じコマンドを送り直す。プローブは読み取りのみで副作用が無い。
        """
        for attempt in range(attempts):
            self.process.write(command + "\r")
            try:
                return self.read_until(marker, timeout=20)
            except PtyTimeout:
                if attempt == attempts - 1:
                    pytest.fail(f"PowerShell did not reach {marker!r}: {self.raw!r}")
                time.sleep(2)
        raise AssertionError("unreachable")


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_deployed_profile_in_interactive_terminal(shell: str, tmp_path: Path):
    winpty = pytest.importorskip("winpty", reason="Run with uv --with pywinpty")
    executable = shutil.which(shell)
    assert executable, f"{shell} is not installed"
    probe = tmp_path / "probe.ps1"
    probe.write_text(PROBE, encoding="utf-8")
    process = winpty.PtyProcess.spawn(
        [
            executable, "-NoLogo", "-NoExit", "-Command",
            "Set-PSReadLineOption -HistorySaveStyle SaveNothing; "
            "Write-Output 'CONPTY_READY'",
        ],
        dimensions=(40, 240),
        backend=1,
    )
    process.fileobj.settimeout(0.25)
    reader = PtyReader(process)
    try:
        # Let PSReadLine reach its first prompt before checking OnIdle jobs.
        reader.read_until("CONPTY_READY\n")
        time.sleep(3)
        quoted = str(probe).replace(chr(39), chr(39) * 2)
        output = reader.send_until(f"& '{quoted}'", "\nCONPTY_DONE\n")
        match = re.search(r"CONPTY_RESULT:(\{.*?\})\s*CONPTY_DONE", output, re.DOTALL)
        assert match, output
        # ConPTY inserts physical line wraps even inside JSON string values.
        result = json.loads(match[1].replace("\n", ""))
        assert result["startupErrors"] == []
        assert result["jobErrors"] == []
        assert result["inputRedirected"] is False
        assert result["outputRedirected"] is False
        assert {"chezmoi.exe", "mise.exe", "uv.exe", "fzf.exe"} <= set(result["commands"])
        assert {"PSReadLine", "ZLocation"} <= set(result["modules"])
        # プロファイルが定義する補助コマンドが対話セッションに揃っていること
        assert {"pbcopy", "pwgen", "ccd", "xg", "xf", "sshf", "wslls", "dls"} <= set(
            result["functions"]
        )
        # oh-my-posh がプロンプトを差し替えていること
        # (prompt 関数自体は ZLocation が更に包むため、モジュールの有無で確認する)
        assert "oh-my-posh-core" in set(result["modules"])
        # mise の activate を繰り返してもPATHが伸びないこと
        assert result["pathDuplicates"] == []
        chords = result["chords"]
        # 既定の Ctrl+d は DeleteCharOrExit で、端末が閉じてしまうため上書きしている
        assert chords.get("Ctrl+d") == "DeleteChar"
        # Register-FzfKeyHandler が OnIdle から呼ばれ、実際に登録されていること
        if result["optional"]["ghq"]:
            assert "Ctrl+x,Ctrl+g" in chords
        if result["optional"]["z"]:
            assert "Ctrl+x,Ctrl+f" in chords
        if shell == "pwsh":
            assert "PSFzf" in result["modules"]
        process.write("exit\r")
        deadline = time.monotonic() + 10
        while process.isalive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not process.isalive(), "PowerShell did not exit"
        assert process.exitstatus == 0
    finally:
        if process.isalive():
            process.terminate(force=True)


GIT_CONFIG_PROBE = (
    '"count=[" + $env:GIT_CONFIG_COUNT + "]"; '
    '"key0=[" + $env:GIT_CONFIG_KEY_0 + "]"; '
    '"value0=[" + $env:GIT_CONFIG_VALUE_0 + "]"; '
    '"key1=[" + $env:GIT_CONFIG_KEY_1 + "]"; '
    '"value1=[" + $env:GIT_CONFIG_VALUE_1 + "]"'
)


def run_with_git_config(shell: str, values: dict[str, str]) -> dict[str, str]:
    """配備済みプロファイルを読み込ませた上で GIT_CONFIG_* の最終状態を返す。"""
    executable = shutil.which(shell)
    assert executable, f"{shell} is not installed"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_CONFIG_")
    }
    env.update(values)
    completed = subprocess.run(
        [executable, "-NoLogo", "-Command", GIT_CONFIG_PROBE],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    parsed = {}
    for line in completed.stdout.splitlines():
        if "=[" in line:
            name, _, rest = line.partition("=[")
            parsed[name] = rest.rstrip("]")
    return parsed


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_git_config_environment_is_sanitized(shell: str):
    """pre-commit を壊す GIT_CONFIG_* の不整合をプロファイルが取り除くこと。

    Python の環境復元は Windows で空文字の環境変数を落とすため、
    `core.fsmonitor` の空値と、対応する KEY/VALUE を欠く COUNT の両方が起きる。
    """
    # 正常な組は保持する
    healthy = run_with_git_config(
        shell,
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "safe.bareRepository",
            "GIT_CONFIG_VALUE_0": "explicit",
            "GIT_CONFIG_KEY_1": "credential.interactive",
            "GIT_CONFIG_VALUE_1": "never",
        },
    )
    assert healthy["count"] == "2"
    assert healthy["value0"] == "explicit"
    assert healthy["value1"] == "never"

    # KEY/VALUE を欠く COUNT は Git を必ず失敗させるため、まとめて取り除く
    broken = run_with_git_config(shell, {"GIT_CONFIG_COUNT": "3"})
    assert broken["count"] == ""
    assert broken["key0"] == ""

    # 空値の core.fsmonitor は「無効」の意味を保ったまま Git が読める形にする。
    # 親プロセスから渡された空の環境変数は 5.1 / 7 のどちらでも空文字として
    # 見えるため（未設定とは区別される）、両方で同じ結果になる。
    empty_fsmonitor = run_with_git_config(
        shell,
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "safe.bareRepository",
            "GIT_CONFIG_VALUE_1": "explicit",
        },
    )
    assert empty_fsmonitor["count"] == "2"
    assert empty_fsmonitor["value0"] == "false"
    assert empty_fsmonitor["value1"] == "explicit"
