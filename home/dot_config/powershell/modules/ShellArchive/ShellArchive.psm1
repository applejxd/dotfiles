# 圧縮・展開の関数 (extract / zpack / zunpack)。bash / zsh の functions/archive.sh に相当する。
# Windows PowerShell 5.1 と PowerShell 7 の両方で動かす。対話セッションだけで読み込む。
# PowerShell のパイプは外部コマンドのバイト列を壊す (5.1) ので、パイプを使わず tar に圧縮・展開を任せる。
# PATH の tar は 2 種類ある: Git for Windows 同梱の GNU tar (MSYS) と、Windows 標準の bsdtar。
#   - GNU tar: `C:\x.tar` の `C:` をリモートのホスト名と読むので --force-local が要る。
#     zstd は --use-compress-program で外部の zstd へ渡す。
#   - bsdtar: zstd を内蔵する (展開は自動判定。圧縮は --zstd --options)。
# どちらにも、パスは `/` 区切りで渡す (GNU tar は `-C C:\dir` の `\` を読み違える)。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

# tar の種類 ('gnu' か 'bsd')。最初に使うときだけ調べて覚える
function Get-TarFlavor {
  $flavor = Get-Variable -Name TarFlavor -Scope Global -ValueOnly -ErrorAction Ignore
  if (-not $flavor) {
    $flavor = if ((& tar --version 2>&1 | Out-String) -match 'GNU tar') { 'gnu' } else { 'bsd' }
    Set-Variable -Name TarFlavor -Scope Global -Value $flavor
  }
  $flavor
}

# tar へ渡すパス
function ConvertTo-TarPath {
  param([Parameter(Mandatory)][string]$Path)

  $Path.Replace('\', '/')
}

# 展開の共通の引数 (tar の種類ごと)
function Get-TarExtractOption {
  param([switch]$Zstd)

  if ((Get-TarFlavor) -eq 'gnu') {
    '--force-local'
    if ($Zstd) { '--use-compress-program=zstd' }
  }
}

# 拡張子に応じて展開する
function extract {
  param([Parameter(Mandatory, Position = 0)][string]$Path)

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Write-Error "extract: $Path : No such file"
    return
  }
  $archive = ConvertTo-TarPath $Path
  switch -Regex ($Path.ToLowerInvariant()) {
    '\.(tar\.zst|tzst)$' { tar @(Get-TarExtractOption -Zstd) -xvf $archive; break }
    '\.(tar\.gz|tgz|tar\.xz|txz|tar\.bz2|tbz|tbz2|tar\.z|tar)$' { tar @(Get-TarExtractOption) -xvf $archive; break }
    '\.zip$' {
      if (Test-ExternalCommand unzip) {
        unzip $Path
      } else {
        Expand-Archive -LiteralPath $Path -DestinationPath .
      }
      break
    }
    '\.(lzh|arj|7z|rar)$' { 7z x $Path; break }
    '\.gz$' { gzip -d $Path; break }
    '\.bz2$' { bzip2 -dk $Path; break }
    '\.xz$' { xz -dk $Path; break }
    '\.z$' { gzip -d $Path; break }
    '\.zst$' { zstd -d $Path; break }
    default { Write-Error "extract: $Path : 未対応の拡張子" }
  }
}

