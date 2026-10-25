<#
  .SYNOPSIS
    Windows Sandbox の中で、まっさらな状態から chezmoi を導入して pi が起動するまでを検証する
  .DESCRIPTION
    launch.ps1 が生成した .wsb から自動で実行される。結果はホストの .tmp/sandbox-result/ に出る。
    手順は README の Windows 導入と同じ (winget → chezmoi init --apply)。
    see docs/spec/development.md#windows-sandbox-でのクリーン導入の検証
#>

# -LegacyNode: 制約のある環境の再現。古い winget 版 Node.js (Machine PATH) を先に入れてから導入する
param([switch]$LegacyNode)

$ErrorActionPreference = 'Continue'
$ResultDir = 'C:\result'
New-Item -ItemType Directory -Force -Path $ResultDir | Out-Null
Start-Transcript -Path (Join-Path $ResultDir 'transcript.log') -Force | Out-Null

function Update-PathFromRegistry {
  # 新しいシェルを開いたときの PATH (レジストリ由来のみ) を再現する
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
      [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Step([string]$Name, [scriptblock]$Body) {
  Write-Host "`n=== $Name ==="
  # ネイティブコマンドの出力は Out-Host を通さないと transcript に残らない
  & $Body 2>&1 | Out-Host
  Write-Host "=== $Name (exit: $LASTEXITCODE) ==="
}

# winget (App Installer) は Sandbox に無い。Repair-WinGetPackageManager は黙って失敗したので、
# 公式の msixbundle と依存パッケージを直接入れる
# Python などの小さなファイルを大量に書くインストーラーが、Sandbox ではスキャンで極端に遅い (Python 3.12 が 10 分超)
try { Set-MpPreference -DisableRealtimeMonitoring $true } catch { Write-Host "Defender: $($_.Exception.Message)" }

Step 'winget bootstrap' {
  $env:Path += ";$env:LOCALAPPDATA\Microsoft\WindowsApps"
  $hasWinget = $false
  try { winget --version | Out-Host; $hasWinget = ($LASTEXITCODE -eq 0) } catch { }
  if (-not $hasWinget) {
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $dir = Join-Path $env:TEMP 'winget-bootstrap'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    # winget-cli の公式リリースが依存パッケージ一式 (VCLibs / UI.Xaml / WindowsAppRuntime) を同梱している
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/microsoft/winget-cli/releases/latest' -UseBasicParsing
    foreach ($assetName in 'DesktopAppInstaller_Dependencies.zip', 'Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle') {
      $asset = $release.assets | Where-Object name -eq $assetName
      Invoke-WebRequest -Uri $asset.browser_download_url -OutFile (Join-Path $dir $assetName) -UseBasicParsing
    }
    Expand-Archive -Path (Join-Path $dir 'DesktopAppInstaller_Dependencies.zip') -DestinationPath (Join-Path $dir 'deps') -Force
    $deps = @(Get-ChildItem -Path (Join-Path $dir 'deps\x64') -Filter *.appx | ForEach-Object FullName)
    try {
      Add-AppxPackage -Path (Join-Path $dir 'Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle') -DependencyPath $deps -ErrorAction Stop
    } catch {
      $_.Exception.Message | Out-Host
      # 失敗の詳細 (ActivityId のログ)
      if ($_.Exception.Message -match '\[ActivityId\]\s+([0-9a-f-]+)') { Get-AppPackageLog -ActivityID $Matches[1] | Out-Host }
    }
    winget --version
  }
}

# Sandbox では msstore ソースが Rest API エラー (0x8a15003b) になり、--source 無しの install が全て失敗する。
# 今回の対象は applejxd 以外で、msstore 専用パッケージは使わないので外す
Step 'winget: msstore を外す' {
  winget source remove --name msstore --disable-interactivity
  winget source update --disable-interactivity
}

# 1 パッケージずつ、出力を結果フォルダの winget-<id>.log へ随時書きながら実行する。
# 戻ってこないインストーラーで全体が止まらないよう、タイムアウトで打ち切って状況を記録する。
function Install-WithWinget([string]$Id, [int]$TimeoutSec = 1800, [string[]]$ExtraArgs = @()) {
  Write-Host "`n=== winget install $Id ==="
  $log = Join-Path $ResultDir ("winget-$Id.log")
  $arguments = @('install', '--id', $Id, '--exact', '--silent', '--disable-interactivity',
      '--accept-package-agreements', '--accept-source-agreements', '--verbose-logs') + $ExtraArgs
  $process = Start-Process -FilePath winget -ArgumentList $arguments -PassThru -NoNewWindow `
      -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  if (-not $process.WaitForExit($TimeoutSec * 1000)) {
    Write-Host "TIMEOUT ($TimeoutSec s): $Id"
    Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CommandLine |
        Out-String -Width 300 | Set-Content (Join-Path $ResultDir "processes-$Id.txt")
    # winget だけ止めるとインストーラーが残り、Windows Installer を占有して後続が 1618 になる
    & taskkill.exe /F /T /PID $process.Id | Out-Null
    $diag = Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\DiagOutputDir'
    Copy-Item -Path (Join-Path $diag '*') -Destination $ResultDir -Force -ErrorAction SilentlyContinue
  } else {
    Write-Host "exit: $($process.ExitCode)"
  }
  Get-Content $log, "$log.err" -ErrorAction SilentlyContinue | Out-Host
}

if ($LegacyNode) {
  # 古い Node.js を Machine PATH に置く。winget は古い版 (24.x より前) を公開していないので、
  # nodejs.org の MSI (winget と同じインストーラー) を直接入れる。20.x は pi の要件 (22.19 以上) を満たさない
  Write-Host "`n=== legacy node (MSI 20.18.0) ==="
  $msi = Join-Path $env:TEMP 'node-legacy.msi'
  $ProgressPreference = 'SilentlyContinue'
  Invoke-WebRequest -Uri 'https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi' -OutFile $msi -UseBasicParsing
  $p = Start-Process msiexec.exe -ArgumentList @('/i', $msi, '/qn', '/norestart') -Wait -PassThru
  Write-Host "msiexec exit: $($p.ExitCode)"
  Update-PathFromRegistry
  Write-Host ("legacy node: " + (& cmd /c 'node --version 2>&1'))
}

Write-Host "`n=== README: winget install ==="
foreach ($id in 'Python.Python.3.12', 'Git.Git', 'twpayne.chezmoi') { Install-WithWinget $id }
Update-PathFromRegistry

Step 'chezmoi init --apply' {
  # 途中経過を見られるよう、出力を随時ファイルへも書く (transcript は最後にまとめて書かれる)
  chezmoi init applejxd --apply 2>&1 | Tee-Object -FilePath (Join-Path $ResultDir 'chezmoi-apply.log')
}

# ----- 検証: 新しいシェル相当の PATH で起動できるか ----- #
Update-PathFromRegistry
$commands = 'node', 'npm', 'mise', 'uv', 'fzf', 'jq', 'pi', 'opencode', 'copilot'
$report = foreach ($name in $commands) {
  $found = @(Get-Command $name -All -ErrorAction SilentlyContinue)
  [pscustomobject]@{
    Command = $name
    Found   = $found.Count -gt 0
    Source  = ($found | Select-Object -First 1 -ExpandProperty Source)
  }
}
# 実際に起動して判定する (見つかるだけでは足りない)。プロファイルなしの cmd と、プロファイルを読む pwsh の両方
$cmdOut = (& cmd /c 'pi --version 2>&1') -join ' '
$cmdCode = $LASTEXITCODE
$pwshOut = (& pwsh -NoLogo -Command 'pi --version 2>&1; exit $LASTEXITCODE' 2>&1 | Out-String).Trim()
$pwshCode = $LASTEXITCODE
$pwshNode = (& pwsh -NoLogo -Command '(Get-Command node -ErrorAction SilentlyContinue).Source; node --version' 2>&1 | Out-String).Trim()
$cmdNode = (& cmd /c 'where node 2>&1 & node --version 2>&1') -join ' | '
$isVersion = { param($s) $s -match '^\s*(\d+\.){2}\d+\s*$' }

# pi の実体の場所 (npm の global prefix がどこかを見る)
$piFiles = @(Get-ChildItem -Path $env:USERPROFILE -Recurse -Filter 'pi.cmd' -ErrorAction SilentlyContinue | ForEach-Object FullName)
$npmPrefix = try { & cmd /c 'mise exec node -- npm config get prefix 2>&1' } catch { $_.Exception.Message }

$lines = @('# Sandbox 検証結果', '', ($report | Format-Table -AutoSize | Out-String))
$lines += "legacy node 先行: $LegacyNode"
$lines += "pwsh (プロファイル読み込み): exit=$pwshCode out=[$pwshOut]"
$lines += "pwsh の node: [$pwshNode]"
$lines += "cmd.exe (プロファイルなし): exit=$cmdCode out=[$cmdOut]"
$lines += "cmd.exe の node: [$cmdNode]"
$lines += "User PATH に npm: " + (([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') -contains "$env:APPDATA\npm")
$lines += "pi.cmd の場所: $($piFiles -join ', ')"
$lines += "mise の node の npm prefix: $npmPrefix"
$pwshOk = ($pwshCode -eq 0) -and (& $isVersion $pwshOut)
$cmdOk = ($cmdCode -eq 0) -and (& $isVersion $cmdOut)
$lines += "cmd.exe: " + $(if ($cmdOk) { 'OK' } else { 'NG (参考。プロファイルなしでは node が PATH に無い)' })
$lines += "result: " + $(if ($pwshOk) { 'PASS (pwsh で pi が起動した)' } else { 'FAIL (pwsh で pi が起動しない)' })
$lines | Set-Content -Path (Join-Path $ResultDir 'summary.txt') -Encoding UTF8
$lines | Write-Host

Stop-Transcript | Out-Null

# 次の launch.ps1 を手で閉じずに実行できるよう、結果を出したら Sandbox を終了する
shutdown.exe /s /t 5 /c "sandbox verification finished"
