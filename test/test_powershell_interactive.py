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
$wantedChords = @('Enter', 'Ctrl+d', 'Ctrl+r', 'Ctrl+t', 'Ctrl+x,Ctrl+g', 'Ctrl+x,Ctrl+f')
$chords = @{}
Get-PSReadLineKeyHandler -Bound |
    Where-Object { $wantedChords -contains $_.Key } |
    ForEach-Object { $chords[$_.Key] = $_.Function }
# pure テーマは前景色だけを使う。既定テーマは背景色 (48;2;) の powerline になる。
$promptUsesBackgroundColor = (prompt) -match "$([char]27)\[[0-9;]*48;2;"
$functions = @(
    'pbcopy', 'pwgen', 'ccd', 'xg', 'xf', 'sshf', 'wslls', 'dls', 'vim', 'Get-CachedInitScript' |
    Where-Object { Get-Command $_ -CommandType Function -ErrorAction Ignore })
$optional = @{}
foreach ($tool in 'ghq', 'z') {
    $optional[$tool] = [bool](Get-Command $tool -ErrorAction Ignore)
}
$chocolateyProfile = "$env:ChocolateyInstall\helpers\chocolateyProfile.psm1"
$gitVimExists = [System.IO.File]::Exists("$env:ProgramFiles\Git\usr\bin\vim.exe")
$result = @{
    gitVimExists = [bool]$gitVimExists
    streaming = [bool]$global:_ompStreaming
    transientPrompt = [bool]$global:_ompTransientPrompt
    themeFromEnvironment = [bool](
        $env:POSH_THEMES_PATH -and
        [System.IO.File]::Exists([System.IO.Path]::Combine($env:POSH_THEMES_PATH, 'pure.omp.json'))
    )
    disableStreamingLeaked = $null -ne [Environment]::GetEnvironmentVariable('POSH_DISABLE_STREAMING')
    chocolateyInstalled = [bool]($env:ChocolateyInstall -and [System.IO.File]::Exists($chocolateyProfile))
    refreshenvType = [string](Get-Command refreshenv -ErrorAction Ignore).CommandType
    startupErrors = $startupErrors
    jobErrors = $jobErrors
    inputRedirected = [Console]::IsInputRedirected
    outputRedirected = [Console]::IsOutputRedirected
    commands = $commands
    modules = $modules
    chords = $chords
    functions = $functions
    optional = $optional
    promptUsesBackgroundColor = $promptUsesBackgroundColor
    pathDuplicates = @(
        $env:Path -split ';' | Where-Object { $_ } | Group-Object |
            Where-Object Count -gt 1 | ForEach-Object { $_.Name }
    )
}
Write-Output ('CONPTY_RESULT:' + ($result | ConvertTo-Json -Compress))
Write-Output 'CONPTY_DONE'
"""


def spawn_env(**extra: str) -> dict[str, str]:
    """oh-my-posh の streaming を左右する変数を、実行者の環境から遮断した環境を返す。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("POSH_DISABLE_STREAMING", "POSH_STREAMING")
    }
    env.update(extra)
    return env


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
        env=spawn_env(),
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
        # 読み込みに 0.2〜0.3 秒かかるモジュールは起動の idle で読まない
        # (idle の処理は打鍵を止める)。使うときまで仮の定義だけを置く。
        assert "PSFzf" not in result["modules"]
        assert "chocolateyProfile" not in result["modules"]
        if result["chocolateyInstalled"]:
            assert result["refreshenvType"] == "Function"
        # streaming (oh-my-posh の常駐プロセス) は PowerShell 6+ だけで有効にし、
        # init のための環境変数を子プロセスへ漏らさない
        assert result["disableStreamingLeaked"] is False
        # transient prompt は streaming のときだけ有効 (無いと Enter ごとに oh-my-posh を起動して遅い)
        assert result["transientPrompt"] is result["streaming"]
        if not result["themeFromEnvironment"]:
            assert result["streaming"] is (shell == "pwsh")
        # プロファイルが定義する補助コマンドが対話セッションに揃っていること
        # (分割したファイルを dot-source しても、定義がグローバルに残ること)
        assert {
            "pbcopy", "pwgen", "ccd", "xg", "xf", "sshf", "wslls", "dls", "Get-CachedInitScript"
        } <= set(result["functions"])
        # vim は Git for Windows の実体を直接呼ぶ関数 (scoop の shim は ssh で動かない)。無い機では定義しない
        assert ("vim" in result["functions"]) is result["gitVimExists"]
        # oh-my-posh がプロンプトを差し替えていること
        # (prompt 関数自体は ZLocation が更に包むため、モジュールの有無で確認する)
        assert "oh-my-posh-core" in set(result["modules"])
        # pure テーマであること。init 出力をキャッシュすると oh-my-posh が
        # 採番していないセッション ID になり、既定の powerline テーマに戻る。
        assert result["promptUsesBackgroundColor"] is False
        # mise の activate を繰り返してもPATHが伸びないこと
        assert result["pathDuplicates"] == []
        chords = result["chords"]
        # 既定の Ctrl+d は DeleteCharOrExit で、端末が閉じてしまうため上書きしている
        assert chords.get("Ctrl+d") == "DeleteChar"
        # oh-my-posh の Enter ハンドラ。-EditMode を init の後で設定すると割り当てごと消え、
        # transient prompt が出ず、streaming のプロンプトが更新されなくなる
        assert chords.get("Enter") == "OhMyPoshEnterKeyHandler"
        if shell == "pwsh":
            # PSFzf の割り当ては、初めて押されたときに本物へ差し替わる仮のもの
            assert chords.get("Ctrl+r") == "PSFzf (lazy)"
            assert chords.get("Ctrl+t") == "PSFzf (lazy)"
        # Register-FzfKeyHandler が OnIdle から呼ばれ、実際に登録されていること
        if result["optional"]["ghq"]:
            assert "Ctrl+x,Ctrl+g" in chords
        if result["optional"]["z"]:
            assert "Ctrl+x,Ctrl+f" in chords
        process.write("exit\r")
        deadline = time.monotonic() + 10
        while process.isalive() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not process.isalive(), "PowerShell did not exit"
        assert process.exitstatus == 0
    finally:
        if process.isalive():
            process.terminate(force=True)


