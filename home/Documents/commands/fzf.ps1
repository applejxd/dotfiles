# ghq-fzf
# C-x C-g のキーバインドに関数割り当て
if (Get-Command ghq -ea SilentlyContinue) {
  function xg {
    $path = ghq list | fzf
    # パスが空の文字列でなければ実行
    if (!([string]::IsNullOrEmpty($path))) {
      Set-Location "$(ghq root)\$path"
      # バッファの内容を実行
      [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    }
    # 画面をクリア
    Clear-Host
  }

  Set-PSReadLineKeyHandler -Chord 'Ctrl+x,Ctrl+g' -ScriptBlock { xg }
}

# z-fzf
Import-Module ZLocation
if (Get-Command z -ea SilentlyContinue) {
  function xf {
    # ZLocation の一覧オブジェクトの Path プロパティ抜き出し
    $path = z -l | ForEach-Object { Write-Output $_.Path } | fzf
    if (!([string]::IsNullOrEmpty($path))) {
      Set-Location "$path"
      [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    }
    Clear-Host
  }
  Set-PSReadLineKeyHandler -Chord 'Ctrl+x,Ctrl+f' -ScriptBlock { xf }
}

function fssh {
  $destination = Get-Content "$HOME\.ssh\config" | Select-String "^Host ([^*]+)$" | ForEach-Object { $_ -replace "Host ", "" } | fzf
  if (!([string]::IsNullOrEmpty($destination))) { 
    ssh "$destination"
  }
  Clear-Host
}