# zeno の snippet (キーワードの展開) に相当する。対話セッションだけで読み込む。
# 定義は ~/.config/powershell/snippets.json (home/dot_config/zeno/*.yml から chezmoi が生成する。
# 元の YAML は zsh の zeno と共通)。PowerShell 7 の PSReadLine のキーで展開する。
#   Space (Spacebar)   カーソルの左の語がキーワード (例: `gs,`) なら、snippet へ展開する。
#                      展開しなければ、ふつうの空白を入れる。
#   Ctrl+x, Ctrl+s     snippet を fzf で選んで、カーソルの位置へ入れる。
# 展開後、`{{名前}}` の最初のものは消して、カーソルをそこへ置く (残りはそのまま。手で直す)。
# `evaluate: true` の snippet は、PowerShell として実行した出力で置き換える (例: `git checkout b,` → 今のブランチ名)。
# zeno の Enter での展開 (zeno-auto-snippet-and-accept-line) は、oh-my-posh が Enter のハンドラを持つので、置き換えない。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

# 定義を読む (最初に使うときだけ。無い・壊れているときは空)
function Get-SnippetTable {
  $variable = Get-Variable -Name SnippetTable -Scope Global -ValueOnly -ErrorAction Ignore
  if ($null -ne $variable) {
    return $variable
  }
  $table = @()
  $file = [System.IO.Path]::Combine($PSScriptRoot, '..', '..', 'snippets.json')
  if ([System.IO.File]::Exists($file)) {
    try {
      $table = @((Get-Content -LiteralPath $file -Raw | ConvertFrom-Json).snippets)
    } catch {
      Write-Warning "Failed to read the snippets: $_"
    }
  }
  Set-Variable -Name SnippetTable -Scope Global -Value $table
  $table
}

# snippet のテキストを作る。evaluate の snippet は実行した出力にする。失敗・空のときは $null
function Resolve-SnippetText {
  param([Parameter(Mandatory)]$Snippet)

  if ($Snippet.evaluate) {
    try {
      $evaluated = (& ([scriptblock]::Create($Snippet.snippet)) | Out-String).Trim()
      if ($evaluated) {
        return $evaluated
      }
    } catch {}
    return $null
  }
  $Snippet.snippet
}

# カーソルの左の語がキーワードなら展開して $true を返す
function Expand-Snippet {
  $line = $null
  $cursor = 0
  [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
  $left = $line.Substring(0, $cursor)
  if ($left -notmatch '(\S+)$') {
    return $false
  }
  $keyword = $Matches[1]
  $before = $left.Substring(0, $left.Length - $keyword.Length)
  foreach ($snippet in @(Get-SnippetTable)) {
    if ($snippet.keyword -cne $keyword) {
      continue
    }
    # context が無いキーワードは、行頭 (空白を除く) でだけ展開する
    $lbuffer = if ($snippet.context) { $snippet.context.lbuffer } else { $null }
    if ($lbuffer) {
      if ($before -notmatch $lbuffer) { continue }
    } elseif ($before.Trim()) {
      continue
    }
    $text = Resolve-SnippetText -Snippet $snippet
    if ($null -eq $text) {
      # 評価に失敗した (例: detached HEAD の `git checkout b,`)。バッファは変えず、展開しなかったことにする
      return $false
    }
    $cursorOffset = $text.Length
    $placeholder = [regex]::Match($text, '\{\{[^{}]*\}\}')
    if ($placeholder.Success) {
      $cursorOffset = $placeholder.Index
      $text = $text.Remove($placeholder.Index, $placeholder.Length)
    }
    [Microsoft.PowerShell.PSConsoleReadLine]::Replace($before.Length, $keyword.Length, $text)
    [Microsoft.PowerShell.PSConsoleReadLine]::SetCursorPosition($before.Length + $cursorOffset)
    return $true
  }
  $false
}

# snippet を選んで、カーソルの位置へ入れる (zeno-insert-snippet)
function Select-Snippet {
  $candidates = @(Get-SnippetTable | ForEach-Object { "$($_.keyword)`t$($_.name)`t$($_.snippet)" })
  if (-not $candidates) {
    return
  }
  $selected = $candidates | fzf --delimiter "`t" --with-nth '1,2' --preview 'echo {3}' --prompt 'Snippet> '
  if (-not $selected) {
    return
  }
  $keyword = ($selected -split "`t")[0]
  $snippet = @(Get-SnippetTable) | Where-Object { $_.keyword -ceq $keyword } | Select-Object -First 1
  $text = Resolve-SnippetText -Snippet $snippet
  if ($null -eq $text) {
    return
  }
  [Microsoft.PowerShell.PSConsoleReadLine]::Insert(($text -replace '\{\{[^{}]*\}\}', ''))
}
