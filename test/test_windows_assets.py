import re
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
    ).read_text(encoding="utf-8-sig")

    assert "--output json" not in script
    assert "winst Microsoft.PowerShell -CheckCommand pwsh" in script
    assert 'winst Craftware.Keyhac -CheckPath "$env:ProgramFiles\\keyhac\\keyhac.exe"' in script
    assert "winst jdx.mise -CheckCommand mise" in script
    assert "winst astral-sh.uv" in script
    assert "winst Bitwarden.CLI" in script
    # プロファイルから参照していないモジュールは導入しない
    assert "posh-git" not in script


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
    ).read_text(encoding="utf-8-sig")

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
        script = (ROOT / source_path).read_text(encoding="utf-8-sig")
        assert "Start-Process -Wait -PassThru" in script
        assert "$process.ExitCode -ne 0" in script


def test_pwgen_uses_cryptographic_randomness():
    script = (
        ROOT / "home/dot_config/powershell/commands/pwgen.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "RandomNumberGenerator" in script
    assert "Get-Random" not in script
    assert "Write-Output $passwords" in script
    assert "if (-not $NoNumerals)" in script


def test_windows_shell_helpers_handle_selection_safely():
    commands = ROOT / "home/dot_config/powershell/commands"
    docker = (commands / "docker.ps1").read_text(encoding="utf-8-sig")
    wsl = (commands / "wsl.ps1").read_text(encoding="utf-8-sig")

    assert "$fine_name" not in docker
    assert "docker compose" in docker
    assert "--format" in docker
    assert "IsNullOrWhiteSpace" in docker
    assert "Get-OnlineWslDistros" in wsl
    assert "$Matches[1] -ne 'NAME'" in wsl
    assert "$uid = [int]" in wsl


def test_profile_loaders_only_dot_source_the_shared_profile():
    """Documents 配下はローダーに保ち、実体は ~/.config/powershell に置く。"""
    for host_directory in ("PowerShell", "WindowsPowerShell"):
        loader_directory = ROOT / "home" / "Documents" / host_directory
        assert not (loader_directory / "profile.ps1").exists()
        loader = (loader_directory / "profile.ps1.tmpl").read_text(encoding="utf-8-sig")
        # PowerShell の $HOME は HOMEDRIVE+HOMEPATH 由来で、ドメイン参加機では
        # chezmoi の ~ (%USERPROFILE%) と一致しないことがある
        assert "$HOME" not in strip_comments(loader)
        assert '. "{{ .chezmoi.homeDir }}/.config/powershell/profile.ps1"' in loader


def test_powershell_profile_activates_mise():
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "activate pwsh --shims" in profile
    assert "$LASTEXITCODE -ne 0" in profile
    assert "[Console]::OutputEncoding = $utf8NoBom" in profile
    assert '{{ includeTemplate "powershell/git-config-env.ps1" }}' in profile


INTERACTIVE_GUARD = "$startupIsNonInteractive -and -not $startupKeepsRunning"


def strip_comments(script: str) -> str:
    """行頭コメントを除いたコードだけを返す（説明文での誤検知を避けるため）。

    行内の ``#`` では切らない。文字列や正規表現に ``#`` を含むコード行を
    黙って読み飛ばし、検査が無効化されるのを避けるため。
    """
    return "\n".join(
        "" if line.lstrip().startswith("#") else line for line in script.splitlines()
    )


def split_at_interactive_guard(profile: str) -> tuple[str, str]:
    guard = profile.split(INTERACTIVE_GUARD, 1)
    assert len(guard) == 2, "対話ガードが見つからない"
    head, tail = guard
    # ガード自体の条件式とその閉じ括弧までは head に含めない
    return head, tail


def test_powershell_profile_skips_interactive_setup_when_not_interactive():
    """AllHosts プロファイルは非対話起動でも読まれるため、対話部分を分離する。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    # stdio のリダイレクトに加えて、起動引数でも非対話を判定する
    assert "[Console]::IsInputRedirected" in profile
    assert "[Environment]::GetCommandLineArgs()" in profile
    assert "'noexit'.StartsWith($switchName)" in profile

    head, tail = (strip_comments(part) for part in split_at_interactive_guard(profile))
    # プロンプト・キーバインド・モジュール読み込みは対話時のみ
    for interactive_only in ("oh-my-posh init", "Set-PSReadLine", "Register-EngineEvent"):
        assert interactive_only not in head
        assert interactive_only in tail


def test_powershell_profile_avoids_slow_cmdlets_before_the_interactive_guard():
    """Management / Utility の初回読み込みと Get-Command の探索は各 0.25 秒かかる。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")
    template = (
        ROOT / "home/.chezmoitemplates/powershell/git-config-env.ps1"
    ).read_text(encoding="utf-8-sig")
    head = strip_comments(split_at_interactive_guard(profile)[0] + template)

    for slow in ("New-Object", "Join-Path", "Set-Alias", "Test-Path", "Get-Item ", "Get-Content"):
        assert slow not in head, slow


def test_powershell_init_cache_returns_before_running_command_discovery():
    """キャッシュが有効な間は Get-Command のコマンド探索を走らせない。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")
    body = strip_comments(profile).split("function Get-CachedInitScript", 1)[1]

    cache_hit = body.index("return $cacheFile")
    discovery = body.index("Get-Command $CommandName")
    assert cache_hit < discovery


def test_powershell_init_cache_is_written_with_a_bom():
    """Windows PowerShell 5.1 は BOM の無い .ps1 を ANSI として読むため。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "$utf8WithBom = [System.Text.UTF8Encoding]::new($true)" in profile
    for call in re.findall(r"\[System\.IO\.File\]::WriteAllText\([^)]*\)", profile):
        assert "$utf8WithBom" in call, call


def test_powershell_init_cache_failure_does_not_skip_activation():
    """キャッシュは最適化であり、保存に失敗しても生成済みの内容を使う。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "Failed to store the $Name init cache" in profile
    assert "return $tempFile" in profile
    # 本体の設置に成功した後の stamp 書き込み失敗で activate を落とさない
    assert "Failed to store the $Name cache stamp" in profile
    # 別シェルが書き換え中の stamp は読めないことがある。起動時エラーにしない
    assert "$stamp = [System.IO.File]::ReadAllText($stampFile)" in profile
    read_guard = profile.split("$stamp = [System.IO.File]::ReadAllText($stampFile)", 1)[0]
    assert read_guard.rstrip().endswith("try {")
    # dot-source は .ps1 以外を Application として扱い、実行せずに開こうとする
    assert '"$Name.$PID.tmp.ps1"' in profile
    assert '"$Name.*.tmp.ps1"' in profile
    # 同時起動した別プロセスの書き込み中ファイルを消さない
    assert "[DateTime]::UtcNow.AddHours(-1)" in profile
    # LOCALAPPDATA 未定義時に相対パスのキャッシュを作らない
    assert "[Environment]::GetFolderPath('LocalApplicationData')" in profile


def test_oh_my_posh_init_is_not_cached():
    """oh-my-posh はテーマ設定をセッション ID に紐付けるため init はキャッシュ不可。

    キャッシュした init を別セッションで読み込むと、oh-my-posh が採番していない
    ID になり設定を引けず、既定テーマに戻る。実際のテーマは
    test_powershell_interactive.py::test_deployed_profile_in_interactive_terminal
    がレンダリング結果で検証する。
    """
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "POSH_SESSION_ID" not in profile
    assert "Get-CachedInitScript" in profile
    assert "-Name 'oh-my-posh'" not in profile
    assert profile.count("Get-CachedInitScript -Name") == 1


def test_cached_init_scripts_have_a_direct_fallback():
    """キャッシュ本体が掴まれていても dot-source は失敗する。退避経路を持つ。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "Cached mise activation failed; running mise directly" in profile
    # Invoke-Expression は空文字を受け付けない (ValidateNotNullOrEmpty)
    for call in re.findall(r"Invoke-Expression [^\n]*", strip_comments(profile)):
        assert re.fullmatch(r"Invoke-Expression \$\w+", call), call
    assert profile.count("[string]::IsNullOrWhiteSpace($miseActivation)") == 1
    assert profile.count("[string]::IsNullOrWhiteSpace($poshActivation)") == 1
    # dot-source は try/catch の中にある
    assert profile.count(". $miseInit") == 1
    head = profile.split(". $miseInit", 1)[0]
    assert head.rstrip().endswith("try {")


def test_startup_detection_covers_positional_script_arguments():
    """`pwsh script.ps1` は -File が現れないため、位置引数も見る必要がある。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "$argument.EndsWith('.ps1', [StringComparison]::OrdinalIgnoreCase)" in profile


def test_powershell_path_updates_are_idempotent():
    """mise の activate は毎回 PATH を先頭へ足すため、重複の除去が必要。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "function Add-EnvPathEntry" in profile
    assert "function Remove-DuplicateEnvPathEntry" in profile
    assert "$env:Path +=" not in profile


def test_pbcopy_forwards_pipeline_input():
    """エイリアスと違い、関数は標準入力を子プロセスへ引き継がない。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "function pbcopy { $input | clip.exe }" in profile


def test_powershell_init_cache_is_keyed_on_the_executable():
    """ツールを更新したらキャッシュを作り直す。"""
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "$executable.FullName" in profile
    assert "$executable.Length" in profile
    assert "$executable.LastWriteTimeUtc.Ticks" in profile


def test_fzf_key_handlers_are_registered_from_a_single_place():
    """OnIdle の登録はプロファイル側 1 箇所に集約する。"""
    fzf = (
        ROOT / "home/dot_config/powershell/commands/fzf.ps1"
    ).read_text(encoding="utf-8-sig")
    profile = (
        ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "Register-EngineEvent" not in fzf
    assert "function Register-FzfKeyHandler" in fzf
    assert profile.count("Register-EngineEvent") == 1
    assert "Register-FzfKeyHandler" in profile
    # 失敗を握り潰さない
    assert "-ErrorAction SilentlyContinue" not in profile


def test_profile_loader_is_redeployed_when_documents_is_redirected():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "run_after_345_powershell_profile.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "[Environment]::GetFolderPath('MyDocuments')" in script
    assert "'PowerShell', 'WindowsPowerShell'" in script
    assert '. "{{ .chezmoi.homeDir }}/.config/powershell/profile.ps1"' in script
    # ローダー本体と同じ内容を書くため、$HOME ではなく chezmoi のホームを使う
    assert "$managedDocuments = Join-Path '{{ .chezmoi.homeDir }}' 'Documents'" in script
    # Set-Content -Encoding utf8 は 5.1 が BOM 付き、7 が BOM 無しを書く。
    # chezmoi は .ps1 を pwsh 7 で実行するため、BOM を明示的に付ける必要がある。
    assert "-Encoding utf8" not in strip_comments(script)
    assert "[System.Text.UTF8Encoding]::new($true)" in script
    assert "$bytes[0] -ne 0xEF" in script


def test_shared_git_config_sanitizer_uses_dotnet_apis_only():
    """Env: プロバイダーは Management の読み込みを伴い 0.25 秒かかるため。

    「未設定」と「空文字」の区別を含めた実挙動は
    test_powershell_interactive.py::test_git_config_environment_is_sanitized
    が、配備済みプロファイルを実際に起動して 5.1 / 7 の両方で検証する。
    """
    template = (
        ROOT / "home/.chezmoitemplates/powershell/git-config-env.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "Env:GIT_CONFIG" not in template
    assert "Get-ChildItem Env:" not in strip_comments(template)
    assert "$gitConfigKey -eq 'core.fsmonitor'" in template
    assert "$gitConfigValue -eq ''" in template
    assert "[Environment]::SetEnvironmentVariable(\"GIT_CONFIG_VALUE_$i\", 'false')" in template
    assert "'^GIT_CONFIG_(COUNT|KEY_\\d+|VALUE_\\d+)$'" in template


def test_windows_terminal_settings_are_replaced_atomically():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "run_after_341_terminal.py.tmpl"
    ).read_text(encoding="utf-8-sig")

    assert "NamedTemporaryFile" in script
    assert "os.replace(temp_path, target_path)" in script
    assert "target_dict == original_dict" in script
    assert 'if __name__ == "__main__":' in script


def test_standalone_windows_installers_use_supported_winget_detection():
    develop = (ROOT / "scripts/windows/develop.ps1").read_text(encoding="utf-8-sig")
    cuda = (ROOT / "scripts/windows/cuda.ps1").read_text(encoding="utf-8-sig")

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
    ).read_text(encoding="utf-8-sig")

    assert "$chocoVersion.Major -lt 2" in script
    assert "$listArgs += '--local-only'" in script


def test_scoop_setup_skips_installed_apps_and_invalid_git_config():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "310_packages"
        / "run_once_before_311_scoop.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    # プロファイルと同じ実装を共有し、片方だけ直る状態を避ける
    assert '{{ includeTemplate "powershell/git-config-env.ps1" }}' in script
    assert "$missingApps.Count -eq 0" in script


def test_powershell_sources_start_with_a_utf8_bom():
    """Windows PowerShell 5.1 は BOM の無い .ps1 を ANSI コードページとして読む。

    日本語コメントが CP932 として解釈されると、行末の 2 バイト目が改行を
    飲み込んでコメントが次行まで伸びる。直後がコードだと、そのコードは
    エラーも警告も出さずに実行されなくなる。

    `.chezmoitemplates/` 配下は includeTemplate で他ファイルへ埋め込まれるため
    対象外（先頭以外に BOM が現れてしまう）。
    """
    sources = [
        path
        for directory in ("home", "scripts")
        for pattern in ("**/*.ps1", "**/*.ps1.tmpl")
        for path in (ROOT / directory).glob(pattern)
        if ".chezmoitemplates" not in path.parts
    ]
    assert sources

    missing = [
        str(path.relative_to(ROOT))
        for path in sources
        if not path.read_bytes().startswith(b"\xef\xbb\xbf")
    ]
    assert missing == []
