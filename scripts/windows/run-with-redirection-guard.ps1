<#
  .SYNOPSIS
    RedirectionGuard を有効にしたプロセスでコマンドを実行する (ssh のセッションの再現用)
  .DESCRIPTION
    sshd は RedirectionGuard (ProcessRedirectionTrustPolicy) を有効にして動き、子のプロセスも引き継ぐ。
    管理者でないユーザーが作った junction は、有効なプロセスから辿れない (ERROR_UNTRUSTED_MOUNT_POINT, 448)。
    このスクリプトは自分のプロセスで有効にしてから、引数のコマンドを実行する。ssh で入らなくても、
    ssh のセッションでの動作を確かめられる。有効にするのはこのプロセスと子孫だけで、レジストリ・sshd・システムは変えない。
    Windows 11 24H2 以降。結果の記録は docs/research/shell/redirectionguard-ssh-2026-11.md

    使い方: run-with-redirection-guard.ps1 <コマンド> [引数...]。引数は変換せずそのまま渡す
    (`-Command` や `-Verbose` も子の引数。このスクリプト自身は param を持たない)。
    終了コードは、子のネイティブコマンドのものをそのまま返す。cmdlet やスクリプトは、成功なら 0、失敗なら 1。
    保護を有効にできない OS (24H2 より前など) は、メッセージを出して 125 で終わる。
  .EXAMPLE
    pwsh -NoProfile -File scripts\windows\run-with-redirection-guard.ps1 uv --version
  .EXAMPLE
    pwsh -NoProfile -File scripts\windows\run-with-redirection-guard.ps1 pwsh -NoLogo
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($args.Count -lt 1) {
  [Console]::Error.WriteLine('usage: run-with-redirection-guard.ps1 <command> [arguments...]')
  exit 2
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class RedirectionGuard {
  [DllImport("kernel32.dll", SetLastError = true)]
  static extern bool SetProcessMitigationPolicy(int policy, ref uint buffer, UIntPtr length);

  // PROCESS_MITIGATION_POLICY の ProcessRedirectionTrustPolicy (16) の EnforceRedirectionTrust (bit 0)
  public static int Enable() {
    uint flags = 1;
    return SetProcessMitigationPolicy(16, ref flags, (UIntPtr)4) ? 0 : Marshal.GetLastWin32Error();
  }
}
'@

$errorCode = [RedirectionGuard]::Enable()
if ($errorCode -ne 0) {
  [Console]::Error.WriteLine("RedirectionGuard を有効にできない (Win32 エラー $errorCode)。Windows 11 24H2 以降が要る")
  exit 125
}

$command = $args[0]
$rest = @($args | Select-Object -Skip 1)
$global:LASTEXITCODE = 0
& $command @rest
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
exit $(if ($?) { 0 } else { 1 })