LAZY_PROBE = (
    "$psfzf = [bool](Get-Module PSFzf); "
    "$ctrlR = (Get-PSReadLineKeyHandler -Bound | Where-Object Key -eq 'Ctrl+r').Function; "
    "$ctrlT = (Get-PSReadLineKeyHandler -Bound | Where-Object Key -eq 'Ctrl+t').Function; "
    "Write-Output ('LAZY_RESULT:' + (@{ psfzf = $psfzf; ctrlR = $ctrlR; ctrlT = $ctrlT } "
    "| ConvertTo-Json -Compress)); Write-Output 'LAZY_DONE'"
)


def test_psfzf_is_loaded_when_ctrl_r_is_first_pressed():
    """PSFzf は起動時に読まず、Ctrl+r を押したときに読み込んで本物の割り当てへ差し替える。"""
    winpty = pytest.importorskip("winpty", reason="Run with uv --with pywinpty")
    executable = shutil.which("pwsh")
    assert executable, "pwsh is not installed"
    process = winpty.PtyProcess.spawn(
        [
            executable, "-NoLogo", "-NoExit", "-Command",
            "Set-PSReadLineOption -HistorySaveStyle SaveNothing; "
            "Write-Output 'CONPTY_READY'",
        ],
        dimensions=(40, 240),
        env=spawn_env(),
        backend=1,
    )
    process.fileobj.settimeout(0.25)
    reader = PtyReader(process)
    try:
        reader.read_until("CONPTY_READY\n")
        time.sleep(3)
        # 履歴に 1 件入れてから Ctrl+r を押す (fzf の件数表示 `1/1` で起動を確かめる)
        reader.send_until("Write-Output 'SEED_DONE'", "\nSEED_DONE\n")
        before = len(reader.text)
        process.write("\x12")
        deadline = time.monotonic() + 20
        while not re.search(r"\d+/\d+", reader.text[before:]):
            assert time.monotonic() < deadline, f"fzf did not start: {reader.text[before:]!r}"
            try:
                reader.raw += process.read(65536)
            except TimeoutError:
                continue
        process.write("\x1b")  # fzf を閉じる
        time.sleep(1)
        output = reader.send_until(LAZY_PROBE, "\nLAZY_DONE\n")
        match = re.search(r"LAZY_RESULT:(\{.*?\})\s*LAZY_DONE", output, re.DOTALL)
        assert match, output
        result = json.loads(match[1].replace("\n", ""))
        assert result["psfzf"] is True
        # 仮の割り当てが PSFzf のものへ差し替わっている
        assert result["ctrlR"] and result["ctrlR"] != "PSFzf (lazy)"
        assert result["ctrlT"] and result["ctrlT"] != "PSFzf (lazy)"
    finally:
        if process.isalive():
            process.terminate(force=True)


