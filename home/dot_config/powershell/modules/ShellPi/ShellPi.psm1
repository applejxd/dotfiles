# pi の特殊な起動 2 つ: drypi (モデルの上に載るものを全部切る) と superpi (drypi を管理者で起動する)。
# bash / zsh の functions/pi.sh に相当する。Windows PowerShell 5.1 と PowerShell 7 の両方で動かす。
# 対話セッションだけで読み込む。pi (外部の実行ファイル) と sudo は呼び出し時に探す。
# 意図・切るもの・注意: docs/spec/shell.md#pi-の特殊な起動-drypi-と-superpi

# drypi が切るもの。superpi も同じ一覧を使うので、切る範囲を変えるときはここだけ直す。
# --no-extensions は、組み込みの MCP・tool_search・codemode と、設定した package 由来の拡張も切る (--no-mcp は足さない)。
# --no-approve は、信頼の対象になるプロジェクトの .pi/ の設定・拡張・MCP を、この実行では読まない。
function Get-PiDryArgument {
  '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--no-approve'
}

# 外部の pi の実行ファイル (関数・エイリアスは除く)
function Get-PiExecutable {
  $command = Get-Command pi -CommandType Application -ErrorAction Ignore | Select-Object -First 1
  if ($command) { $command.Source }
}

# 起動したその場所のまま (作業ディレクトリは変えない)。引数は pi へそのまま渡す。
# 例: drypi / drypi -p "依頼" / "依頼" | drypi -p
function drypi {
  $pi = Get-PiExecutable
  if (-not $pi) {
    Write-Error 'drypi: pi の実行ファイルが PATH に無い'
    return
  }
  if ($MyInvocation.ExpectingInput) {
    $input | & $pi @(Get-PiDryArgument) @args
  } else {
    & $pi @(Get-PiDryArgument) @args
  }
}

# 管理者 (Windows の sudo) で drypi を起動する。ドライブの根からの起動 (呼んだシェルの作業ディレクトリは戻る)。
# 認証・設定は利用者のものをそのまま使う (昇格しても同じユーザーなので HOME の受け渡しは要らない)。
# 管理者が ~/.pi/agent に自分の所有のファイルを作ると、あとで通常の pi が書けなくなるおそれがあるため、
# セッションを保存せず (--no-session)、起動時の自動の通信もしない (--offline)。
# sudo の既定は新しいウィンドウで起動する (`sudo config` で変えられる)。
function superpi {
  $sudo = Get-Command sudo -CommandType Application -ErrorAction Ignore | Select-Object -First 1
  if (-not $sudo) {
    Write-Error 'superpi: sudo が無い'
    return
  }
  $pi = Get-PiExecutable
  if (-not $pi) {
    Write-Error 'superpi: pi の実行ファイルが PATH に無い'
    return
  }
  $root = [System.IO.Path]::GetPathRoot([Environment]::GetFolderPath('System'))
  # chpwd の一覧表示 (commands/interactive.ps1) を、この移動では出さない
  $global:ChpwdSuppress = $true
  Push-Location -LiteralPath $root
  try {
    & $sudo.Source $pi @(Get-PiDryArgument) --no-session --offline @args
  } finally {
    Pop-Location
    $global:ChpwdSuppress = $false
  }
}
