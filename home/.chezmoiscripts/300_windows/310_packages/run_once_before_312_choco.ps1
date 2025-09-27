<#
  .SYNOPSIS
    Install keypirinha and its extentions
  .DESCRIPTION
    Install keypirinha via chocolatey
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

# Install chocolatey
if (-not (Get-Command choco -ea SilentlyContinue)) {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}

function cinst {
  param([Parameter(Mandatory=$true,ValueFromRemainingArguments=$true)][string[]]$args)
  $id=$args[0]; $rest=if($args.Count -gt 1){$args[1..($args.Count-1)]}else{@()}
  choco upgrade $id -y --install-if-not-installed --no-progress @rest
}

cinst chocolateygui
cinst Keypirinha

# ---------- #
# Extensions #
# ---------- #

$install_dir = "$env:UserProfile\src\windows-setup\tools\Keypirinha\InstalledPackages"
if (-not (Test-Path $install_dir)) {
    New-Item $install_dir -ItemType Directory
}

# To avoid Internet Explorer initialization
Function Invoke-UpdatedWebRequest {
    $version = $PSVersionTable.PSVersion.Major
    if ($version -le 5) {
        $cmd = "Invoke-WebRequest $args -UseBasicParsing" 
    }
    else {
        $cmd = "Invoke-WebRequest $args" 
    }
    Invoke-Expression $cmd
}
  
# function for downloading Keypirinha extensions
function InstallRelease($repo_name, $file_path) { 
    if (-not (Test-Path $install_dir\$file_path)) {
        # GitHub Release API
        $uri = "https://api.github.com/repos/" + $repo_name + "/releases/latest"
        # Read json
        $json = Invoke-UpdatedWebRequest $uri | ConvertFrom-Json
        # Get URL
        $url = $json.assets.browser_download_url
        # Download
        Invoke-UpdatedWebRequest $url -OutFile $file_path
    }
}

InstallRelease "Fuhrmann/keypirinha-url-shortener" "$install_dir\URLShortener.keypirinha-package"
InstallRelease "psistorm/keypirinha-systemcommands" "$install_dir\SystemCommands.keypirinha-package"
InstallRelease "clinden/keypirinha-colorpicker" "$install_dir\ColorPicker.keypirinha-package"
InstallRelease "dozius/keypirinha-snippets" "$install_dir\Snippets.keypirinha-package"
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
