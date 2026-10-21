<#
  .SYNOPSIS
    TEMPORARY: pwsh 7.6.x の更新通知による起動クラッシュを避ける
  .DESCRIPTION
    TEMP-REMOVE: 理由・出典・撤去の条件は
    docs/spec/temporary-workarounds.md#pwsh-76x-の更新通知クラッシュ
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([Environment]::GetEnvironmentVariable('POWERSHELL_UPDATECHECK', 'User') -ne 'Off') {
  [Environment]::SetEnvironmentVariable('POWERSHELL_UPDATECHECK', 'Off', 'User')
}
