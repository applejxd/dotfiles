<#
  .SYNOPSIS
    Install packages by scoop
  .DESCRIPTION
    Install Linux tools to user environments by scoop
#>

# Memo: Japanese comments cause new line error

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$gitConfigCount = 0
$hasGitConfigCount = [int]::TryParse($env:GIT_CONFIG_COUNT, [ref]$gitConfigCount)
$invalidGitConfig = $false
if ($hasGitConfigCount) {
  for ($i = 0; $i -lt $gitConfigCount; $i++) {
    if (
      -not (Test-Path "Env:GIT_CONFIG_KEY_$i") -or
      -not (Test-Path "Env:GIT_CONFIG_VALUE_$i")
    ) {
      $invalidGitConfig = $true
      break
    }
  }
}
if ($invalidGitConfig) {
  Get-ChildItem Env: |
    Where-Object Name -Match '^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)$' |
    Remove-Item
}

if (!(Get-Command scoop -ErrorAction Ignore)) {
  Invoke-WebRequest -useb get.scoop.sh | Invoke-Expression
}

$installedApps = @(scoop list | ForEach-Object { $_.Name })
if ($LASTEXITCODE -ne 0) {
  throw "Failed to list installed Scoop apps: $LASTEXITCODE"
}

function sinst {
  param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$PackageId)

  $missingApps = @($PackageId | Where-Object { $installedApps -notcontains $_ })
  if ($missingApps.Count -eq 0) {
    return
  }

  & scoop install @missingApps
  if ($LASTEXITCODE -ne 0) {
    throw "scoop install failed for $($missingApps -join ', '): $LASTEXITCODE"
  }
}

# Linux commands (gow = Gnu on Windows)
# see https://github.com/bmatzelle/gow/wiki/executables_list
sinst sudo gow

# build tools
sinst mingw-winlibs
# other tools
sinst ghq pdftk