STREAMING_PROBE = (
    "Write-Output ('STREAM_RESULT:' + (@{ "
    "streaming = [bool]$global:_ompStreaming; "
    "transient = [bool]$global:_ompTransientPrompt; "
    "disable = [Environment]::GetEnvironmentVariable('POSH_DISABLE_STREAMING') "
    "} | ConvertTo-Json -Compress)); Write-Output 'STREAM_DONE'"
)


def test_inherited_disable_streaming_is_kept_and_turns_streaming_off():
    """利用者が自分で立てた POSH_DISABLE_STREAMING は、プロファイルが消さず、streaming も transient も切れる。"""
    winpty = pytest.importorskip("winpty", reason="Run with uv --with pywinpty")
    executable = shutil.which("pwsh")
    assert executable, "pwsh is not installed"
    process = winpty.PtyProcess.spawn(
        [
            executable, "-NoLogo", "-NoExit", "-Command",
            "Set-PSReadLineOption -HistorySaveStyle SaveNothing; "
            "Write-Output 'CONPTY_READY'",
        ],
        dimensions=(40, 240),
        env=spawn_env(POSH_DISABLE_STREAMING="keep"),
        backend=1,
    )
    process.fileobj.settimeout(0.25)
    reader = PtyReader(process)
    try:
        reader.read_until("CONPTY_READY\n")
        time.sleep(3)
        output = reader.send_until(STREAMING_PROBE, "\nSTREAM_DONE\n")
        match = re.search(r"STREAM_RESULT:(\{.*?\})\s*STREAM_DONE", output, re.DOTALL)
        assert match, output
        result = json.loads(match[1].replace("\n", ""))
        assert result == {"streaming": False, "transient": False, "disable": "keep"}
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


REPO_ROOT = Path(__file__).resolve().parents[1]
SCOOP_PATH_SCRIPT = REPO_ROOT / "home/dot_config/powershell/scoop-path.ps1"
GUARD_SCRIPT = REPO_ROOT / "scripts/windows/run-with-redirection-guard.ps1"
GUARD_UNSUPPORTED = 125

# 偽の scoop を作り、Add-ScoopRealPathEntry の結果を出す。
#   foo: current -> 1.0 (bin あり)・旧版 0.9 の bin・shim あり   bar: current 無し・shim あり
#   baz: current が壊れた junction (実体が無い)             tools: current の PATH 項目だけ (shim 無し)
# $args[0] は偽の scoop の根、$args[1] は PATH の形、$args[2] は scoop-path.ps1
SCOOP_PATH_PROBE = r"""
$root = $args[0]
$shape = $args[1]
$scoopPathScript = $args[2]
$directories = "$root\apps\foo\1.0\bin", "$root\apps\foo\0.9\bin", "$root\apps\bar\2.0\bin"
$directories += "$root\apps\tools\3.0\bin", "$root\apps\baz\4.0", "$root\shims"
$null = New-Item -ItemType Directory -Force $directories
$null = New-Item -ItemType Junction -Path "$root\apps\foo\current" -Target "$root\apps\foo\1.0"
$null = New-Item -ItemType Junction -Path "$root\apps\tools\current" -Target "$root\apps\tools\3.0"
$null = New-Item -ItemType Junction -Path "$root\apps\baz\current" -Target "$root\apps\baz\4.0"
Remove-Item "$root\apps\baz\4.0"
Set-Content "$root\shims\foo.shim" "path = `"$root\apps\foo\current\bin\foo.exe`""
Set-Content "$root\shims\bar.shim" "path = `"$root\apps\bar\2.0\bin\bar.exe`""
Set-Content "$root\shims\baz.shim" "path = `"$root\apps\baz\current\baz.exe`""
$env:SCOOP = $root
$env:SCOOP_PROBE_ROOT = $root
$env:Path = switch ($shape) {
    'shims' { "C:\Windows\System32;$root\shims;C:\Windows" }
    'unexpanded' { '%SCOOP_PROBE_ROOT%\shims;C:\Windows' }
    'noshims' { 'C:\Windows\System32;C:\Windows' }
    'order' { "$root\shims;C:\Other;$root\apps\tools\current\bin;C:\Windows" }
    'stale' { "C:\Windows\System32;$root\apps\foo\0.9\bin;$root\shims" }
    'empty' { '' }
}
. $scoopPathScript
Add-ScoopRealPathEntry
Write-Output ('PATH=' + $env:Path)
Write-Output ('JUNCTION_BIN_VISIBLE=' + [System.IO.Directory]::Exists("$root\apps\foo\current\bin"))
Write-Output ('REAL_BIN_VISIBLE=' + [System.IO.Directory]::Exists("$root\apps\foo\1.0\bin"))
"""


