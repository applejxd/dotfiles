<#
  .SYNOPSIS
    Set Explorer / Folder Options (HKCU) and restart Explorer.

  .NOTES
    - Standard DWORD settings are done via PowerShell registry provider.
    - The classic context menu tweak uses reg.exe for the unnamed default value stability.
#>

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

    Start-Process -Wait -FilePath PowerShell.exe -Verb Runas -ArgumentList $allArguments
    Exit
  }
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$regRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer"

# --- Folder/Explorer options (DWORD) ---
$settings = @(
  @{ Path = "$regRoot\Advanced";     Name = "HideFileExt"; Value = 0; Comment = "拡張子表示" }
  @{ Path = "$regRoot\Advanced";     Name = "Hidden";      Value = 1; Comment = "隠しファイル表示" }
  @{ Path = "$regRoot\CabinetState"; Name = "FullPath";    Value = 1; Comment = "タイトルバーにフルパス表示" }
  @{ Path = "$regRoot\Advanced";     Name = "LaunchTo";    Value = 1; Comment = "エクスプローラーの開始場所: PC" }
)

foreach ($s in $settings) {
  New-Item -Path $s.Path -Force | Out-Null

  # 型を明示して作る（既に存在する場合も Force で上書き）
  New-ItemProperty -Path $s.Path -Name $s.Name -PropertyType DWord -Value $s.Value -Force | Out-Null
}

# --- Classic context menu (unnamed default value) ---
$clsid = '{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}'
$inproc = "HKCU\Software\Classes\CLSID\$clsid\InprocServer32"
& reg.exe add $inproc /f /ve | Out-Null

# --- Apply by restarting Explorer ---
Stop-Process -Name explorer -Force
Start-Process explorer.exe
