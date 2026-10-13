<#
  .SYNOPSIS
    Windows Sandbox を起動し、chezmoi のクリーン導入を自動で検証する (ホストで実行)
  .DESCRIPTION
    結果は <repo>/.tmp/sandbox-result/summary.txt と transcript.log に出る。
    Sandbox が無効なら管理者の PowerShell で次を実行して再起動する:
      Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All
    see docs/spec/development.md#windows-sandbox-でのクリーン導入の検証
#>

param([switch]$LegacyNode)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Sandbox は同時に 1 つしか起動できず、起動済みだと新しい設定が反映されない。
# 終了後に WindowsSandboxServer.exe だけが居残ることがあるので、実行中のインスタンスは wsb list で見る
$running = @(
  if (Get-Command wsb.exe -ErrorAction SilentlyContinue) {
    & wsb.exe list 2>$null | Where-Object { $_ -match '[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}' }
  } else {
    Get-Process -Name WindowsSandboxRemoteSession, WindowsSandboxServer -ErrorAction SilentlyContinue
  }
)
if ($running.Count -gt 0) {
  throw '起動中の Windows Sandbox があります。ウィンドウを閉じてから再実行してください。'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$result = Join-Path $repo '.tmp\sandbox-result'
New-Item -ItemType Directory -Force -Path $result | Out-Null
Get-ChildItem -LiteralPath $result -Force | Remove-Item -Recurse -Force

$guestArgs = if ($LegacyNode) { ' -LegacyNode' } else { '' }
$wsb = Join-Path $result 'fresh-install.wsb'
@"
<Configuration>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$PSScriptRoot</HostFolder>
      <SandboxFolder>C:\sandbox-scripts</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$result</HostFolder>
      <SandboxFolder>C:\result</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\sandbox-scripts\guest.ps1$guestArgs</Command>
  </LogonCommand>
</Configuration>
"@ | Set-Content -Path $wsb -Encoding UTF8

Write-Host "Sandbox を起動します。結果: $result\summary.txt"
Start-Process -FilePath $wsb
