<#
  .SYNOPSIS
    Install VSCode and extentions
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# VS Code itself is installed by 310_packages/309_admin (machine-wide); this script only adds extensions.
$codeCommand = Get-Command code -ErrorAction SilentlyContinue
if (-not $codeCommand) {
  # PATH of this session may be stale after the admin step
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
  $codeCommand = Get-Command code -ErrorAction SilentlyContinue
}
if (-not $codeCommand) {
  $candidates = @($env:ProgramFiles, $env:LOCALAPPDATA) | Where-Object { $_ } | ForEach-Object {
    $root = if ($_ -eq $env:LOCALAPPDATA) { Join-Path $_ 'Programs\Microsoft VS Code' } else { Join-Path $_ 'Microsoft VS Code' }
    Join-Path $root 'bin\code.cmd'
  }
  $found = @($candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }) | Select-Object -First 1
  if (-not $found) {
    throw 'VS Code (code command) not found; rerun after the admin setup (309_admin) has installed it.'
  }
  $codeCommand = Get-Command $found -CommandType Application
}

# Collect currently installed extensions to avoid reinstalling.
$installedExtensions = @(& $codeCommand.Path --list-extensions)
if ($LASTEXITCODE -ne 0) {
  throw "Failed to retrieve installed VS Code extensions: $LASTEXITCODE"
}

# Define extension categories
$extensions = @{
  'Theme'      = @(
      'ms-ceintl.vscode-language-pack-ja',
      'usernamehw.errorlens'
  )
  'Git'        = @(
      'eamodio.gitlens',
      'mhutchie.git-graph'
  )
  'Remote'     = @(
      'ms-vscode-remote.remote-wsl',
      'ms-vscode-remote.remote-containers'
  )
  'C/C++'      = @(
      'ms-vscode.cpptools',
      'ms-vscode.cpptools-extension-pack',
      'ms-vscode.cpptools-themes',
      'ms-vscode.cmake-tools'
  )
  'Python'     = @(
      'ms-python.python',
      "charliermarsh.ruff"
  )
}

# Install extensions that are not yet present
$failedExtensions = @()
foreach ($category in $extensions.Keys) {
  foreach ($extension in $extensions[$category]) {
      if ($installedExtensions -notcontains $extension) {
        & $codeCommand.Path --install-extension $extension
        if ($LASTEXITCODE -ne 0) {
          $failedExtensions += $extension
          Write-Warning "Failed to install VS Code extension: $extension"
        }
      }
  }
}

if ($failedExtensions.Count -gt 0) {
  throw "Failed to install $($failedExtensions.Count) VS Code extension(s)."
}