# tar + zstd で圧縮する (全コア並列・高圧縮。既存の出力先は上書きしない)
# Usage: zpack <dir_or_file> [output.tar.zst]
function zpack {
  [CmdletBinding()]
  param(
    [Parameter(Position = 0)][string]$Source,
    [Parameter(Position = 1)][string]$Output,
    [Alias('h')][switch]$Help
  )

  if ($Help -or $Source -eq '--help') {
    @'
Usage: zpack <dir_or_file> [output.tar.zst]

Existing output files are never overwritten.

Compression level:
  Set ZPACK_LEVEL to an integer between 1 and 22 (default: 19).
  Levels 20-22 automatically enable --ultra.

Examples:
  zpack mydir
  zpack mydir archive.tar.zst
  $env:ZPACK_LEVEL = 22; zpack mydir
'@
    return
  }
  if (-not $Source) {
    Write-Error 'Usage: zpack <dir_or_file> [output.tar.zst] (see: zpack --help)'
    return
  }
  if (-not (Test-Path -LiteralPath $Source)) {
    Write-Error "zpack: $Source : No such file or directory"
    return
  }
  # GNU tar は外部の zstd を呼ぶ。bsdtar は内蔵するが、使うかどうかをそろえるため、どちらも要求する
  if (-not (Test-ExternalCommand zstd)) {
    Write-Error 'zpack: zstd が PATH に無い (scoop install zstd)'
    return
  }
  $sourcePath = (Resolve-Path -LiteralPath $Source).ProviderPath.TrimEnd('\')
  if (-not $Output) {
    $Output = (Split-Path -Leaf $sourcePath) + '.tar.zst'
  }
  $level = if ($env:ZPACK_LEVEL) { $env:ZPACK_LEVEL } else { '19' }
  if ($level -notmatch '^[0-9]+$') {
    Write-Error "zpack: ZPACK_LEVEL must be an integer (1-22): $level"
    return
  }
  if ([int]$level -lt 1 -or [int]$level -gt 22) {
    Write-Error "zpack: ZPACK_LEVEL out of range (1-22): $level"
    return
  }
  if (Test-Path -LiteralPath $Output) {
    Write-Error "zpack: $Output : already exists (not overwritten)"
    return
  }
  $outputPath = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).ProviderPath, $Output))
  # 出力先が圧縮対象の中だと一時ファイル自身を tar が取り込むので拒否する (例: zpack .)
  if (Test-Path -LiteralPath $sourcePath -PathType Container) {
    if ($outputPath.StartsWith($sourcePath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
      Write-Error "zpack: $Output : output is inside the source directory"
      return
    }
  }
  $outputDirectory = Split-Path -Parent $outputPath
  if (-not [System.IO.Directory]::Exists($outputDirectory)) {
    Write-Error "zpack: $outputDirectory : No such directory"
    return
  }
  # 出力先と同じ場所に、この呼び出し専用の作業ディレクトリ (他の何かと衝突しない名前) を作り、
  # そこへ書いてから、既存を上書きしない Move で出力先へ置く。作業ディレクトリだけを、必ず消す
  $workDirectory = [System.IO.Path]::Combine($outputDirectory, '.zpack-' + [System.Guid]::NewGuid().ToString('N'))
  $temporary = [System.IO.Path]::Combine($workDirectory, 'archive.tmp')
  $parent = Split-Path -Parent $sourcePath
  $name = Split-Path -Leaf $sourcePath
  if ((Get-TarFlavor) -eq 'gnu') {
    # -T0 は全コア。20 以上は --ultra が要る
    $zstdCommand = if ([int]$level -gt 19) { "zstd -T0 --ultra -$level" } else { "zstd -T0 -$level" }
    $compression = @('--force-local', "--use-compress-program=$zstdCommand")
  } else {
    $compression = @('--zstd', '--options', "zstd:compression-level=$level,zstd:threads=0")
  }
  try {
    $null = [System.IO.Directory]::CreateDirectory($workDirectory)
    & tar @compression -cf (ConvertTo-TarPath $temporary) -C (ConvertTo-TarPath $parent) $name
    if ($LASTEXITCODE -ne 0 -or -not [System.IO.File]::Exists($temporary)) {
      Write-Error "zpack: failed to create archive: $Output"
      return
    }
    try {
      # 既存の出力先は上書きしない (File.Move は既存があると失敗する)
      [System.IO.File]::Move($temporary, $outputPath)
    } catch {
      Write-Error "zpack: $Output : $($_.Exception.Message)"
      return
    }
    "Created: $Output"
  } finally {
    Remove-Item -LiteralPath $workDirectory -Recurse -Force -ErrorAction Ignore
  }
}

# tar.zst を展開する
# Usage: zunpack <archive.tar.zst> [output_dir]
function zunpack {
  [CmdletBinding()]
  param(
    [Parameter(Position = 0)][string]$Archive,
    [Parameter(Position = 1)][string]$Destination = '.',
    [Alias('h')][switch]$Help
  )

  if ($Help -or $Archive -eq '--help') {
    'Usage: zunpack <archive.tar.zst> [output_dir]'
    return
  }
  if (-not $Archive) {
    Write-Error 'Usage: zunpack <archive.tar.zst> [output_dir] (see: zunpack --help)'
    return
  }
  if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
    Write-Error "zunpack: $Archive : No such file"
    return
  }
  if ((Test-Path -LiteralPath $Destination) -and -not (Test-Path -LiteralPath $Destination -PathType Container)) {
    Write-Error "zunpack: $Destination : Not a directory"
    return
  }
  if (-not (Test-ExternalCommand zstd)) {
    Write-Error 'zunpack: zstd が PATH に無い (scoop install zstd)'
    return
  }
  try {
    $null = New-Item -ItemType Directory -Path $Destination -Force -ErrorAction Stop
  } catch {
    Write-Error "zunpack: failed to create directory: $Destination"
    return
  }
  $archivePath = ConvertTo-TarPath (Resolve-Path -LiteralPath $Archive).ProviderPath
  $destinationPath = ConvertTo-TarPath (Resolve-Path -LiteralPath $Destination).ProviderPath
  & tar @(Get-TarExtractOption -Zstd) -xf $archivePath -C $destinationPath
  if ($LASTEXITCODE -ne 0) {
    Write-Error "zunpack: failed to extract archive: $Archive"
  }
}
