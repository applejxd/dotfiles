# fzf を使った補助コマンドとキーバインド。
#
# キーハンドラの登録はモジュール (ghq / ZLocation) の読み込み後である必要がある
# ため、関数定義と Register-FzfKeyHandler に分け、登録はプロファイルの OnIdle
# から 1 度だけ呼び出す。

# ghq-fzf
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

# z-fzf
function xf {
  # ZLocation の一覧オブジェクトの Path プロパティ抜き出し
  $path = z -l | ForEach-Object { Write-Output $_.Path } | fzf
  if (!([string]::IsNullOrEmpty($path))) {
    Set-Location "$path"
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
  }
  Clear-Host
}

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

function Register-FzfKeyHandler {
  if (Get-Command ghq -ErrorAction Ignore) {
    Set-PSReadLineKeyHandler -Chord 'Ctrl+x,Ctrl+g' -ScriptBlock { xg }
  }
  if (Get-Command z -ErrorAction Ignore) {
    Set-PSReadLineKeyHandler -Chord 'Ctrl+x,Ctrl+f' -ScriptBlock { xf }
  }
}
