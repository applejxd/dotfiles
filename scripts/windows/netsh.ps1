<#
  .SYNOPSIS
    mirrored モードの WSL へ、LAN から SSH (50022) できるようにする
  .DESCRIPTION
    mirrored モードでは、WSL の VM への受信を Hyper-V ファイアウォール (WSL の VM 向け。既定は
    Block) が止める。標準の Windows ファイアウォールにも規則を作る (単独の必要性は未確定。
    docs/spec/structure.md を参照)。規則は Domain / Private のネットワークだけに限定し、Public では開けない。

    2 つの規則は別の名前にする。同じ名前にすると Remove-NetFirewallRule -Name が
    両方を消し、片方だけを調べる試験が成り立たない (実際に起きた)。

    Tailscale 経由はこの規則では通らない (Wintun のパケットは VM へ転送されない)。
    tailnet からは `tailscale serve` で localhost:50022 へ転送する。
    see docs/spec/structure.md#リモートから-wsl-へ-ssh-する
#>

#Requires -RunAsAdministrator

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$port = 50022
$stdRuleName = 'WSL-SSH-In-TCP'
$hvRuleName = 'WSL-SSH-In-TCP-HyperV'
$displayName = 'OpenSSH Server (WSL)'
# WSL の VM の作成者 ID (Get-NetFirewallHyperVVMCreator で確認できる)
$wslCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

function Wait-Until {
    param([scriptblock]$Condition, [int]$Seconds = 10)
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (& $Condition) { return }
        Start-Sleep -Seconds 1
    }
}

# 毎回作り直す (古い設定が残らないように)。削除は非同期なので、消えるのを待ってから作る
if (Get-NetFirewallHyperVRule -Name $hvRuleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallHyperVRule -Name $hvRuleName
    Wait-Until { -not (Get-NetFirewallHyperVRule -Name $hvRuleName -ErrorAction SilentlyContinue) }
}
for ($attempt = 1; ; $attempt++) {
    try {
        New-NetFirewallHyperVRule -Name $hvRuleName -DisplayName $displayName `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPorts $port `
            -VMCreatorId $wslCreatorId -Profiles Domain, Private -Enabled True -ErrorAction Stop | Out-Null
        break
    } catch {
        if ($attempt -ge 5) { throw }
        Start-Sleep -Seconds 1
    }
}
Write-Host "Hyper-V firewall rule '$hvRuleName' (TCP $port, Domain/Private) is set."

if (Get-NetFirewallRule -Name $stdRuleName -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -Name $stdRuleName
}
New-NetFirewallRule -Name $stdRuleName -DisplayName $displayName `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
    -LocalPort $port -Profile Domain, Private | Out-Null
Write-Host "Windows firewall rule '$stdRuleName' (TCP $port, Domain/Private) is set."
