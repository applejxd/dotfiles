import ast
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
        ROOT / "home" / ".chezmoiscripts" / "300_windows" / "run_once_after_340_vscode.ps1"
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


ADMIN_SCRIPT = (
    ROOT / "home/.chezmoiscripts/300_windows/310_packages/run_once_before_309_admin.ps1.tmpl"
)


def test_admin_steps_are_consolidated_into_one_elevation():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    # 昇格は 309 と、新しい鍵のときだけの 348 (指紋の記録で通常は出ない)。ほかの chezmoi スクリプトは自前で昇格しない
    assert script.count("'RunAs'") == 1
    key_script = ROOT / "home/.chezmoiscripts/300_windows/run_after_348_authorized_keys.ps1.tmpl"
    assert key_script.read_text(encoding="utf-8-sig").count("'RunAs'") == 1
    for path in (ROOT / "home" / ".chezmoiscripts" / "300_windows").rglob("*"):
        if path.is_file() and path not in (ADMIN_SCRIPT, key_script):
            assert "RunAs" not in path.read_text(encoding="utf-8-sig").replace("Runas", "RunAs"), path
    # 昇格子の終了を待ち、終了コードを検証する
    assert "Wait         = $true" in script and "PassThru     = $true" in script
    assert "$process.ExitCode -ne 0" in script
    assert "UAC" in script
    # 実行前に SHA-256 を照合し、メモリ上のテキストを実行する
    assert "-EncodedCommand" in script and "SHA256" in script
    assert "[Text.Encoding]::Unicode" in script
    # 許可リストの外・重複は昇格子が拒否する
    assert "exit 2" in script
    for key in ("Chocolatey", "chocolateygui", "Keypirinha", "WinSCP", "VSCode", "LongPaths", "RDP"):
        assert f"'{key}'" in script
    # 昇格子はユーザープロファイルに書かない
    assert "HKCU:" not in script and "$env:APPDATA" not in script


def test_admin_setup_rdp_never_opens_public_profile():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    assert "Set-NetFirewallRule -Name $name -Profile Domain, Private -Enabled True" in script
    assert "-PolicyStore ActiveStore" in script
    assert "($profileBits -band 4) -ne 0" in script
    # Shadow 規則と Remote Desktop Users は触らない
    assert "Shadow-In" not in script.replace("Shadow rule", "")
    assert "Add-LocalGroupMember" not in script


def test_admin_setup_explains_winscp_recovery():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    assert "winget list --id WinSCP.WinSCP" in script
    assert "rerun `chezmoi apply`" in script


def test_pwgen_uses_cryptographic_randomness():
    script = (ROOT / "home/dot_config/powershell/commands/pwgen.ps1").read_text(
        encoding="utf-8-sig"
    )

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


PROFILE_LOADER_INCLUDE = '{{ includeTemplate "powershell/profile-loader.ps1" . | trim }}'


def test_profile_loaders_only_dot_source_the_shared_profile():
    """Documents 配下はローダーに保ち、実体は ~/.config/powershell に置く。"""
    template = (ROOT / "home/.chezmoitemplates/powershell/profile-loader.ps1").read_text(
        encoding="utf-8"
    )
    # PowerShell の $HOME は HOMEDRIVE+HOMEPATH 由来で、ドメイン参加機では
    # chezmoi の ~ (%USERPROFILE%) と一致しないことがある
    assert "$HOME" not in strip_comments(template)
    assert '. "{{ .chezmoi.homeDir }}/.config/powershell/profile.ps1"' in template
    for host_directory in ("PowerShell", "WindowsPowerShell"):
        loader_directory = ROOT / "home" / "Documents" / host_directory
        assert not (loader_directory / "profile.ps1").exists()
        loader = (loader_directory / "profile.ps1.tmpl").read_text(encoding="utf-8-sig")
        # 本文は run_after_345 と共有し、Documents 側に独自のコードを持たない
        assert loader == PROFILE_LOADER_INCLUDE + "\n"


def test_powershell_profile_activates_mise():
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

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
    return "\n".join("" if line.lstrip().startswith("#") else line for line in script.splitlines())


