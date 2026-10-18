<#
  .SYNOPSIS
    mirrored モードの WSL へ、LAN から SSH (50022) できるようにする
  .DESCRIPTION
    mirrored モードでは、WSL の VM への受信を 2 つの層が止める。どちらも規則が要る (実測)。
      1. Hyper-V ファイアウォール (WSL の VM 向け。既定は Block)
      2. 標準の Windows ファイアウォール (これを消すと LAN から届かなくなった)
    規則は Domain / Private のネットワークだけに限定し、Public では開けない。

    Tailscale 経由はこの規則では通らない (Wintun のパケットは VM へ転送されない)。
    tailnet からは `tailscale serve` で localhost:50022 へ転送する。
    see docs/spec/structure.md#リモートから-wsl-へ-ssh-する
#>

#Requires -RunAsAdministrator

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

if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -Name $ruleName
}
New-NetFirewallRule -Name $ruleName -DisplayName $displayName `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
    -LocalPort $port -Profile Domain, Private | Out-Null
Write-Host "Windows firewall rule '$ruleName' (TCP $port, Domain/Private) is set."
