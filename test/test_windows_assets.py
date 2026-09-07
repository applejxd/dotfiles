from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_winget_installer_uses_supported_detection_and_package_ids():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "310_packages"
        / "run_once_before_310_winget.ps1.tmpl"
    ).read_text(encoding="utf-8")

    assert "--output json" not in script
    assert "winst Microsoft.PowerShell -CheckCommand pwsh" in script
    assert 'winst Craftware.Keyhac -CheckPath "$env:ProgramFiles\\keyhac\\keyhac.exe"' in script
    assert "winst jdx.mise -CheckCommand mise" in script
    assert "winst astral-sh.uv" in script
    assert "winst Bitwarden.CLI" in script


def test_zero_byte_windows_targets_use_empty_attribute():
    source_paths = [
        "home/AppData/Local/Microsoft/PowerToys/NewPlus/Template/cpp/src/empty_main.cpp",
        "home/AppData/Roaming/Keypirinha/User/empty_command.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_everything.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_filebrowser.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_repos.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_snippets.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_taskswitcher.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_terminal-profiles.ini",
        "home/AppData/Roaming/Keypirinha/User/empty_url.ini",
    ]

    for source_path in source_paths:
        path = ROOT / source_path
        assert path.is_file()
        assert path.stat().st_size == 0


def test_vscode_installer_does_not_hide_extension_failures():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "run_once_after_340_vscode.ps1"
    ).read_text(encoding="utf-8")

    assert "$LASTEXITCODE -ne 0" in script
    assert "$failedExtensions += $extension" in script
    assert "throw" in script
    for disallowed_extension in (
        "Anan.jetbrains-darcula-theme",
        "chadalen.vscode-jetbrains-icon-theme",
        "genieai.chatgpt-vscode",
        "saoudrizwan.claude-dev",
        "yzhang.markdown-all-in-one",
        "DavidAnson.vscode-markdownlint",
        "xaver.clang-format",
        "jeff-hykin.better-cpp-syntax",
        "notskm.clang-tidy",
        "twxs.cmake",
    ):
        assert disallowed_extension not in script


def test_elevated_windows_scripts_propagate_child_failures():
    source_paths = [
        "home/.chezmoiscripts/300_windows/310_packages/run_once_before_312_choco.ps1",
        "home/.chezmoiscripts/300_windows/320_regkey/run_once_after_320_system.ps1",
    ]

    for source_path in source_paths:
        script = (ROOT / source_path).read_text(encoding="utf-8")
        assert "Start-Process -Wait -PassThru" in script
        assert "$process.ExitCode -ne 0" in script


def test_pwgen_uses_cryptographic_randomness():
    script = (ROOT / "home/Documents/commands/pwgen.ps1").read_text(encoding="utf-8")

    assert "RandomNumberGenerator" in script
    assert "Get-Random" not in script
    assert "Write-Output $passwords" in script
    assert "if (-not $NoNumerals)" in script


def test_windows_shell_helpers_handle_selection_safely():
    docker = (ROOT / "home/Documents/commands/docker.ps1").read_text(encoding="utf-8")
    wsl = (ROOT / "home/Documents/commands/wsl.ps1").read_text(encoding="utf-8")

    assert "$fine_name" not in docker
    assert "docker compose" in docker
    assert "--format" in docker
    assert "IsNullOrWhiteSpace" in docker
    assert "Get-OnlineWslDistros" in wsl
    assert "$Matches[1] -ne 'NAME'" in wsl
    assert "$uid = [int]" in wsl


def test_powershell_profile_activates_mise():
    profile = (
        ROOT / "home/Documents/WindowsPowerShell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8")

    assert "activate pwsh --shims" in profile
    assert "$LASTEXITCODE -eq 0" in profile
    assert "[Console]::OutputEncoding = $utf8NoBom" in profile


def test_windows_terminal_settings_are_replaced_atomically():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "run_after_341_terminal.py.tmpl"
    ).read_text(encoding="utf-8")

    assert "NamedTemporaryFile" in script
    assert "os.replace(temp_path, target_path)" in script
    assert "target_dict == original_dict" in script
    assert 'if __name__ == "__main__":' in script


def test_standalone_windows_installers_use_supported_winget_detection():
    develop = (ROOT / "scripts/windows/develop.ps1").read_text(encoding="utf-8")
    cuda = (ROOT / "scripts/windows/cuda.ps1").read_text(encoding="utf-8")

    assert "--output json" not in develop
    assert "--output json" not in cuda
    assert "Nvidia.GeForceNow" not in develop
    assert "Nvidia.GeForceNow" not in cuda


def test_chocolatey_setup_supports_v1_and_v2_listing():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "310_packages"
        / "run_once_before_312_choco.ps1"
    ).read_text(encoding="utf-8")

    assert "$chocoVersion.Major -lt 2" in script
    assert "$listArgs += '--local-only'" in script
