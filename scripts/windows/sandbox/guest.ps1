<#
  .SYNOPSIS
    Windows Sandbox の中で、まっさらな状態から chezmoi を導入して pi が起動するまでを検証する
  .DESCRIPTION
    launch.ps1 が生成した .wsb から自動で実行される。結果はホストの .tmp/sandbox-result/ に出る。
    手順は README の Windows 導入と同じ (winget → chezmoi init --apply)。
    see docs/spec/development.md#windows-sandbox-でのクリーン導入の検証
#>

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
  & $Body
  Write-Host "=== $Name (exit: $LASTEXITCODE) ==="
}

# winget (App Installer) は Sandbox に無いことがある
Step 'winget bootstrap' {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Install-PackageProvider -Name NuGet -Force | Out-Null
    Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery | Out-Null
    Repair-WinGetPackageManager -AllUsers
  }
  $env:Path += ";$env:LOCALAPPDATA\Microsoft\WindowsApps"
  winget --version
}

Step 'README: winget install' {
  winget install Python.Python.3.12 Git.Git twpayne.chezmoi --exact --silent --disable-interactivity `
      --accept-package-agreements --accept-source-agreements
}
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
Update-PathFromRegistry

Step 'chezmoi init --apply' {
  chezmoi init applejxd --apply
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
$versions = @{}
foreach ($pair in @('node --version', 'pi --version')) {
  $versions[$pair] = try { (& cmd /c "$pair 2>&1") -join ' ' } catch { $_.Exception.Message }
}
$withProfile = try {
  & pwsh -NoLogo -Command 'pi --version 2>&1; $LASTEXITCODE' 2>&1 | Out-String
} catch { $_.Exception.Message }

$lines = @('# Sandbox 検証結果', '', ($report | Format-Table -AutoSize | Out-String))
$lines += $versions.GetEnumerator() | ForEach-Object { "$($_.Key): $($_.Value)" }
$lines += "pwsh (プロファイル読み込み) pi --version: $withProfile"
$lines += "User PATH に npm: " + (([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') -contains "$env:APPDATA\npm")
$lines += "result: " + $(if (($report | Where-Object Command -eq 'pi').Found) { 'PASS (pi found)' } else { 'FAIL (pi not found)' })
$lines | Set-Content -Path (Join-Path $ResultDir 'summary.txt') -Encoding UTF8
$lines | Write-Host

Stop-Transcript | Out-Null