def elevated() -> bool:
    """昇格したシェルが作った junction は信頼されるので、保護下で辿れない前提が成り立たない。"""
    if os.name != "nt":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def run_scoop_path_probe(tmp_path: Path, shape: str, *, guarded: bool = False) -> dict[str, str]:
    """pwsh 7 で probe を実行し、`PATH=` などの出力を辞書で返す。標準エラーは空であること。"""
    executable = shutil.which("pwsh")
    assert executable, "pwsh is not installed"
    probe = tmp_path / "scoop-path-probe.ps1"
    probe.write_text(SCOOP_PATH_PROBE, encoding="utf-8")
    # 形ごとに別の偽の scoop を作る (同じ場所へ junction を作り直すと失敗する)
    root = tmp_path / f"scoop-{shape}{'-guarded' if guarded else ''}"
    command = [executable, "-NoProfile", "-File"]
    if guarded:
        command += [str(GUARD_SCRIPT), executable, "-NoProfile", "-File"]
    command += [str(probe), str(root), shape, str(SCOOP_PATH_SCRIPT)]
    completed = subprocess.run(
        command, capture_output=True, text=True, errors="replace", timeout=120
    )
    if guarded and completed.returncode == GUARD_UNSUPPORTED:
        pytest.skip("この Windows は RedirectionGuard の設定を受け付けない")
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    values = {}
    for line in completed.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            values[name] = value
    values["root"] = str(root)
    return values


def test_scoop_shim_directories_are_inserted_just_before_the_shims(tmp_path: Path):
    """shim の指す先のディレクトリだけを、shims の直前へ足す。"""
    values = run_scoop_path_probe(tmp_path, "shims")
    root = values["root"]
    # foo だけ (bin)。bar は current が無い、baz は current が壊れている、tools は shim が無いので足さない
    assert values["PATH"] == rf"C:\Windows\System32;{root}\apps\foo\1.0\bin;{root}\shims;C:\Windows"


def test_scoop_path_handles_unexpanded_variables_and_missing_shims(tmp_path: Path):
    # ssh のセッションは、ユーザー PATH の未展開の %VAR% をそのまま渡すことがある
    values = run_scoop_path_probe(tmp_path, "unexpanded")
    assert values["PATH"] == rf"{values['root']}\apps\foo\1.0\bin;%SCOOP_PROBE_ROOT%\shims;C:\Windows"
    # shims が PATH に無い機は、shim の分を足さない。空の PATH でも何も起きない
    assert run_scoop_path_probe(tmp_path, "noshims")["PATH"] == r"C:\Windows\System32;C:\Windows"
    assert run_scoop_path_probe(tmp_path, "empty")["PATH"] == ""