def split_at_interactive_guard(profile: str) -> tuple[str, str]:
    guard = profile.split(INTERACTIVE_GUARD, 1)
    assert len(guard) == 2, "対話ガードが見つからない"
    head, tail = guard
    # ガード自体の条件式とその閉じ括弧までは head に含めない
    return head, tail


def test_powershell_profile_skips_interactive_setup_when_not_interactive():
    """AllHosts プロファイルは非対話起動でも読まれるため、対話部分を分離する。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

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
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    template = (ROOT / "home/.chezmoitemplates/powershell/git-config-env.ps1").read_text(
        encoding="utf-8-sig"
    )
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")
    head = strip_comments(split_at_interactive_guard(profile)[0] + template + cache)

    for slow in ("New-Object", "Join-Path", "Set-Alias", "Test-Path", "Get-Item ", "Get-Content"):
        assert slow not in head, slow


def test_init_cache_is_dot_sourced_at_the_top_level():
    """関数の中で dot-source すると、定義がその関数のスコープに閉じてしまう。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    head = split_at_interactive_guard(profile)[0]

    dot_source = re.search(r'^\. "\$PSScriptRoot/cache\.ps1"$', head, re.MULTILINE)
    assert dot_source, "cache.ps1 をトップレベルで読み込んでいない"
    assert dot_source.start() < profile.index("Get-CachedInitScript -Name")


def test_powershell_init_cache_returns_before_running_command_discovery():
    """キャッシュが有効な間は Get-Command のコマンド探索を走らせない。"""
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")
    body = strip_comments(cache).split("function Get-CachedInitScript", 1)[1]

    cache_hit = body.index("return $cacheFile")
    discovery = body.index("Get-Command $CommandName")
    assert cache_hit < discovery


def test_powershell_init_cache_is_written_with_a_bom():
    """Windows PowerShell 5.1 は BOM の無い .ps1 を ANSI として読むため。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")

    assert "$utf8WithBom = [System.Text.UTF8Encoding]::new($true)" in cache
    for call in re.findall(r"\[System\.IO\.File\]::WriteAllText\([^)]*\)", profile + cache):
        assert "$utf8WithBom" in call, call


def test_powershell_init_cache_failure_does_not_skip_activation():
    """キャッシュは最適化であり、保存に失敗しても生成済みの内容を使う。"""
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")

    assert "Failed to store the $Name init cache" in cache
    assert "return $tempFile" in cache
    # 本体の設置に成功した後の stamp 書き込み失敗で activate を落とさない
    assert "Failed to store the $Name cache stamp" in cache
    # 別シェルが書き換え中の stamp は読めないことがある。起動時エラーにしない
    assert "$stamp = [System.IO.File]::ReadAllText($stampFile)" in cache
    read_guard = cache.split("$stamp = [System.IO.File]::ReadAllText($stampFile)", 1)[0]
    assert read_guard.rstrip().endswith("try {")
    # dot-source は .ps1 以外を Application として扱い、実行せずに開こうとする
    assert '"$Name.$PID.tmp.ps1"' in cache
    assert '"$Name.*.tmp.ps1"' in cache
    # 同時起動した別プロセスの書き込み中ファイルを消さない
    assert "[DateTime]::UtcNow.AddHours(-1)" in cache
    # LOCALAPPDATA 未定義時に相対パスのキャッシュを作らない
    assert "[Environment]::GetFolderPath('LocalApplicationData')" in cache


def test_oh_my_posh_init_is_not_cached():
    """oh-my-posh はテーマ設定をセッション ID に紐付けるため init はキャッシュ不可。

    キャッシュした init を別セッションで読み込むと、oh-my-posh が採番していない
    ID になり設定を引けず、既定テーマに戻る。実際のテーマは
    test_powershell_interactive.py::test_deployed_profile_in_interactive_terminal
    がレンダリング結果で検証する。
    """
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")

    assert "POSH_SESSION_ID" not in profile + cache
    assert "function Get-CachedInitScript" in cache
    assert "-Name 'oh-my-posh'" not in profile
    assert profile.count("Get-CachedInitScript -Name") == 1


def test_cached_init_scripts_have_a_direct_fallback():
    """キャッシュ本体が掴まれていても dot-source は失敗する。退避経路を持つ。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

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
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

    assert "$argument.EndsWith('.ps1', [StringComparison]::OrdinalIgnoreCase)" in profile


