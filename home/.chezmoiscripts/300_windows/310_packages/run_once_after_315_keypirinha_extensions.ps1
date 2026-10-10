<#
  .SYNOPSIS
    Download Keypirinha extensions for the current user
  .DESCRIPTION
    Runs unelevated so files land in the signed-in user's profile (the elevated
    account in 309_admin may be a different user). Existing files are never
    overwritten. Rerun after a failure fetches only the missing ones.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run as a normal user: extensions must go to the signed-in user profile, not an admin profile.'
}

# GitHub API requires TLS 1.2 (PowerShell 5.1 default may not enable it).
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$installDir = Join-Path $env:APPDATA 'Keypirinha\InstalledPackages'
if (-not (Test-Path -LiteralPath $installDir)) {
  New-Item -Path $installDir -ItemType Directory | Out-Null
}

function Install-Release {
  param([string]$Repo, [string]$FileName)
  $filePath = Join-Path $installDir $FileName
  if (Test-Path -LiteralPath $filePath -PathType Leaf) { return }

  $release = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/releases/latest"
  $asset = @($release.assets | Where-Object { $_.name -eq $FileName })
  if ($asset.Count -ne 1) {
    throw "Expected one release asset named $FileName in $Repo, found $($asset.Count)"
  }
  # Download to a temp name, then move, so a partial file is never mistaken for installed.
  $tmp = "$filePath.download"
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $asset[0].browser_download_url -OutFile $tmp
    Move-Item -LiteralPath $tmp -Destination $filePath
  } finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
  }
  Write-Host "Installed $FileName"
}

Install-Release 'Fuhrmann/keypirinha-url-shortener' 'URLShortener.keypirinha-package'
Install-Release 'psistorm/keypirinha-systemcommands' 'SystemCommands.keypirinha-package'
Install-Release 'clinden/keypirinha-colorpicker' 'ColorPicker.keypirinha-package'
# Clipboard Manager
Install-Release 'tuteken/Keypirinha-Plugin-Ditto' 'Ditto.keypirinha-package'
# Default Windows Apps
Install-Release 'ueffel/Keypirinha-WindowsApps' 'WindowsApps.keypirinha-package'
# Windows Terminal Profiles
Install-Release 'fran-f/keypirinha-terminal-profiles' 'Terminal-Profiles.keypirinha-package'
# Search by abbrev
Install-Release 'bantya/Keypirinha-EasySearch' 'EasySearch.keypirinha-package'
# Execute commands from >
Install-Release 'bantya/Keypirinha-Command' 'Command.keypirinha-package'
# Snippets moved to https://codeberg.org/skullzy/keypirinha-snippets
