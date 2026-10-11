<#
  .SYNOPSIS
    Shell defaults (HKCU): Windows PowerShell 5.1 execution policy and the default terminal app
  .DESCRIPTION
    5.1 ships with the Restricted policy, which blocks the profile (*.ps1) the dotfiles deploy.
    PowerShell 7 already defaults to RemoteSigned, so only 5.1 needs this.
    see docs/spec/structure.md#シェルの既定値
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$policyKey = 'HKCU:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell'
$consoleKey = 'HKCU:\Console\%%Startup'
# Windows Terminal as the console / terminal host (documented GUIDs of the "Default terminal application" setting)
$terminalValues = [ordered]@{
  DelegationConsole  = '{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}'
  DelegationTerminal = '{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}'
}

function Get-RegistryValue {
  param([string]$Key, [string]$Name)
  $item = Get-Item -LiteralPath $Key -ErrorAction Ignore
  if ($null -eq $item) { return $null }
  return $item.GetValue($Name, $null)
}

function Set-RegistryString {
  param([string]$Key, [string]$Name, [string]$Value)
  if (-not (Test-Path -LiteralPath $Key)) {
    New-Item -Path $Key -Force | Out-Null
  }
  New-ItemProperty -LiteralPath $Key -Name $Name -PropertyType String -Value $Value -Force | Out-Null
}

# --- Execution policy (CurrentUser, Windows PowerShell 5.1) ---
# A Group Policy wins over CurrentUser, so leave those machines alone.
$policyManaged = $false
foreach ($gpo in 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell', 'HKCU:\SOFTWARE\Policies\Microsoft\Windows\PowerShell') {
  if ($null -ne (Get-RegistryValue $gpo 'ExecutionPolicy')) { $policyManaged = $true }
}
if ($policyManaged) {
  Write-Warning 'Execution policy is set by Group Policy; skipped.'
} else {
  $current = Get-RegistryValue $policyKey 'ExecutionPolicy'
  # Keep a more permissive policy the user chose
  if ($current -notin @('RemoteSigned', 'Unrestricted', 'Bypass')) {
    Set-RegistryString $policyKey 'ExecutionPolicy' 'RemoteSigned'
    Write-Host 'Set the Windows PowerShell execution policy (CurrentUser) to RemoteSigned.'
  }
}

# --- Default terminal application ---
if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\wt.exe')) {
  foreach ($name in $terminalValues.Keys) {
    if ((Get-RegistryValue $consoleKey $name) -ne $terminalValues[$name]) {
      Set-RegistryString $consoleKey $name $terminalValues[$name]
      Write-Host "Set the default terminal application ($name)."
    }
  }
}