def test_scoop_current_entries_are_replaced_in_place(tmp_path: Path):
    """PATH の `current` の項目は、その位置で実体にする。別のツールの前後関係 (解決の順) を変えない。"""
    values = run_scoop_path_probe(tmp_path, "order")
    root = values["root"]
    # shims より後ろの tools の位置はそのまま。foo の実体は shims の直前へ
    assert values["PATH"] == (
        rf"{root}\apps\foo\1.0\bin;{root}\shims;C:\Other;{root}\apps\tools\3.0\bin;C:\Windows"
    )


def test_stale_version_entries_from_a_parent_shell_are_refreshed(tmp_path: Path):
    """入れ子のシェルは、親が足した前の版の実体を引き継ぐ。scoop の更新後に、旧版が先に解決されない。"""
    values = run_scoop_path_probe(tmp_path, "stale")
    root = values["root"]
    # 0.9 の項目は、その位置で現行の 1.0 になる。shim の分は重複して足さない
    assert values["PATH"] == rf"C:\Windows\System32;{root}\apps\foo\1.0\bin;{root}\shims"


@pytest.mark.skipif(elevated(), reason="昇格したシェルが作った junction は保護下でも信頼される")
def test_scoop_real_directories_stay_reachable_under_redirection_guard(tmp_path: Path):
    """RedirectionGuard を有効にしたプロセス (ssh の再現) でも、実体のディレクトリは辿れる。

    試験が作った junction は管理者でない作成なので、保護下では辿れない。実体のディレクトリを足す理由そのもの。
    """
    values = run_scoop_path_probe(tmp_path, "shims", guarded=True)
    root = values["root"]
    assert values["JUNCTION_BIN_VISIBLE"] == "False"
    assert values["REAL_BIN_VISIBLE"] == "True"
    # junction の実体は、保護下でも読み取れる (リンク自体を開かずに対象を返す)
    assert rf"{root}\apps\foo\1.0\bin" in values["PATH"].split(";")


def test_redirection_guard_helper_passes_arguments_and_exit_codes_through():
    executable = shutil.which("pwsh")
    assert executable, "pwsh is not installed"

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [executable, "-NoProfile", "-File", str(GUARD_SCRIPT), *arguments],
            capture_output=True,
            text=True,
            timeout=120,
        )

    unsupported = run("pwsh", "-NoProfile", "-Command", "exit 0")
    if unsupported.returncode == GUARD_UNSUPPORTED:
        pytest.skip("この Windows は RedirectionGuard の設定を受け付けない")
    assert unsupported.returncode == 0, unsupported.stderr
    # 子のコマンドの終了コードを返す。-Command は子の引数で、ラッパーに奪われない
    assert run("pwsh", "-NoProfile", "-Command", "exit 37").returncode == 37
    # -Verbose などの共通パラメーターの名前も、子へそのまま渡す
    echoed = run("cmd.exe", "/c", "echo", "-Verbose", "-Debug")
    assert echoed.returncode == 0, echoed.stderr
    assert echoed.stdout.split() == ["-Verbose", "-Debug"]
    # 引数が無ければ使い方を出して 2
    assert run().returncode == 2


UV_PREFERENCE_PROBE = '"uv=[" + $env:UV_PYTHON_PREFERENCE + "]"'


def run_uv_preference_probe(**environment: str) -> str:
    """配備済みプロファイルを読み込ませた上で UV_PYTHON_PREFERENCE の最終値を返す (pwsh 7)。"""
    executable = shutil.which("pwsh")
    assert executable, "pwsh is not installed"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("SSH_CONNECTION", "UV_PYTHON_PREFERENCE")
    }
    env.update(environment)
    completed = subprocess.run(
        [executable, "-NoLogo", "-Command", UV_PREFERENCE_PROBE],
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip().rsplit("uv=[", 1)[1].removesuffix("]")


def test_uv_uses_only_the_system_python_over_ssh():
    """ssh では uv の管理 Python (junction 経由) が動かないので、システムの Python だけを使わせる。"""
    ssh = {"SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22"}
    # ローカルの uv は管理 Python を使うままにする
    assert run_uv_preference_probe() == ""
    assert run_uv_preference_probe(**ssh) == "only-system"
    # 利用者が指定しているときは、それを尊重する
    assert run_uv_preference_probe(**ssh, UV_PYTHON_PREFERENCE="system") == "system"
