# ghq-fzf
# C-x C-g のキーバインドに関数割り当て
if (Get-Command ghq -ErrorAction Ignore) {
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
Register-EngineEvent -SourceIdentifier PowerShell.OnIdle -Action {
  Import-Module ZLocation -Scope Global -ErrorAction SilentlyContinue
  if (Get-Command z -ErrorAction Ignore) {
    function global:xf {
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
  Unregister-Event -SubscriptionId $EventSubscriber.SubscriptionId
} | Out-Null

function sshf {
  $sshConfig = "$HOME\.ssh\config"
  if (-not (Test-Path -LiteralPath $sshConfig -PathType Leaf)) {
    Write-Warning "SSH config not found: $sshConfig"
    return
  }
  $destination = Get-Content -LiteralPath $sshConfig | Select-String "^Host ([^*]+)$" | ForEach-Object { $_ -replace "Host ", "" } | fzf
  if (!([string]::IsNullOrEmpty($destination))) {
    ssh "$destination"
  }
  Clear-Host
}
