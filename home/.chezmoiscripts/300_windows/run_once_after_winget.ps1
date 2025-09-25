<#
  .SYNOPSIS
    Install packages by winget and NuGet
  .DESCRIPTION
    Install keypirinha via chocolatey
#>

# Self-elevate the script if required
# see https://www.chezmoi.io/user-guide/machines/windows/#run-a-powershell-script-as-admin-on-windows
if (-Not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] 'Administrator')) {
  if ([int](Get-CimInstance -Class Win32_OperatingSystem | Select-Object -ExpandProperty BuildNumber) -ge 6000) {
    $CommandLine = "-NoExit -File `"" + $MyInvocation.MyCommand.Path + "`" " + $MyInvocation.UnboundArguments
    Start-Process -Wait -FilePath PowerShell.exe -Verb Runas -ArgumentList $CommandLine
    Exit
  }
}

# ----- #
# NuGet #
# ----- #

# NuGet プロバイダー更新
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force
# fzf wrapper (needs fzf binary from chocolatey or scoop)
Install-Module -Name PSFzf -RequiredVersion 2.1.0 -Scope CurrentUser -Force
# z コマンド
Install-Module -Name ZLocation -Scope CurrentUser -Force

# oh-my-posh integration for git prompt
Install-Module -Name posh-git -Scope CurrentUser -Force

# ------ #
# winget #
# ------ #

Function winst {
  $cmd = "winget install --source winget --silent --accept-package-agreements --accept-source-agreements $args"
  Invoke-Expression $cmd
}

# tools
winst Microsoft.PowerShell
winst Google.Chrome
winst Google.JapaneseIME
winst 7zip.7zip
winst junegunn.fzf
winst Obsidian.Obsidian

# terminal
winst JanDeDobbeleer.OhMyPosh
winst SourceFoundry.HackFonts

# utilities
winst Microsoft.PowerToys
winst Ditto.Ditto
winst WinSCP.WinSCP

# MCP
winst OpenJS.NodeJS
winst stral-sh.uv
