<#
  .SYNOPSIS
    Install VSCode and extentions
#>

# Self-elevate the script if required
# see https://www.chezmoi.io/user-guide/machines/windows/#run-a-powershell-script-as-admin-on-windows
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()  # Get current user identity
$principal = [Security.Principal.WindowsPrincipal] $identity  # Create a principal object
$adminRole = [Security.Principal.WindowsBuiltInRole] 'Administrator' # Define the admin role
$isElevated = $principal.IsInRole($adminRole) # Check if the user has the admin role
if (-not $isElevated) {
  $buildNumber = [int](Get-CimInstance -Class Win32_OperatingSystem | Select-Object -ExpandProperty BuildNumber)
  if ($buildNumber -ge 6000) {  # Windows Vista / Windows Server 2008 or later
    $scriptPath = $MyInvocation.MyCommand.Path
    $baseArguments = @('-File', $scriptPath)
    $allArguments = $baseArguments + $MyInvocation.UnboundArguments

    Start-Process -Wait -FilePath PowerShell.exe -Verb Runas -ArgumentList $allArguments
    Exit
  }
}

$codeCommand = Get-Command code -ErrorAction SilentlyContinue
if (-not $codeCommand) {
  # Install VS Code only when it is not available
  winget install Microsoft.VisualStudioCode --scope machine --silent --accept-package-agreements --accept-source-agreements --override "/silent /mergetasks=""addcontextmenufiles,addcontextmenufolders"""

  # Enable path to vscode command for the current session after installation
  $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')

  $codeCommand = Get-Command code -ErrorAction SilentlyContinue
  if (-not $codeCommand) {
    Write-Warning 'Unable to locate the code command. Skipping extension installation.'
    return
  }
}

# Collect currently installed extensions to avoid reinstalling
$installedExtensions = @()
try {
  $installedExtensions = @(& $codeCommand.Path --list-extensions)
} catch {
  Write-Warning 'Failed to retrieve the current extensions list. All extensions will be attempted.'
}

# Define extension categories
$extensions = @{
  'Theme'      = @(
      'ms-ceintl.vscode-language-pack-ja',
      'Anan.jetbrains-darcula-theme',
      'chadalen.vscode-jetbrains-icon-theme',
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
  'AI agent'   = @(
      'genieai.chatgpt-vscode',
      'saoudrizwan.claude-dev'
  )
  'Markdown'   = @(
      'yzhang.markdown-all-in-one',
      'DavidAnson.vscode-markdownlint'
  )
  'C/C++'      = @(
      'ms-vscode.cpptools',
      'ms-vscode.cpptools-extension-pack',
      'ms-vscode.cpptools-themes',
      'xaver.clang-format',
      'jeff-hykin.better-cpp-syntax',
      'notskm.clang-tidy',
      'twxs.cmake',
      'ms-vscode.cmake-tools'
  )
  'Python'     = @(
      'ms-python.python',
      "charliermarsh.ruff"
  )
}

# Install extensions that are not yet present
foreach ($category in $extensions.Keys) {
  foreach ($extension in $extensions[$category]) {
      if ($installedExtensions -notcontains $extension) {
        & $codeCommand.Path --install-extension $extension
      }
  }
}
