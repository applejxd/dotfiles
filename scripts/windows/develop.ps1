<#
  .SYNOPSIS
    Install development tools
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Self-elevate the script if required
# see https://www.chezmoi.io/user-guide/machines/windows/#run-a-powershell-script-as-admin-on-windows
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()  # Get current user identity
$principal = [Security.Principal.WindowsPrincipal] $identity  # Create a principal object
$adminRole = [Security.Principal.WindowsBuiltInRole] 'Administrator' # Define the admin role
$isElevated = $principal.IsInRole($adminRole) # Check if the user has the admin role
if (-not $isElevated) {
  $buildNumber = [int](Get-CimInstance -Class Win32_OperatingSystem | Select-Object -ExpandProperty BuildNumber)
  if ($buildNumber -ge 6000) {  # Windows Vista / Windows Server 2008 or later
    $scriptPath = $MyInvocation.MyCommand.Path
    $baseArguments = @('-File', $scriptPath)
    $allArguments = $baseArguments + $MyInvocation.UnboundArguments

    $process = Start-Process -Wait -PassThru -FilePath PowerShell.exe -Verb Runas -ArgumentList $allArguments
    if ($process.ExitCode -ne 0) {
      throw "Elevated development setup failed with exit code $($process.ExitCode)"
    }
    Exit 0
  }
}

Function winst {
  param(
    [Parameter(Mandatory,Position=0)][string]$PackageId,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$AdditionalArgs
  )
  if (-not (Get-Command winget -EA SilentlyContinue)) { throw "winget (App Installer) not found" }

  & winget list --id $PackageId --exact --disable-interactivity `
      --accept-source-agreements | Out-Null
  $installed = $LASTEXITCODE -eq 0

  if (-not $installed) {
    Write-Host "Installing $PackageId..."
    & winget @('install','--id',$PackageId,'--exact','--silent','--disable-interactivity',
               '--accept-package-agreements','--accept-source-agreements') $AdditionalArgs
    if ($LASTEXITCODE -ne 0) { throw "winget install failed: $LASTEXITCODE" }
  } else {
    Write-Host "$PackageId is already installed."
  }
}

#-------#
# Tools #
#-------#

# X11 forwarding
winst marha.VcXsrv

# Docker
winst hadolint.hadolint
winst Docker.DockerDesktop

# C++
winst Microsoft.VisualStudio.2022.Community
winst Kitware.CMake

# Python
winst Python.Python.3.9
winst Python.Python.3.10
winst Python.Python.3.11
winst Python.Python.3.12

# GPU development toolkit
winst Nvidia.CUDA
