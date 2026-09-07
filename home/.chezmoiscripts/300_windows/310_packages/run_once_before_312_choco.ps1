<#
  .SYNOPSIS
    Install keypirinha and its extentions
  .DESCRIPTION
    Install keypirinha via chocolatey
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$requiredPackages = @('chocolateygui', 'Keypirinha')
$installedPackages = @()
if (Get-Command choco -ErrorAction SilentlyContinue) {
  $chocoVersion = [version](& choco --version)
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to determine the Chocolatey version: $LASTEXITCODE"
  }
  $listArgs = @('list', '--limit-output')
  if ($chocoVersion.Major -lt 2) {
    $listArgs += '--local-only'
  }
  $installedPackages = @(
    & choco @listArgs |
      ForEach-Object { ($_ -split '\|', 2)[0] }
  )
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to list installed Chocolatey packages: $LASTEXITCODE"
  }
}
$missingPackages = @($requiredPackages | Where-Object { $installedPackages -notcontains $_ })

# Self-elevate only when Chocolatey or a required package is missing.
# see https://www.chezmoi.io/user-guide/machines/windows/#run-a-powershell-script-as-admin-on-windows
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()  # Get current user identity
$principal = [Security.Principal.WindowsPrincipal] $identity  # Create a principal object
$adminRole = [Security.Principal.WindowsBuiltInRole] 'Administrator' # Define the admin role
$isElevated = $principal.IsInRole($adminRole) # Check if the user has the admin role
if ($missingPackages.Count -gt 0 -and -not $isElevated) {
  $buildNumber = [int](Get-CimInstance -Class Win32_OperatingSystem | Select-Object -ExpandProperty BuildNumber)
  if ($buildNumber -ge 6000) {  # Windows Vista / Windows Server 2008 or later
    $scriptPath = $MyInvocation.MyCommand.Path
    $baseArguments = @('-File', $scriptPath)
    $allArguments = $baseArguments + $MyInvocation.UnboundArguments

    $process = Start-Process -Wait -PassThru -FilePath PowerShell.exe -Verb Runas -ArgumentList $allArguments
    if ($process.ExitCode -ne 0) {
      throw "Elevated Chocolatey setup failed with exit code $($process.ExitCode)"
    }
    Exit 0
  }
}

# Install chocolatey
if (-not (Get-Command choco -ea SilentlyContinue)) {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}

function cinst {
  param([Parameter(Mandatory=$true,ValueFromRemainingArguments=$true)][string[]]$args)
  $id=$args[0]; $rest=if($args.Count -gt 1){$args[1..($args.Count-1)]}else{@()}
  if ($installedPackages -contains $id) {
    return
  }
  & choco install $id -y --no-progress @rest
  if ($LASTEXITCODE -ne 0) {
    throw "Chocolatey setup failed for ${id}: $LASTEXITCODE"
  }
}

cinst chocolateygui
cinst Keypirinha

# ---------- #
# Extensions #
# ---------- #

$install_dir = "$env:UserProfile\AppData\Roaming\Keypirinha\InstalledPackages"
if (-not (Test-Path $install_dir)) {
    New-Item $install_dir -ItemType Directory
}

# function for downloading Keypirinha extensions
function InstallRelease($repo_name, $file_path) {
    if (-not (Test-Path -LiteralPath $file_path -PathType Leaf)) {
        # GitHub Release API
        $uri = "https://api.github.com/repos/" + $repo_name + "/releases/latest"
        $release = Invoke-RestMethod -Uri $uri
        $assetName = Split-Path -Leaf $file_path
        $asset = @($release.assets | Where-Object name -eq $assetName)
        if ($asset.Count -ne 1) {
            throw "Expected one release asset named $assetName in $repo_name, found $($asset.Count)"
        }
        # Download
        Invoke-WebRequest -UseBasicParsing -Uri $asset[0].browser_download_url -OutFile $file_path
    }
}

InstallRelease "Fuhrmann/keypirinha-url-shortener" "$install_dir\URLShortener.keypirinha-package"
InstallRelease "psistorm/keypirinha-systemcommands" "$install_dir\SystemCommands.keypirinha-package"
InstallRelease "clinden/keypirinha-colorpicker" "$install_dir\ColorPicker.keypirinha-package"
# Clipborad Manager
InstallRelease "tuteken/Keypirinha-Plugin-Ditto" "$install_dir\Ditto.keypirinha-package"
# Default Windows Apps
InstallRelease "ueffel/Keypirinha-WindowsApps" "$install_dir\WindowsApps.keypirinha-package"
# Windows Terminal Profiles
InstallRelease "fran-f/keypirinha-terminal-profiles" "$install_dir\Terminal-Profiles.keypirinha-package"
# Search by abbrev
InstallRelease "bantya/Keypirinha-EasySearch" "$install_dir\EasySearch.keypirinha-package"
# Execute commands from >
InstallRelease "bantya/Keypirinha-Command" "$install_dir\Command.keypirinha-package"

# moved to https://codeberg.org/skullzy/keypirinha-snippets
# InstallRelease "dozius/keypirinha-snippets" "$install_dir\Snippets.keypirinha-package"
