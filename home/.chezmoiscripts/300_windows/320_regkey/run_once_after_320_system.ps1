<#
  .SYNOPSIS
    enable long path support
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$reg_root = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
$longPathsEnabled = Get-ItemPropertyValue -LiteralPath $reg_root -Name LongPathsEnabled -ErrorAction Ignore
if ($longPathsEnabled -eq 1) {
  exit 0
}

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
      throw "Elevated system configuration failed with exit code $($process.ExitCode)"
    }
    Exit 0
  }
}

Set-ItemProperty "$reg_root" -Name 'LongPathsEnabled' -Value 1
