#Requires -RunAsAdministrator

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rules = @(
    @{ Name = 'OpenSSH-Server-In-TCP'; DisplayName = 'OpenSSH Server (Windows)'; Port = 22 }
    @{ Name = 'WSL-SSH-In-TCP'; DisplayName = 'OpenSSH Server (WSL)'; Port = 50022 }
    @{ Name = 'WSL-RDP-In-TCP'; DisplayName = 'xrdp (WSL)'; Port = 53389 }
)

foreach ($rule in $rules) {
    if (-not (Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name $rule.Name -DisplayName $rule.DisplayName `
            -Enabled True -Direction Inbound -Protocol TCP -Action Allow `
            -LocalPort $rule.Port | Out-Null
    }
}
