<#
  .SYNOPSIS
    Install VSCode and extentions
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$codeCommand = Get-Command code -ErrorAction SilentlyContinue
if (-not $codeCommand) {
  # Install VS Code only when it is not available
  & winget install Microsoft.VisualStudioCode --scope machine --silent --accept-package-agreements --accept-source-agreements --override "/silent /mergetasks=""addcontextmenufiles,addcontextmenufolders"""
  if ($LASTEXITCODE -ne 0) {
    throw "VS Code installation failed with exit code $LASTEXITCODE"
  }

  # Enable path to vscode command for the current session after installation
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')

  $codeCommand = Get-Command code -ErrorAction SilentlyContinue
  if (-not $codeCommand) {
    Write-Warning 'Unable to locate the code command. Skipping extension installation.'
    return
  }
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
