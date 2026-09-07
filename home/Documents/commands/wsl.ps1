function wslls { wsl -l -v }

function Select-WslDistro {
  @(wsl -l -q) |
    ForEach-Object { ($_ -replace "`0", "").Trim() } |
    Where-Object { $_ } |
    fzf
}

function Get-OnlineWslDistros {
  @(wsl --list --online) |
    ForEach-Object { ($_ -replace "`0", "").TrimEnd() } |
    ForEach-Object {
      if ($_ -match '^\s*(\S+)\s{2,}.+$' -and $Matches[1] -ne 'NAME') {
        $Matches[1]
      }
    } |
    Select-Object -Unique
}

function wslex {
  $distro = Select-WslDistro
  if (-not [string]::IsNullOrWhiteSpace($distro)) {
    $date = Get-Date -UFormat "%y.%m.%d"
    wsl --export $distro "${distro}_${date}.tar"
  }
  Clear-Host
}

function wslim {
  $fileName = Get-ChildItem -File -Filter '*.tar' | Select-Object -ExpandProperty FullName | fzf
  if ([string]::IsNullOrWhiteSpace($fileName)) {
    return
  }
  $distroName = [IO.Path]::GetFileNameWithoutExtension($fileName)
  $importPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'WSL'
  New-Item -ItemType Directory -Path $importPath -Force | Out-Null
  wsl --import $distroName (Join-Path $importPath $distroName) $fileName
}

function wslrm {
  $distro = Select-WslDistro
  if (-not [string]::IsNullOrWhiteSpace($distro)) {
    wsl --unregister $distro
  }
  Clear-Host
}

function wslin {
  $distro = Get-OnlineWslDistros | fzf
  if (-not [string]::IsNullOrWhiteSpace($distro)) {
    wsl --install -d $distro
  }
  Clear-Host
}

function wslrun {
  $distro = Select-WslDistro
  if (-not [string]::IsNullOrWhiteSpace($distro)) {
    wsl -d $distro --cd '~' -e /usr/bin/bash @args
  }
  Clear-Host
}

function wsluser ($distro, $user) {
  $uidText = wsl -d $distro -u $user -e id -u
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to resolve UID for ${user} in ${distro}: $LASTEXITCODE"
  }
  $uid = [int]($uidText | Select-Object -First 1)
  $distroKey = Get-ItemProperty Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Lxss\*\ DistributionName |
    Where-Object -Property DistributionName -eq $distro |
    Select-Object -First 1
  if (-not $distroKey) {
    throw "WSL distribution not found in the registry: $distro"
  }
  Set-ItemProperty -LiteralPath $distroKey.PSPath -Name DefaultUid -Value $uid
}
