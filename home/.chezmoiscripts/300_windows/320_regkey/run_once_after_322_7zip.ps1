<#
  .SYNOPSIS
    Register 7-Zip "extract here" as a selectable default app for archive types (HKCU)
  .DESCRIPTION
    Windows 11 does not allow a script to set the default app (UserChoice is protected).
    This registers the ProgIDs and an app capability, so that Settings > Apps > Default apps
    lists "7-Zip (extract)" and one click there makes double-click extract.
    see docs/spec/windows-settings.md#7-zip-の関連付け
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$exts = @("7z", "zip", "rar", "lzh", "tar", "gz")
$command = '"C:\Program Files\7-Zip\7zG.exe" x "%1" -o*'
$icon = '"C:\Program Files\7-Zip\7zFM.exe",0'
$appName = '7-Zip (extract)'
$capabilities = 'Software\dotfiles\7-Zip\Capabilities'

# One entry per registry value: Path (HKCU: relative), Name ('' = default value), Value
$desired = @()
foreach ($ext in $exts) {
    $progId = "Software\Classes\7-Zip.$ext"
    $desired += @{ Path = $progId; Name = ''; Value = "7-Zip .$ext archive" }
    $desired += @{ Path = "$progId\DefaultIcon"; Name = ''; Value = $icon }
    $desired += @{ Path = "$progId\shell\open\command"; Name = ''; Value = $command }
    $desired += @{ Path = "Software\Classes\.$ext\OpenWithProgids"; Name = "7-Zip.$ext"; Value = '' }
    $desired += @{ Path = "$capabilities\FileAssociations"; Name = ".$ext"; Value = "7-Zip.$ext" }
}
$desired += @{ Path = $capabilities; Name = 'ApplicationName'; Value = $appName }
$desired += @{ Path = $capabilities; Name = 'ApplicationDescription'; Value = 'Extract archives with 7-Zip on double-click' }
$desired += @{ Path = 'Software\RegisteredApplications'; Name = $appName; Value = $capabilities }

function Get-Current {
    param($Entry)
    $item = Get-Item -LiteralPath "HKCU:\$($Entry.Path)" -ErrorAction Ignore
    if ($null -eq $item) { return $null }
    # Missing and empty differ: GetValue returns $null for a missing value
    return $item.GetValue($Entry.Name, $null)
}

$pending = @($desired | Where-Object { (Get-Current $_) -ne $_.Value })
if ($pending.Count -eq 0) {
    exit 0
}

foreach ($entry in $pending) {
    $path = "HKCU:\$($entry.Path)"
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -Path $path -Force | Out-Null
    }
    if ($entry.Name -eq '') {
        Set-Item -LiteralPath $path -Value $entry.Value
    } else {
        New-ItemProperty -LiteralPath $path -Name $entry.Name -PropertyType String -Value $entry.Value -Force | Out-Null
    }
}
