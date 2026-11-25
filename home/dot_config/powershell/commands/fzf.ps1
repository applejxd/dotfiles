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

# PSFzf (Ctrl+t / Ctrl+r) は読み込みに 0.2 秒かかり、起動の idle に置くと打鍵が止まる。
# 仮のキーハンドラを置き、初めて押されたときに読み込んで本物の割り当てへ差し替える。
# 読み込めないとき (未導入・壊れている) は、警告して標準の割り当て (Emacs モード) に戻す。
# see docs/spec/shell.md#powershellプロファイル
function Initialize-PsFzfOnDemand {
  try {
    Import-Module PSFzf -Scope Global -ErrorAction Stop
    Set-PsFzfOption -PSReadlineChordProvider 'Ctrl+t' -PSReadlineChordReverseHistory 'Ctrl+r'
    $true
  } catch {
    Write-Warning "Failed to set up PSFzf: $_"
    Set-PSReadLineKeyHandler -Chord 'Ctrl+r' -Function ReverseSearchHistory
    Set-PSReadLineKeyHandler -Chord 'Ctrl+t' -Function SwapCharacters
    $false
  }
}

function Register-PsFzfLazyKeyHandler {
  Set-PSReadLineKeyHandler -Chord 'Ctrl+t' -BriefDescription 'PSFzf (lazy)' -ScriptBlock {
    if (Initialize-PsFzfOnDemand) {
      Invoke-FzfPsReadlineHandlerProvider
    } else {
      [Microsoft.PowerShell.PSConsoleReadLine]::SwapCharacters()
    }
  }
  Set-PSReadLineKeyHandler -Chord 'Ctrl+r' -BriefDescription 'PSFzf (lazy)' -ScriptBlock {
    if (Initialize-PsFzfOnDemand) {
      Invoke-FzfPsReadlineHandlerHistory
    } else {
      [Microsoft.PowerShell.PSConsoleReadLine]::ReverseSearchHistory()
    }
  }
}
