# init 出力のキャッシュ。profile.ps1 がトップレベルで dot-source する。
# 起動経路で読まれるため、profile.ps1 冒頭の制約 (cmdlet を使わない) に従う。

# mise の init は毎起動で外部プロセスを起動するが、出力は実行ファイルが変わらない
# 限り不変なのでキャッシュする。oh-my-posh の init はキャッシュできないため、
# profile.ps1 の対話ブロックで毎回実行している (see docs/spec/structure.md#powershellプロファイル)。
#
# stamp には実行ファイルの絶対パス・サイズ・更新時刻を記録し、検証もそれだけで
# 行う。Get-Command はコマンド探索を走らせて 0.2 秒かかるため、キャッシュが無効
# なとき (初回・ツール更新後) にしか呼ばない。
function Get-CachedInitScript {
  [OutputType([string])]
  param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$CommandName,
    [Parameter(Mandatory)][scriptblock]$Generator,
    [string]$ExtraKey = ''
  )

  # Join-Path は Microsoft.PowerShell.Management の読み込みを伴うため使わない。
  # $null / 空文字を Combine へ渡すと例外ではなく相対パスになり、キャッシュが
  # カレントディレクトリに作られてしまうため、先に解決しておく。
  $localAppData = $env:LOCALAPPDATA
  if ([string]::IsNullOrEmpty($localAppData)) {
    $localAppData = [Environment]::GetFolderPath('LocalApplicationData')
  }
  if ([string]::IsNullOrEmpty($localAppData)) {
    return $null
  }
  $cacheRoot = [System.IO.Path]::Combine($localAppData, 'PowerShellProfileCache')
  $cacheFile = [System.IO.Path]::Combine($cacheRoot, "$Name.ps1")
  $stampFile = [System.IO.Path]::Combine($cacheRoot, "$Name.stamp")
  # Windows PowerShell 5.1 は BOM の無い .ps1 を ANSI コードページとして読む。
  # キャッシュには実行ファイルの絶対パスが入るため、BOM を付けないとユーザー名や
  # インストール先に非 ASCII を含む環境で壊れる。
  $utf8WithBom = [System.Text.UTF8Encoding]::new($true)

  function Get-Stamp([string]$ExecutablePath) {
    # 壊れた stamp から不正なパスを渡されても、起動時エラーではなく
    # キャッシュミスとして扱う (FileInfo は不正な形式のパスで例外を投げる)。
    try {
      $executable = [System.IO.FileInfo]::new($ExecutablePath)
      if (-not $executable.Exists) {
        return $null
      }
      @(
        $executable.FullName
        $executable.Length
        $executable.LastWriteTimeUtc.Ticks
        $ExtraKey
      ) -join '|'
    } catch {
      return $null
    }
  }

  # 別シェルが同じ stamp を書き換えている最中は読めないことがある。
  # その場合もキャッシュミスとして扱い、起動時エラーにはしない。
  if ([System.IO.File]::Exists($cacheFile) -and [System.IO.File]::Exists($stampFile)) {
    try {
      $stamp = [System.IO.File]::ReadAllText($stampFile)
      if ($stamp -and ((Get-Stamp $stamp.Split('|')[0]) -eq $stamp)) {
        return $cacheFile
      }
    } catch { }
  }

  # 同名の実行ファイルが複数の PATH に存在しうる (例: winget の shim と本体)
  $command = @(Get-Command $CommandName -ErrorAction Ignore -CommandType Application)[0]
  if (-not $command) {
    return $null
  }
  $stamp = Get-Stamp $command.Path
  if (-not $stamp) {
    return $null
  }

  $generated = & $Generator $command.Path
  if ([string]::IsNullOrWhiteSpace($generated)) {
    return $null
  }

  # 同時に起動したシェルが書き込み途中のファイルを読まないよう、一時ファイル経由で置く。
  # stamp はキャッシュ本体の後に書くので、壊れた stamp は次回の再生成になるだけで済む。
  # 置き換えに失敗しても生成済みの内容は使えるよう、一時ファイルのパスを返す
  # (キャッシュはあくまで最適化で、失敗しても mise の activate 等は行う)。
  # dot-source は .ps1 以外を Application として扱い、実行せずにシェル関連付けで
  # 開こうとするため、一時ファイル名も .ps1 で終わらせる。
  $tempFile = [System.IO.Path]::Combine($cacheRoot, "$Name.$PID.tmp.ps1")
  try {
    [System.IO.Directory]::CreateDirectory($cacheRoot) | Out-Null
    # 置き換えへ失敗して残った一時ファイルを掃除する。同時に起動した別プロセスが
    # 書き込み中のものを消さないよう、十分古いものだけを対象にする。
    $staleBefore = [DateTime]::UtcNow.AddHours(-1)
    foreach ($stale in [System.IO.Directory]::GetFiles($cacheRoot, "$Name.*.tmp.ps1")) {
      try {
        if ([System.IO.File]::GetLastWriteTimeUtc($stale) -lt $staleBefore) {
          [System.IO.File]::Delete($stale)
        }
      } catch { }
    }
    [System.IO.File]::WriteAllText($tempFile, $generated, $utf8WithBom)
    if ([System.IO.File]::Exists($cacheFile)) {
      # PowerShell は $null を空文字へ変換するため、backup 無しは [NullString]::Value で渡す
      [System.IO.File]::Replace($tempFile, $cacheFile, [NullString]::Value)
    } else {
      [System.IO.File]::Move($tempFile, $cacheFile)
    }
  } catch {
    Write-Warning "Failed to store the $Name init cache: $_"
    if ([System.IO.File]::Exists($tempFile)) {
      return $tempFile
    }
    return $null
  }

  # 本体の設置後は stamp が書けなくても実害はない (次回再生成されるだけ)。
  # 別シェルが検証のために stamp を読んでいると書き込みは競合しうるため、
  # ここで失敗しても $cacheFile を返して activate は行う。
  try {
    [System.IO.File]::WriteAllText($stampFile, $stamp, $utf8WithBom)
  } catch {
    Write-Warning "Failed to store the $Name cache stamp: $_"
  }
  return $cacheFile
}
