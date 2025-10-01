function wslls { wsl -l -v }

function wslex {
  # Where-Object で空行削除
  $distro = wsl -l -q | Where-Object { $_ -ne "" } | fzf
  if (!([string]::IsNullOrEmpty($distro))) {
    # null 文字を削除
    # see https://stackoverflow.com/questions/9863455/how-to-remove-null-char-0x00-from-object-within-powershell
    $distro = $distro -replace "`0", ""
    $date = Get-Date -UFormat "%y.%m.%d"
    # https://sevenb.jp/wordpress/ura/2016/06/01/powershell%E6%96%87%E5%AD%97%E5%88%97%E5%86%85%E3%81%AE%E5%A4%89%E6%95%B0%E5%B1%95%E9%96%8B%E3%81%A7%E5%A4%89%E6%95%B0%E5%90%8D%E3%82%92%E7%A2%BA%E5%AE%9A%E3%81%95%E3%81%9B%E3%82%8B/
    wsl --export "${distro}" "${distro}_${date}.tar"
  }
  Clear-Host
}

function wslim {
  $file_name = Get-ChildItem ./*.tar -name | fzf
  $distro_name = [System.IO.Path]::GetFileNameWithoutExtension($file_name)
  $import_path = [Environment]::GetFolderPath('LocalApplicationData') + "\WSL"
  if (!(Test-Path $import_path)) {
    mkdir $import_path
  }
  wsl --import $distro_name "${import_path}\${distro_name}" $file_name
}

function wslrm {
  # Where-Object で空行削除
  $distro = wsl -l -q | Where-Object { $_ -ne "" } | fzf
  if (!([string]::IsNullOrEmpty($distro))) {
    # null 文字を削除
    # see https://stackoverflow.com/questions/9863455/how-to-remove-null-char-0x00-from-object-within-powershell
    $distro = $distro -replace "`0", ""
    wsl --unregister $distro
  }
  Clear-Host
}

function wslin {
  # Where-Object で空行削除
  $distro = wsl -l --online | Where-Object { $_ -ne "" } | Select-Object -Skip 3 | fzf
  if (!([string]::IsNullOrEmpty($distro))) {
    # null 文字を削除 & スペース区切りで最初の文字列取得
    # see https://stackoverflow.com/questions/9863455/how-to-remove-null-char-0x00-from-object-within-powershell
    $distro = ($distro -replace "`0", "").Split(" ")[0]
    wsl --install -d $distro
  }
  Clear-Host
}

function wslrun {
  # Where-Object で空行削除
  $distro = wsl -l -q | Where-Object { $_ -ne "" } | fzf
  if (!([string]::IsNullOrEmpty($distro))) {
    # null 文字を削除
    # see https://stackoverflow.com/questions/9863455/how-to-remove-null-char-0x00-from-object-within-powershell
    $distro = $distro -replace "`0", ""
    wsl ~ -d $distro $args -e /usr/bin/bash
  }
  Clear-Host
}

function wsluser ($distro, $user) { 
  Get-ItemProperty Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Lxss\*\ DistributionName | `
    Where-Object -Property DistributionName -eq $distro | `
    Set-ItemProperty -Name DefaultUid -Value ((wsl -d $distro -u $user -e id -u) | Out-String)
}
