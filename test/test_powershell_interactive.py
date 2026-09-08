"""Opt-in integration tests for the deployed Windows PowerShell profiles."""

from __future__ import annotations

import json
import os
import re
import shutil
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
$result = @{
    startupErrors = $startupErrors
    jobErrors = $jobErrors
    inputRedirected = [Console]::IsInputRedirected
    outputRedirected = [Console]::IsOutputRedirected
    commands = $commands
    modules = $modules
}
Write-Output ('CONPTY_RESULT:' + ($result | ConvertTo-Json -Compress))
Write-Output 'CONPTY_DONE'
"""


def read_until(process, marker: str, timeout: float = 45) -> str:
    deadline = time.monotonic() + timeout
    raw_output = ""
    output = ""
    while time.monotonic() < deadline:
        try:
            chunk = process.read(65536)
        except TimeoutError:
            continue
        except EOFError:
            pytest.fail(f"PowerShell exited before {marker!r}: {output}")
        raw_output += chunk
        output = ANSI_ESCAPE.sub("", raw_output).replace("\r", "")
        if marker in output:
            return output
    pytest.fail(f"PowerShell did not reach {marker!r}: {raw_output!r}")


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
    try:
        # Let PSReadLine reach its first prompt before checking OnIdle jobs.
        read_until(process, "CONPTY_READY\n")
        time.sleep(3)
        process.write(f"& '{str(probe).replace(chr(39), chr(39) * 2)}'\r")
        output = read_until(process, "\nCONPTY_DONE\n")
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
