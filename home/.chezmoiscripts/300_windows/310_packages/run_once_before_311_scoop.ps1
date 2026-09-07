<#
  .SYNOPSIS
    Install packages by scoop
  .DESCRIPTION
    Install Linux tools to user environments by scoop
#>

# Memo: Japanese comments cause new line error

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (!(Get-Command scoop -ea SilentlyContinue)) {
  Invoke-WebRequest -useb get.scoop.sh | Invoke-Expression
}

function sinst {
  param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$PackageId)

  & scoop install @PackageId
  if ($LASTEXITCODE -ne 0) {
    throw "scoop install failed for $($PackageId -join ', '): $LASTEXITCODE"
  }
}

# Linux commands (gow = Gnu on Windows)
# see https://github.com/bmatzelle/gow/wiki/executables_list
sinst sudo gow

# build tools
sinst mingw-winlibs
# other tools
sinst ghq pdftk
