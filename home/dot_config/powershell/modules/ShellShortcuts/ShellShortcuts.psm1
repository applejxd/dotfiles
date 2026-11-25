# bash / zsh の shellrc.sh (alias と小さい関数) に相当するもの。対話セッションだけで読み込む。
# Windows PowerShell 5.1 と PowerShell 7 の両方で動かす。
# 外部コマンド (eza・bat・yazi など) は、定義時ではなく呼び出し時に探す。
# 起動時に Get-Command で PATH を走査しないため。無ければ PowerShell の標準の機能で代替する。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

# 外部コマンド (実行ファイル) があるか。関数・エイリアスは数えない
#--------------#
# ディレクトリ #
#--------------#

function up { Set-Location .. }
function upp { Set-Location ../.. }
function uppp { Set-Location ../../.. }

# `find . -type d -maxdepth 1 | grep PATTERN | tail -1` へ移動する
function jcd {
  param([Parameter(Position = 0)][string]$Pattern)

  if (-not $Pattern) {
    return
  }
  $directory = Get-ChildItem -Directory -Force |
    Where-Object { $_.Name -match $Pattern } |
    Select-Object -Last 1
  if ($directory) {
    Set-Location -LiteralPath $directory.FullName
  } else {
    'directory not found'
  }
}

# 2 階層までの空のディレクトリを消す (2 回走らせて、中身が空になった親も消す)
function cleanup {
  for ($pass = 0; $pass -lt 2; $pass++) {
    # 深いものから消す
    $directories = Get-ChildItem -Directory -Recurse -Depth 1 -Force -ErrorAction Ignore |
      Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $directories) {
      if (-not (Get-ChildItem -LiteralPath $directory.FullName -Force -ErrorAction Ignore | Select-Object -First 1)) {
        [System.IO.Directory]::Delete($directory.FullName)
        "removed '$($directory.FullName)'"
      }
    }
  }
}

#----------------------#
# ls (eza) と tree     #
#----------------------#

