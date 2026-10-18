<#
  .SYNOPSIS
    mirrored モードの WSL へ、リモートから SSH (50022) できるようにする
  .DESCRIPTION
    mirrored モードでは、WSL の VM への受信を Hyper-V ファイアウォールが止める (既定は Block)。
    標準の Windows ファイアウォールの規則とは別の層なので、WSL の VM 向けの規則を作る。
    規則は Domain / Private のネットワークだけに限定し、Public では開けない。

    -AlsoWindowsFirewall: 標準の Windows ファイアウォールにも同じ規則を作る。
    Hyper-V の規則だけで届かないときの切り分け用 (既定では作らない)。
    see docs/spec/structure.md#wsl
#>

#Requires -RunAsAdministrator

[CmdletBinding()]
param(
    [switch]$AlsoWindowsFirewall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ruleName = 'WSL-SSH-In-TCP'
$displayName = 'OpenSSH Server (WSL)'
$port = 50022
# WSL の VM の作成者 ID (Get-NetFirewallHyperVVMCreator で確認できる)
$wslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

# 毎回作り直す (古い設定が残らないように)
if (Get-NetFirewallHyperVRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallHyperVRule -Name $ruleName
}
New-NetFirewallHyperVRule -Name $ruleName -DisplayName $displayName `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPorts $port `
    -VMCreatorId $wslCreatorId -Profiles Domain, Private -Enabled True | Out-Null
Write-Host "Hyper-V firewall rule '$ruleName' (TCP $port, Domain/Private) is set."

if ($AlsoWindowsFirewall) {
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -Name $ruleName
    }
    New-NetFirewallRule -Name $ruleName -DisplayName $displayName `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
        -LocalPort $port -Profile Domain, Private | Out-Null
    Write-Host "Windows firewall rule '$ruleName' (TCP $port, Domain/Private) is set."
}
