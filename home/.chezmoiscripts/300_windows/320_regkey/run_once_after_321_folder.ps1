<#
  .SYNOPSIS
    Set Explorer / Folder Options (HKCU) and restart Explorer.

  .NOTES
    - Standard DWORD settings are done via PowerShell registry provider.
    - The classic context menu tweak uses reg.exe for the unnamed default value stability.
#>

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

$needsRestart = $false
foreach ($s in $settings) {
  if (-not (Test-Path -LiteralPath $s.Path)) {
    $needsRestart = $true
    continue
  }
  $currentValue = Get-ItemPropertyValue -LiteralPath $s.Path -Name $s.Name -ErrorAction SilentlyContinue
  if ($currentValue -ne $s.Value) {
    $needsRestart = $true
  }
}

# --- Classic context menu (unnamed default value) ---
$clsid = '{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}'
$inproc = "HKCU:\Software\Classes\CLSID\$clsid\InprocServer32"
$inprocItem = Get-Item -LiteralPath $inproc -ErrorAction SilentlyContinue
if ($null -eq $inprocItem -or $inprocItem.GetValue('') -ne '') {
  $needsRestart = $true
}

if (-not $needsRestart) {
  exit 0
}

foreach ($s in $settings) {
  if (-not (Test-Path -LiteralPath $s.Path)) {
    New-Item -Path $s.Path -Force | Out-Null
  }
  New-ItemProperty -Path $s.Path -Name $s.Name -PropertyType DWord -Value $s.Value -Force | Out-Null
}
if (-not (Test-Path -LiteralPath $inproc)) {
  New-Item -Path $inproc -Force | Out-Null
}
Set-Item -LiteralPath $inproc -Value ''

Stop-Process -Name explorer -Force
Start-Process explorer.exe