# eza の `-T -L 3 -a -I` に相当する素朴な木の表示。eza が無いときの代替
function Show-DirectoryTree {
  param(
    [string]$Path = '.',
    [int]$Depth = 3,
    [string[]]$Exclude = @('node_modules', '.git', '.cache', '.venv'),
    [string]$Prefix = ''
  )

  if ($Prefix -eq '' -and $Path -eq '.') {
    '.'
  }
  if ($Depth -le 0) {
    return
  }
  $items = @(
    Get-ChildItem -LiteralPath $Path -Force -ErrorAction Ignore |
      Where-Object { $Exclude -notcontains $_.Name } |
      Sort-Object @{ Expression = { -not $_.PSIsContainer } }, Name
  )
  for ($i = 0; $i -lt $items.Count; $i++) {
    $last = $i -eq $items.Count - 1
    $item = $items[$i]
    $Prefix + $(if ($last) { '└── ' } else { '├── ' }) + $item.Name
    if ($item.PSIsContainer) {
      Show-DirectoryTree -Path $item.FullName -Depth ($Depth - 1) -Exclude $Exclude `
        -Prefix ($Prefix + $(if ($last) { '    ' } else { '│   ' }))
    }
  }
}

# Linux の `ls=eza` と `ll` `la` `lla` `lal` `lt` `ltl`。標準の `ls` (Get-ChildItem) は
# パイプラインにオブジェクトを流すため、上書きしない。eza が無ければ Get-ChildItem で代替する
function ll { if (Test-ExternalCommand eza) { eza -l @args } else { Get-ChildItem @args } }
function la { if (Test-ExternalCommand eza) { eza -a @args } else { Get-ChildItem -Force @args } }
function lla { if (Test-ExternalCommand eza) { eza -la @args } else { Get-ChildItem -Force @args } }
function lal { lla @args }

function lt {
  if (Test-ExternalCommand eza) {
    eza -T -L 3 -a -I 'node_modules|.git|.cache|.venv' @args
  } else {
    Show-DirectoryTree @args
  }
}

function ltl {
  if (Test-ExternalCommand eza) {
    eza -T -L 3 -a -I 'node_modules|.git|.cache|.venv' -l @args
  } else {
    Show-DirectoryTree @args
  }
}

# `alias cat='bat --paging=never -p'`。bat があるときだけ、ファイルをそのまま見る呼び出し (オプションなし・入力なし) を
# bat にする。それ以外 (-Raw -Tail などのオプション・パイプライン) は Get-Content のまま。
# PowerShell の cat は Get-Content のエイリアスで、PATH の外部の cat.exe (Git・gow) より先に解決される。
# このモジュールの関数は、外部の実行ファイルより後に解決されるので、`cat` は interactive.ps1 が、
# エイリアスを外して、この関数を呼ぶ関数として定義する。
function Invoke-ShellCat {
  # オプションではなく、実在するファイルシステムのファイルだけを bat に任せる
  # (`cat Env:PATH` や `cat *.txt` のようなプロバイダーのパス・ワイルドカードは Get-Content のまま)
  $plain = -not $MyInvocation.ExpectingInput -and $args.Count -gt 0
  if ($plain) {
    foreach ($argument in $args) {
      $isFile = $false
      if ($argument -is [string] -and -not $argument.StartsWith('-')) {
        try {
          $isFile = [System.IO.File]::Exists($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($argument))
        } catch {}
      }
      if (-not $isFile) {
        $plain = $false
        break
      }
    }
  }
  if ($plain -and (Test-ExternalCommand bat)) {
    bat --paging=never -p @args
  } elseif ($MyInvocation.ExpectingInput) {
    $input | Get-Content @args
  } else {
    Get-Content @args
  }
}

# yazi の終了時に、移動したディレクトリへ cd する (yazi 公式の PowerShell 版と同じ)
function y {
  if (-not (Test-ExternalCommand yazi)) {
    Write-Error 'yazi が PATH に無い'
    return
  }
  $cwdFile = [System.IO.Path]::GetTempFileName()
  try {
    yazi @args --cwd-file="$cwdFile"
    $cwd = [System.IO.File]::ReadAllText($cwdFile).Trim()
    if ($cwd -and $cwd -ne (Get-Location).ProviderPath -and [System.IO.Directory]::Exists($cwd)) {
      Set-Location -LiteralPath $cwd
    }
  } finally {
    Remove-Item -LiteralPath $cwdFile -Force -ErrorAction Ignore
  }
}

#--------------#
# 小さい関数   #
#--------------#

# クリップボードの文字数 (`pbpaste | wc -m`)
function wcc { (Get-Clipboard -Raw).Length }

# クリップボードの書式を落として文字列だけにする (`pbpaste | pbcopy`)
function fcr { Set-Clipboard -Value (Get-Clipboard -Raw) }

# `find . -type f -print0 | xargs -0 grep -n PATTERN`。`パス:行:内容` の形で出す
function search {
  param(
    [Parameter(Mandatory, Position = 0)][string]$Pattern,
    [Parameter(Position = 1)][string]$Path = '.'
  )

  $root = (Resolve-Path -LiteralPath $Path).ProviderPath
  $base = $root.TrimEnd('\') + '\'
  Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction Ignore |
    Select-String -Pattern $Pattern |
    ForEach-Object {
      $file = if ($_.Path.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        $_.Path.Substring($base.Length)
      } else {
        $_.Path
      }
      '{0}:{1}:{2}' -f $file, $_.LineNumber, $_.Line
    }
}

# 文字列の SHA-1 (`echo -n "$1" | openssl sha1`)
function sha1 {
  param([Parameter(Mandatory, Position = 0)][string]$Text)

  $algorithm = [System.Security.Cryptography.SHA1]::Create()
  try {
    $bytes = $algorithm.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
    ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
  } finally {
    $algorithm.Dispose()
  }
}

#--------------------#
# fzf を使う関数     #
#--------------------#

# v: ~/.viminfo の最近のファイルを選んで vim で開く (複数選択できる。候補が 1 つなら即開く)
function v {
  $viminfo = @("$HOME/.viminfo", "$HOME/_viminfo") |
    Where-Object { [System.IO.File]::Exists($_) } |
    Select-Object -First 1
  if (-not $viminfo) {
    Write-Warning 'viminfo not found'
    return
  }
  $files = [System.IO.File]::ReadAllLines($viminfo) |
    Where-Object { $_.StartsWith('>') } |
    ForEach-Object { $_.Substring(2) -replace '^~', $HOME } |
    Where-Object { [System.IO.File]::Exists($_) }
  # 空の引数は Windows PowerShell 5.1 だと外部コマンドへ渡らないので、あるときだけ -q を足す
  $fzfArguments = @('-m', '-1')
  if ($args) {
    $fzfArguments += '-q', ($args -join ' ')
  }
  $selected = @($files | fzf @fzfArguments)
  if ($selected) {
    vim @selected
  }
}

# shellf: 起動するシェルを選ぶ (Linux の /etc/shells に相当する候補を、入っているものから出す)
function shellf {
  $shells = 'pwsh', 'powershell', 'cmd', 'bash', 'wsl' |
    Where-Object { Get-Command $_ -CommandType Application -ErrorAction Ignore }
  $fzfArguments = @()
  if ($args) {
    $fzfArguments += '-q', ($args -join ' ')
  }
  $shell = $shells | fzf @fzfArguments
  if ($shell) {
    & $shell
  }
}

# mise-select: mise の版を選んで `mise use` する。例: mise-select node
function mise-select {
  param([Parameter(Position = 0)][string]$Tool)

  if (-not $Tool) {
    return
  }
  $version = mise ls-remote $Tool | fzf --tac
  if ($version) {
    mise use "$Tool@$version"
  }
}
