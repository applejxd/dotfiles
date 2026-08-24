<#
  .SYNOPSIS
    Install Herdr for native Windows
  .DESCRIPTION
    Install the stable Herdr release with the official user-scoped installer
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$installerPath = Join-Path ([System.IO.Path]::GetTempPath()) "herdr-install-$PID.ps1"
$herdrPath = Join-Path $env:LOCALAPPDATA 'Programs\Herdr\bin\herdr.exe'

try {
  Write-Host 'Downloading the Herdr installer...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://herdr.dev/install.ps1' -OutFile $installerPath

  & $installerPath -Channel stable

  if (-not (Test-Path -LiteralPath $herdrPath -PathType Leaf)) {
    throw "Herdr executable was not installed at $herdrPath"
  }

  & $herdrPath --version
  if ($LASTEXITCODE -ne 0) {
    throw "Herdr verification failed with exit code $LASTEXITCODE"
  }
}
finally {
  if (Test-Path -LiteralPath $installerPath) {
    Remove-Item -LiteralPath $installerPath -Force
  }
}