def test_powershell_path_updates_are_idempotent():
    """mise の activate は毎回 PATH を先頭へ足すため、重複の除去が必要。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

    assert "function Add-EnvPathEntry" in profile
    assert "function Remove-DuplicateEnvPathEntry" in profile
    assert "$env:Path +=" not in profile


def test_pbcopy_forwards_pipeline_input():
    """エイリアスと違い、関数は標準入力を子プロセスへ引き継がない。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

    assert "function pbcopy { $input | clip.exe }" in profile


def test_copilot_function_sets_agent_env_and_restores_it():
    """git が入力待ちにならない既定値を、未設定のときだけ入れて終了後に戻す。"""
    import shutil
    import subprocess

    import pytest

    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        pytest.skip("chezmoi が無い")
    source = ROOT / "home/dot_config/powershell/profile.ps1.tmpl"
    raw = source.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM が無い"

    rendered = subprocess.run(
        [chezmoi, "--source", str(ROOT / "home"), "execute-template"],
        input=raw.decode("utf-8-sig"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout

    # [agent_env] は値が単純な文字列なので、テンプレート記法を含まない先頭付近から読む
    common = (ROOT / "home/dot_config/agents/common.toml.tmpl").read_text(encoding="utf-8")
    section = common.split("[agent_env]\n", 1)[1].split("\n[", 1)[0]
    agent_env = dict(re.findall(r'^(\w+) = "([^"]*)"$', section, re.MULTILINE))
    assert agent_env, "[agent_env] が読めない"

    head, tail = rendered.split(INTERACTIVE_GUARD, 1)
    assert "function copilot" not in head, "対話判定より前に置かない"
    function = tail.split("function copilot {", 1)[1].split("\n}\n", 1)[0]
    for name, value in agent_env.items():
        assert f"'{name}' = '{value}'" in function
    assert "Get-Command copilot -CommandType Application" in function
    # 未設定のものだけを入れ、入れたものだけを finally で消す
    assert "$null -eq [Environment]::GetEnvironmentVariable($name)" in function
    finally_body = function.split("} finally {", 1)[1]
    assert "SetEnvironmentVariable($name, [NullString]::Value)" in finally_body
    assert "$MyInvocation.ExpectingInput" in function


def test_powershell_init_cache_is_keyed_on_the_executable():
    """ツールを更新したらキャッシュを作り直す。"""
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")

    assert "$executable.FullName" in cache
    assert "$executable.Length" in cache
    assert "$executable.LastWriteTimeUtc.Ticks" in cache


def test_fzf_key_handlers_are_registered_from_a_single_place():
    """OnIdle の登録はプロファイル側 1 箇所に集約する。"""
    fzf = (ROOT / "home/dot_config/powershell/commands/fzf.ps1").read_text(encoding="utf-8-sig")
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")
    cache = (ROOT / "home/dot_config/powershell/cache.ps1").read_text(encoding="utf-8-sig")

    assert "Register-EngineEvent" not in fzf
    assert "function Register-FzfKeyHandler" in fzf
    assert profile.count("Register-EngineEvent") == 1
    assert "Register-FzfKeyHandler" in profile
    # 失敗を握り潰さない
    assert "-ErrorAction SilentlyContinue" not in profile + cache


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
    # Documents 配下のローダーと同じ本文を書く
    assert PROFILE_LOADER_INCLUDE in script
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
    template = (ROOT / "home/.chezmoitemplates/powershell/git-config-env.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "Env:GIT_CONFIG" not in template
    assert "Get-ChildItem Env:" not in strip_comments(template)
    assert "$gitConfigKey -eq 'core.fsmonitor'" in template
    assert "$gitConfigValue -eq ''" in template
    assert "[Environment]::SetEnvironmentVariable(\"GIT_CONFIG_VALUE_$i\", 'false')" in template
    assert "'^GIT_CONFIG_(COUNT|KEY_\\d+|VALUE_\\d+)$'" in template


def test_windows_terminal_settings_are_managed_only_by_the_modify_script():
    """341 (json.load で読み直して書く) は廃止した。コメント入りの settings.json で失敗し、既定設定を消すため。"""
    assert not (ROOT / "home/.chezmoiscripts/300_windows/run_after_341_terminal.py.tmpl").exists()
    assert not (ROOT / "config/windows/terminal.json").exists()


def test_standalone_windows_installers_use_supported_winget_detection():
    develop = (ROOT / "scripts/windows/develop.ps1").read_text(encoding="utf-8-sig")
    cuda = (ROOT / "scripts/windows/cuda.ps1").read_text(encoding="utf-8-sig")

    assert "--output json" not in develop
    assert "--output json" not in cuda
    assert "Nvidia.GeForceNow" not in develop
    assert "Nvidia.GeForceNow" not in cuda


def test_agent_cli_installer_uses_official_windows_channels():
    script = (
        ROOT
        / "home"
        / ".chezmoiscripts"
        / "300_windows"
        / "310_packages"
        / "run_onchange_after_314_agent_cli.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    # Windows では公式が手段を分ける: install.ps1 / winget / npm
    assert "https://claude.ai/install.ps1" in script
    assert "winget install --id GitHub.Copilot --exact" in script
    assert "--allow-scripts='@opencode/cli' '@opencode/cli'" in script
    # pi の install.ps1 は Read-Host で確認を聞く (apply では答えられない) ので npm で入れる
    assert "npm install -g --ignore-scripts '@earendil-works/pi-coding-agent'" in script
    assert "pi.dev/install.ps1" not in script
    # install.sh は Windows を拒否するので使わない
    assert "claude.ai/install.sh" not in script
    # 既に入っている CLI は触らない
    assert script.count("Test-CliInstalled '") == 4
    # winget / npm の失敗を握り潰さない
    assert script.count("$LASTEXITCODE -ne 0") == 3


def test_chocolatey_setup_supports_v1_and_v2_listing():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    assert "winget install" in script and "Chocolatey.Chocolatey" in script
    assert "community.chocolatey.org/install.ps1" not in script

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


# PowerShell の出力は UTF-8 とは限らない (Windows PowerShell 5.1 は OEM コードページ)
ENCODING_EXEMPT = {"test/test_powershell_interactive.py"}


def test_subprocess_text_mode_specifies_encoding():
    """テストの subprocess は text=True なら encoding も明示する。

    省くと英語版 Windows の既定 (cp1252) で chezmoi の日本語出力を読んで失敗し、
    終了コード 0 のまま stdout が None になる。
    """
    missing = []
    for path in sorted((ROOT / "test").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ENCODING_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name not in {"run", "check_output", "Popen"}:
                continue
            keywords = {kw.arg for kw in node.keywords}
            if keywords & {"text", "universal_newlines"} and "encoding" not in keywords:
                missing.append(f"{rel}:{node.lineno}")
    assert not missing, missing


MACHINE_WINGET_IDS = [
    "Google.Chrome",
    "Google.JapaneseIME",
    "7zip.7zip",
    "SourceFoundry.HackFonts",
    "Python.Launcher",
    "Apple.iTunes",
    "Google.GoogleDrive",
    "Dropbox.Dropbox",
    "Ditto.Ditto",
    "Tailscale.Tailscale",
    "Valve.Steam",
    "Wacom.WacomTabletDriver",
]


def test_machine_only_winget_packages_are_installed_by_the_admin_step():
    admin = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")
    winget = (
        ROOT / "home/.chezmoiscripts/300_windows/310_packages/run_once_before_310_winget.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")

    for package_id in MACHINE_WINGET_IDS:
        # UAC を出すものは 309 に 1 回だけ。310 に残すと個別に UAC が出る
        assert f"Id = '{package_id}'" in admin, package_id
        assert f"winst {package_id}" not in winget, package_id
    # マニフェストが scope を宣言していない MSI に --scope を付けると 'No applicable installer' になる
    assert "Id = 'Python.Launcher'; Scope = ''" in admin
    # user scope で入る (UAC なし) ものは 310 に残す
    for package_id in ("Git.Git", "OpenJS.NodeJS", "Microsoft.PowerToys", "Discord.Discord"):
        assert f"winst {package_id}" in winget, package_id
        assert package_id not in admin, package_id


def test_admin_setup_enables_openssh_server_without_opening_public():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    assert "'OpenSSHServer'" in script
    assert "Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'" in script
    assert "Set-Service -Name sshd -StartupType Automatic" in script
    # 既定の規則は Profile=Any (Public を含む) なので Domain / Private に絞る
    assert "-Profile Domain, Private -Enabled True" in script
    assert "-PolicyStore ActiveStore" in script
    # applejxd の機械だけ
    assert "$SshdWanted = $true" in script and "$SshdWanted = $false" in script


def test_admin_setup_points_sshd_at_a_stable_pwsh_path():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    # MSIX の pwsh は更新のたびにパスが変わり、sshd のログインが全部失敗するので、固定パスの MSI を使う
    assert "'PowerShellMsi'" in script
    assert "InstallerType = 'wix'" in script and "Force = $true" in script
    assert "'--installer-type'" in script and "'--force'" in script
    assert "'SshDefaultShell'" in script
    assert "-Name DefaultShell" in script
    # 無いシェルを指さない (ログイン不能になる)
    assert "not found; install PowerShell 7 (MSI) first" in script
    # 一発実行でも既定の -c のまま使う (DefaultShellCommandOption は変えない)
    assert "DefaultShellCommandOption" not in script


def test_power_settings_are_applied_every_run_and_never_sleep_on_ac():
    script = (ROOT / "home/.chezmoiscripts/300_windows/run_after_331_power.ps1").read_text(
        encoding="utf-8-sig"
    )

    # 毎回明示的に当てる (run_once だと後から戻されても直らない)
    assert not (ROOT / "home/.chezmoiscripts/300_windows/run_once_after_331_power.ps1").exists()
    assert "Set-PowerValue SUB_SLEEP STANDBYIDLE -Ac 0 -Dc 600" in script
    assert "Set-PowerValue SUB_SLEEP HIBERNATEIDLE -Ac 0 -Dc 0" in script
    # AC は蓋を閉じても何もしない、バッテリーはスリープ
    assert "Set-PowerValue SUB_BUTTONS LIDACTION -Ac 0 -Dc 1 -Optional" in script
    assert "7bc4a2f9-d8fc-4469-b07b-33eb785aaca0 -Ac 0 -Optional" in script
    assert "powercfg /setactive SCHEME_CURRENT" in script


def test_powershell_path_expands_unexpanded_variables_for_ssh_sessions():
    """sshd 経由のセッションは PATH の %VAR% を展開せず渡す。WindowsApps のエイリアスが引けなくなる。"""
    profile = (ROOT / "home/dot_config/powershell/profile.ps1.tmpl").read_text(encoding="utf-8-sig")

    assert "[System.Environment]::ExpandEnvironmentVariables($_)" in profile


def test_7zip_registers_a_selectable_default_app_instead_of_setting_userchoice():
    script = (ROOT / "home/.chezmoiscripts/300_windows/320_regkey/run_once_after_322_7zip.ps1").read_text(
        encoding="utf-8-sig"
    )

    # UserChoice は保護されていて書けない。既定アプリの一覧に出る形 (ProgID + Capabilities) で登録する
    assert "UserChoice" not in script.replace("UserChoice is protected", "")
    assert "RegisteredApplications" in script
    assert "OpenWithProgids" in script
    assert "FileAssociations" in script
    assert '7zG.exe" x "%1" -o*' in script
    # 値が揃っていれば何もしない (冪等)
    assert "$pending.Count -eq 0" in script


def test_shell_defaults_set_execution_policy_and_default_terminal_in_hkcu_only():
    script = (ROOT / "home/.chezmoiscripts/300_windows/320_regkey/run_once_after_323_shell_defaults.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "HKLM:\SOFTWARE\Policies" in script  # Group Policy は読むだけ
    assert "Set-ExecutionPolicy" not in script  # モジュールに依存せず HKCU へ直接書く
    assert "'RemoteSigned', 'Unrestricted', 'Bypass'" in script  # 緩い設定は下げない
    assert "{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}" in script
    assert "{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}" in script
    # HKLM への書き込みは無い
    assert "New-ItemProperty -LiteralPath $Key" in script
    assert "Set-RegistryString HKLM" not in script


def test_suggestions_are_turned_off_every_apply():
    hkcu = (ROOT / "home/.chezmoiscripts/300_windows/320_regkey/run_after_324_suggestions.ps1").read_text(
        encoding="utf-8-sig"
    )

    # 更新で戻されるので毎回当てる。値が 0 なら何もしない。書けない値は警告して続ける
    assert "SubscribedContent-338389Enabled" in hkcu and "SystemPaneSuggestionsEnabled" in hkcu
    assert "Start_IrisRecommendations" in hkcu and "ShowSyncProviderNotifications" in hkcu
    assert "if ($current -eq 0) { continue }" in hkcu
    assert "Windows refused to write" in hkcu
    # ウィジェットは HKCU (TaskbarDa) も HKLM のポリシーも書けなかったので、自動化しない
    assert "TaskbarDa" not in hkcu.replace("(weather)", "")
    assert "AllowNewsAndInterests" not in ADMIN_SCRIPT.read_text(encoding="utf-8-sig")


def test_admin_setup_enables_the_builtin_sudo_safely_for_the_personal_machine_only():
    script = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")

    assert "'Sudo'" in script
    # applejxd のときだけ ($SudoWanted は applejxd のブロックで $true)
    assert script.index("$SudoWanted = $true") < script.index("{{- else }}") < script.index("$SudoWanted = $false")
    # 公式の手順で、既定の forceNewWindow (sudo のたびに UAC。normal / disableInput は選ばない)
    assert "config --enable forceNewWindow" in script
    assert "--enable normal" not in script and "--enable disableInput" not in script
    # 24H2 より前 (sudo.exe が無い) とポリシーで無効に固定された機械は飛ばす。有効な方式は選び直さない
    assert "Test-SudoSupported" in script and "Test-SudoAllowedByPolicy" in script
    assert "[int]$value -ge 1" in script
    assert "Microsoft\Windows\CurrentVersion\Sudo" in script


def test_power_settings_are_read_back_and_a_mismatch_only_warns():
    script = (ROOT / "home/.chezmoiscripts/300_windows/run_after_331_power.ps1").read_text(encoding="utf-8-sig")

    # 設定した値を powercfg /q で読み取って確かめる (表示の言語に依らず、末尾の 2 つの 0x… を AC・DC とする)
    assert "function Get-PowerValue" in script and "0x[0-9A-Fa-f]{8}" in script
    assert "$script:Expected" in script
    # 上書きされていても apply は止めない (警告だけ)。設定が無い機種の任意の項目は確かめない
    assert "Write-Warning ('Power settings differ" in script
    assert "if (-not $e.Optional)" in script
    assert script.rindex("Write-Warning ('Power settings differ") > script.rindex("powercfg /setactive")


HOST_LIMITED = {
    "StreamDeck": "Elgato.StreamDeck",
    "Wacom": "Wacom.WacomTabletDriver",
    "Steam": "Valve.Steam",
    "iTunes": "Apple.iTunes",
}


def test_device_and_usage_specific_packages_are_limited_to_the_named_host():
    admin = ADMIN_SCRIPT.read_text(encoding="utf-8-sig")
    winget = (
        ROOT / "home/.chezmoiscripts/300_windows/310_packages/run_once_before_310_winget.ps1.tmpl"
    ).read_text(encoding="utf-8-sig")
    allowed = admin.index("$AllowedTargets")
    host_gate = admin.rindex("{{- if eq (lower .chezmoi.hostname)", 0, allowed)
    # applejxd の条件の内側で、さらに hostname で絞る。ゲートの終わりまでに入れ子が閉じる
    assert admin.rindex("regexMatch", 0, host_gate) < host_gate
    block_end = admin.index("{{- end }}", host_gate)
    block = admin[host_gate:block_end]

    for key, package_id in HOST_LIMITED.items():
        assert f"'{key}'" in block and f"Id = '{package_id}'; Scope = 'machine'" in block, key
        assert admin.count(f"Id = '{package_id}'") == 1, key  # ほかの場所に重ねて書かない
        assert package_id not in winget, key
