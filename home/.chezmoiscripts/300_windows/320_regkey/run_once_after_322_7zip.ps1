<#
  .SYNOPSIS
    decompress files by double-click using 7-Zip
  .DESCRIPTION
    [Attension!] set registry keys
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exts = @("7z", "zip", "rar", "lzh", "tar", "gz")
$command = '"C:\Program Files\7-Zip\7zG.exe" x "%1" -o*'
$needsUpdate = $false
foreach ($ext in $exts) {
    $path = "HKCU:\Software\Classes\7-Zip.$ext\shell\open\command"
    $item = Get-Item -LiteralPath $path -ErrorAction Ignore
    $current = if ($null -eq $item) { $null } else { $item.GetValue('') }
    if ($current -ne $command) {
        $needsUpdate = $true
    }
}

if (-not $needsUpdate) {
    exit 0
}

foreach ($ext in $exts) {
    $path = "HKCU:\Software\Classes\7-Zip.$ext\shell\open\command"
    New-Item -Path $path -Force | Out-Null
    Set-Item -LiteralPath $path -Value $command
}
