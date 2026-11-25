# bash / zsh の対話設定 (環境変数・履歴・補完・cd の挙動・snippet) を、PSReadLine と PowerShell の仕組みで再現する。
# 対話セッションだけで読み込む (profile.ps1 が -EditMode の後で読む。-EditMode は割り当てを初期化するので、ここでは触らない)。
# 起動時間を増やさないため、次の方針にしている (ファイルを 1 つ読むごとに約 16 ms かかる)。
#   - 関数は commands/ でなく modules/ の小さなモジュールに置き、使うときに自動で読み込む
#     (PSModulePath に足したので、`zpack` などを初めて呼んだときに PowerShell が自動で Import-Module する)。
#   - 外部コマンドの有無は、起動時に PATH を調べず、使う時点か、使えなければ代替へ落ちるコマンドで決める。
#   - 補完は、使うときまで生成も読み込みもしない (スタブ)。
# PSReadLine 2.1 以降 (PowerShell 7) の機能は、無い環境 (Windows PowerShell 5.1) では黙って飛ばす。
# see docs/spec/shell.md#bashzsh-と-powershell-の対応

# PATH から実行ファイルを探して、見つかったパスを返す (無ければ $null)。関数・エイリアスは数えない。
# Get-Command は PATH 全体を走査して 0.1 秒以上かかるので、.NET で探す (数 ms)。モジュールの関数からも使う
function Find-Executable {
  param([Parameter(Mandatory)][string]$Name)

  foreach ($directory in $env:Path.Split(';')) {
    if (-not $directory) {
      continue
    }
    foreach ($extension in '.exe', '.cmd', '.bat', '.com') {
      try {
        $candidate = [System.IO.Path]::Combine($directory, $Name + $extension)
        if ([System.IO.File]::Exists($candidate)) {
          return $candidate
        }
      } catch {
        # PATH の要素に使えない文字があるときは、その要素を飛ばす
        break
      }
    }
  }
}

# 外部コマンド (実行ファイル) があるか
function Test-ExternalCommand {
  param([Parameter(Mandatory)][string]$Name)

  $null -ne (Find-Executable -Name $Name)
}

#--------------------#
# 関数のモジュール   #
#--------------------#

# modules/ の ShellShortcuts・ShellGit・ShellArchive・ShellCpp・ShellPi・ShellPk・ShellSnippets (と個人用の PersonalShell) は、
# PSModulePath にあるので、含まれる関数を初めて呼んだときに自動で読み込まれる (manifest の FunctionsToExport が一覧)。
$modulePath = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($PSScriptRoot, '..', 'modules'))
if (-not ($env:PSModulePath -split ';' -contains $modulePath)) {
  $env:PSModulePath = "$modulePath;$env:PSModulePath"
}

# PowerShell の cat は Get-Content のエイリアスで、PATH の外部の cat.exe (Git・gow) より先に解決される。bat を使う cat
# (ShellShortcuts の Invoke-ShellCat) を効かせるため、エイリアスを外して、その関数を呼ぶ cat を定義する。
# (モジュールの関数は、外部の実行ファイルより後に解決されるので、cat.exe に負ける。そのため、ここで定義する)
# (Test-Path / Remove-Item は Management モジュールの読み込みを伴い、起動が遅れるので、プロバイダーを直接呼ぶ)
if ($ExecutionContext.InvokeProvider.Item.Exists('Alias:\cat')) {
  $ExecutionContext.InvokeProvider.Item.Remove('Alias:\cat', $false)
}
# `pk` (補助スクリプトの短い入口)。~/.local/bin/pk という拡張子の無いファイル (Python) が PATH にあり、自動読み込みの
# 関数より先に解決される (実行できずに「関連付け」を聞かれる) ので、ここで定義する。実体は ShellPk の Invoke-ShellPk
function pk { Invoke-ShellPk @args }

function cat {
  if ($MyInvocation.ExpectingInput) {
    $input | Invoke-ShellCat @args
  } else {
    Invoke-ShellCat @args
  }
}

# zsh の `dirs -v` (auto_pushd のスタック)。PowerShell の pushd / popd のスタックを番号つきで出す。
# 場所のスタックは SessionState ごとなので、モジュールの関数ではなく、ここ (グローバル) に置く
function dirs {
  $index = 0
  foreach ($location in @(Get-Location) + @(Get-Location -Stack)) {
    '{0,2}  {1}' -f $index, $location.Path
    $index++
  }
}

#------------#
# 環境変数   #
#------------#

# less の既定のオプション (Linux の shellrc.sh と同じ)
if (-not $env:LESS) {
  $env:LESS = '-iMR -gSW -z-4 -x4'
}

# fzf の既定のコマンドとプレビュー (Linux の fzf/core.sh と同じ)。fzf は cmd.exe で実行するので、
# 使う道具 (rg・bat・eza) が無いときは `||` で標準のコマンドへ落ちる (起動時に PATH を調べない)
if (-not $env:FZF_CTRL_R_OPTS) {
  $env:FZF_CTRL_R_OPTS = '--sort --exact'
}
if (-not $env:FZF_DEFAULT_COMMAND) {
  $env:FZF_DEFAULT_COMMAND = 'rg --files --hidden --follow --glob "!.git/*" 2>nul || dir /s /b /a-d'
}
if (-not $env:FZF_CTRL_T_OPTS) {
  $env:FZF_CTRL_T_OPTS = '--preview "bat --color=always --style=header,grid --line-range :100 {} 2>nul || type {}"'
}
if (-not $env:FZF_ALT_C_OPTS) {
  $env:FZF_ALT_C_OPTS = '--preview "eza -T -L 2 --color=always {} 2>nul || dir /b {}" --select-1 --exit-0'
}

#------#
# 履歴 #
#------#

if (Get-Module PSReadLine) {
  # zsh の HISTSIZE=100000 / hist_ignore_all_dups (保存されるファイルは常に全件で、これはメモリ上の件数)、
  # hist_ignore_space (先頭が空白のコマンドは履歴に残さない。既定のハンドラが除く、秘密らしい語を含む行は、
  # メモリだけに残す扱いを保つ)、zsh-autosuggestions (履歴からの候補を入力の右に薄く出す。右矢印・Ctrl+f・End で確定、
  # Alt+f で 1 語だけ確定)。1 回の呼び出しにまとめる (呼び出しごとに数 ms かかる)。
  # 候補の表示は PSReadLine 2.1 以降 (PowerShell 7 の標準) だけ。2.0 (Windows PowerShell 5.1 の標準) には無い
  # (無いパラメーターを try/catch で受けると $Error に残るので、版で判定する)
  $readLineOptions = @{
    MaximumHistoryCount = 100000
    HistoryNoDuplicates = $true
    AddToHistoryHandler = {
      param([string]$line)

      if ($line.StartsWith(' ')) {
        return $false
      }
      if ($line -match 'password|asplaintext|token|apikey|secret') {
        $option = 'Microsoft.PowerShell.AddToHistoryOption' -as [type]
        if ($option) {
          return [System.Enum]::Parse($option, 'MemoryOnly')
        }
        return $false
      }
      $true
    }
  }
  if ((Get-Module PSReadLine).Version -ge [version]'2.1.0') {
    $readLineOptions.PredictionSource = 'History'
    $readLineOptions.PredictionViewStyle = 'InlineView'
  }
  Set-PSReadLineOption @readLineOptions
}

#---------------------#
# auto_cd (cdpath つき) #
#---------------------#

# zsh の `setopt auto_cd` と `cdpath=(.. ~)`、bash の `shopt -s autocd`: ディレクトリ名だけを入力すると cd する。
# 探す場所は、カレント・その親 (..)・ホーム (~) の順。`..` と `...` (`../..`) と `~` も使える。
# スクリプトや関数の中から呼ばれた (CommandOrigin が Internal の) ときは何もしない:
# 存在しないコマンドをディレクトリ名で取り違えて、黙って移動しないため。
# (クロージャは、1 つにつき約 2 ms かかるので、前のハンドラはグローバル変数に持つ。
# 再読み込みで、前のハンドラが自分自身を指して再帰しないよう、自分のものは前のハンドラにしない。
# CommandNotFoundAction / LocationChangedAction は、代入したスクリプトブロックではなく、変換されたデリゲートを返すので、
# 登録後に読み戻したデリゲートを `...Installed` に控えて比べる)
# 引数つきの入力 (`build --help` など) は移動せず、通常のコマンドの未検出のエラーにする
# (zsh の auto_cd も、ディレクトリ名だけの 1 語のときだけ動く)。ファイルシステムの外 (レジストリなど) では何もしない。
$autoCdCurrent = $ExecutionContext.InvokeCommand.CommandNotFoundAction
if (-not [object]::ReferenceEquals($autoCdCurrent, $global:AutoCdInstalled)) {
  $global:AutoCdPrevious = $autoCdCurrent
}
$global:AutoCdHandler = {
  param([string]$commandName, [System.Management.Automation.CommandLookupEventArgs]$lookup)

  $handled = $false
  try {
    if ($lookup.CommandOrigin -eq [System.Management.Automation.CommandOrigin]::Runspace -and
      $commandName -notmatch '^-' -and $commandName.IndexOfAny([char[]]'*?[]') -lt 0 -and
      (Get-Location).Provider.Name -eq 'FileSystem') {
      $target = $null
      $here = (Get-Location).ProviderPath
      if ($commandName -match '^\.{3,}$') {
        # `...` は ../.. 、`....` は ../../..
        $target = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($here, ('..\' * ($commandName.Length - 1))))
      } elseif ($commandName -eq '~' -or $commandName.StartsWith('~/') -or $commandName.StartsWith('~\')) {
        $target = [System.IO.Path]::Combine($HOME, $commandName.Substring(1).TrimStart('/', '\'))
      } elseif ([System.IO.Path]::IsPathRooted($commandName)) {
        $target = $commandName
      } else {
        foreach ($base in $here, [System.IO.Path]::Combine($here, '..'), $HOME) {
          $candidate = [System.IO.Path]::Combine($base, $commandName)
          if ([System.IO.Directory]::Exists($candidate)) {
            $target = $candidate
            break
          }
          # `./x` や `../x` は、カレントからだけ探す
          if ($commandName.StartsWith('.')) {
            break
          }
        }
      }
      if ($target -and [System.IO.Directory]::Exists($target)) {
        $resolved = [System.IO.Path]::GetFullPath($target)
        $lookup.CommandScriptBlock = {
          if ($args.Count -gt 0) {
            throw [System.Management.Automation.CommandNotFoundException]::new(
              "The term '$commandName' is not recognized as a name of a cmdlet, function, script file, or executable program.")
          }
          Set-Location -LiteralPath $resolved
        }.GetNewClosure()
        $lookup.StopSearch = $true
        $handled = $true
      }
    }
  } catch {
    # パスの解決に失敗した (不正な文字など) ときは、何もしない
    $handled = $false
  }
  if (-not $handled -and $global:AutoCdPrevious) {
    $global:AutoCdPrevious.Invoke($commandName, $lookup)
  }
}
$ExecutionContext.InvokeCommand.CommandNotFoundAction = $global:AutoCdHandler
$global:AutoCdInstalled = $ExecutionContext.InvokeCommand.CommandNotFoundAction

#------------------------------#
# chpwd: cd のたびに一覧を出す #
#------------------------------#

# zsh の `chpwd()` (cd のたびに lsd か ls を出す)。標準出力が端末のときだけ出す。
# 先に登録された LocationChangedAction (リポジトリごとの TEMP の追従。profile.ps1) は、残して先に呼ぶ。
# PowerShell 6 以降 (LocationChangedAction がある環境) だけ。
if ($PSVersionTable.PSVersion.Major -ge 6) {
  $chpwdCurrent = $ExecutionContext.InvokeCommand.LocationChangedAction
  if (-not [object]::ReferenceEquals($chpwdCurrent, $global:ChpwdInstalled)) {
    $global:ChpwdPrevious = $chpwdCurrent
  }
  $global:ChpwdHandler = {
    param($sender, $eventArgs)

    if ($global:ChpwdPrevious) {
      $global:ChpwdPrevious.Invoke($sender, $eventArgs)
    }
    if ($global:ChpwdSuppress -or [Console]::IsOutputRedirected) {
      return
    }
    # eza があれば色つきの格子。無ければ名前だけの格子 (Get-ChildItem の表の見出しは出さない)
    $eza = Find-Executable -Name eza
    if ($eza) {
      & $eza --color=always --grid --width ([Console]::WindowWidth) | Out-Host
    } else {
      Get-ChildItem -Name | Format-Wide -AutoSize | Out-Host
    }
  }
  $ExecutionContext.InvokeCommand.LocationChangedAction = $global:ChpwdHandler
  $global:ChpwdInstalled = $ExecutionContext.InvokeCommand.LocationChangedAction
}

#---------------------------------------#
# snippet (zeno のキーワード展開) のキー #
#---------------------------------------#

# 定義は ~/.config/powershell/snippets.json (home/dot_config/zeno/*.yml から chezmoi が生成する。YAML は zsh の zeno と共通)。
# 展開と選択の関数は ShellSnippets (初めてキーを押したときに自動で読み込まれる)。
#   Space              カーソルの左の語がキーワード (例: `gs,`) なら、snippet へ展開する。展開しなければ、ふつうの空白を入れる
#   Ctrl+x, Ctrl+s     snippet を fzf で選んで、カーソルの位置へ入れる
# zeno の Enter での展開 (zeno-auto-snippet-and-accept-line) は、oh-my-posh が Enter のハンドラを持つので、置き換えない。
if ((Get-Module PSReadLine) -and $PSVersionTable.PSVersion.Major -ge 6) {
  Set-PSReadLineKeyHandler -Chord 'Spacebar' -BriefDescription 'ExpandSnippet' `
    -Description 'zeno のように、キーワード (gs, など) を snippet へ展開する' -ScriptBlock {
    # キーワードは `,` で終わる (zeno の YAML の約束)。左の語が `,` で終わるときだけ、モジュール (ShellSnippets) を読んで展開する
    # (ふつうの空白のたびにモジュールを読み込んで、最初の入力を遅らせない)。展開に失敗しても、空白は必ず入れる
    $expanded = $false
    $line = $null
    $cursor = 0
    [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
    if ($cursor -gt 0 -and $line[$cursor - 1] -eq ',') {
      try {
        $expanded = Expand-Snippet
      } catch {}
    }
    if (-not $expanded) {
      [Microsoft.PowerShell.PSConsoleReadLine]::Insert(' ')
    }
  }
  Set-PSReadLineKeyHandler -Chord 'Ctrl+x,Ctrl+s' -BriefDescription 'InsertSnippet' `
    -Description 'snippet を fzf で選んで入れる' -ScriptBlock {
    Select-Snippet
    [Microsoft.PowerShell.PSConsoleReadLine]::InvokePrompt()
  }
}

#------#
# 補完 #
#------#

# bash / zsh の補完 (compinit・zsh-completions・docker と mise の補完) に相当する。
# 各ツールが出す PowerShell 用の補完スクリプト (`gh completion -s powershell` など) を使い、
# 起動時には仮の補完 (スタブ) を登録するだけにする。そのコマンドで初めて Tab を押したとき、
# 補完スクリプトを生成してキャッシュし (実行ファイルが変わるまで再生成しない。cache.ps1)、
# スクリプトが登録しようとする補完のスクリプトブロックを横取りして、以後はスタブがそれを呼ぶ。
# (本物の登録でスタブを置き換える方式は、cobra 製のスクリプト (gh・chezmoi) の登録先がスタブと
# 別になり、効かなかったので採らない。スクリプトの内容はそのまま使い、登録だけを奪う)
# 補完スクリプトは大きい (uv は 750 KB) ので、使うときまで読み込まない。
# スタブは全ツールで 1 つ (ツールごとにクロージャを作ると、1 つにつき約 2 ms かかる)。ツール名は、入力の先頭の語から取る。
# 生成のコマンドの引数は $LazyCompletionSpecs (ツール名 → 引数)。
$global:LazyCompletionSpecs = @{
  gh = 'completion', '-s', 'powershell'
  chezmoi = 'completion', 'powershell'
  docker = 'completion', 'powershell'
  mise = 'completion', 'powershell'
  uv = 'generate-shell-completion', 'powershell'
  uvx = '--generate-shell-completion', 'powershell'
  rg = '--generate', 'complete-powershell'
  fd = '--gen-completions', 'powershell'
  herdr = 'completion', 'powershell'
}
$global:LazyCompletionStub = {
  param($wordToComplete, $commandAst, $cursorPosition)

  # `gh` と `gh.exe` はツール名にする。パスつき (`C:\x\gh.exe`・`.\gh`) は、PATH の同名の別の実行ファイルの
  # 補完を出してしまうので、補完しない
  $typed = $commandAst.CommandElements[0].Extent.Text.Trim('"', "'")
  if ($typed.IndexOfAny([char[]]'/\') -ge 0) {
    return
  }
  $name = [System.IO.Path]::GetFileNameWithoutExtension($typed).ToLowerInvariant()
  $blocks = Get-Variable -Name LazyCompletionBlocks -Scope Global -ValueOnly -ErrorAction Ignore
  if ($null -eq $blocks) {
    $blocks = @{}
    Set-Variable -Name LazyCompletionBlocks -Scope Global -Value $blocks
  }
  if (-not $blocks.ContainsKey($name)) {
    # 失敗しても、同じコマンドで何度も生成し直さない
    $blocks[$name] = $null
    $arguments = $global:LazyCompletionSpecs[$name]
    if ($arguments) {
      # 補完の登録を含まない出力 (使い方の表示やエラー) は、キャッシュしない
      $generator = {
        param([string]$Executable)
        $text = & $Executable @arguments | Out-String
        if ($text -match 'Register-ArgumentCompleter') { $text }
      }.GetNewClosure()
      $cache = Get-CachedInitScript -Name "completion-$name" -CommandName $name -Generator $generator
      if ($cache) {
        # cobra の補助関数・フィルター (`function __gh_debug`・`filter __gh_escapeStringWithSpecialChars`) は
        # 補完のブロックから使われる。入れ子のスコープで読むので、グローバルへ定義し直す。
        # 登録 (Register-ArgumentCompleter) は、ブロックを横取りする
        $script = [System.IO.File]::ReadAllText($cache) -replace '(?m)^(function|filter) (?!global:)', '$1 global:'
        function Register-ArgumentCompleter {
          param([string[]]$CommandName, [string]$ParameterName, [scriptblock]$ScriptBlock, [switch]$Native)
          $global:LazyCompletionCaptured = $ScriptBlock
        }
        $global:LazyCompletionCaptured = $null
        Invoke-Expression $script
        $blocks[$name] = $global:LazyCompletionCaptured
        $global:LazyCompletionCaptured = $null
      }
    }
  }
  $block = $blocks[$name]
  if ($block) {
    & $block $wordToComplete $commandAst $cursorPosition
  }
}

# 追加の登録 (試験・手元の拡張用)。生成のコマンドの引数を表へ足し、同じスタブで登録する
function Register-LazyCompletion {
  param(
    [Parameter(Mandatory)][string]$CommandName,
    [Parameter(Mandatory)][string[]]$GeneratorArguments
  )

  $global:LazyCompletionSpecs[$CommandName.ToLowerInvariant()] = $GeneratorArguments
  # -Native は、PowerShell が補完を持たない外部コマンドのための登録
  Register-ArgumentCompleter -Native -CommandName $CommandName -ScriptBlock $global:LazyCompletionStub
}

Register-ArgumentCompleter -Native -CommandName @($global:LazyCompletionSpecs.Keys) -ScriptBlock $global:LazyCompletionStub

# git: zsh の _git に相当する補完は posh-git が持つ。プロンプトは oh-my-posh なので、補完のためだけに、
# 初めて Tab を押したときに読み込む (入っていなければ何もしない)。posh-git が同じ (-Native) 登録でスタブを置き換え、
# その場の入力にも本物の結果を返す
Register-ArgumentCompleter -Native -CommandName git -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)

  $loaded = Get-Variable -Name LazyCompletionBlocks -Scope Global -ValueOnly -ErrorAction Ignore
  if ($null -eq $loaded) {
    $loaded = @{}
    Set-Variable -Name LazyCompletionBlocks -Scope Global -Value $loaded
  }
  if ($loaded.ContainsKey('git')) {
    return
  }
  $loaded['git'] = $null
  if (-not (Get-Module -ListAvailable -Name posh-git)) {
    return
  }
  Import-Module posh-git -Global
  $extent = $commandAst.Extent
  $inputText = $extent.Text
  $column = $cursorPosition - $extent.StartOffset
  if ($column -gt $inputText.Length) {
    $inputText = $inputText.PadRight($column)
  }
  [System.Management.Automation.CommandCompletion]::CompleteInput($inputText, $column, $null).CompletionMatches
}

# winget: Microsoft の公式の補完 (https://learn.microsoft.com/windows/package-manager/winget/tab-completion)
Register-ArgumentCompleter -Native -CommandName winget -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)

  [Console]::InputEncoding = [Console]::OutputEncoding = $OutputEncoding = [System.Text.Utf8Encoding]::new()
  $local:word = $wordToComplete.Replace('"', '""')
  $local:ast = $commandAst.ToString().Replace('"', '""')
  winget complete --word="$local:word" --commandline "$local:ast" --position $cursorPosition | ForEach-Object {
    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
  }
}

# ssh・scp・sftp: ~/.ssh/config の Host を補完する (zeno の `ssh hosts` の補完に相当する。`user@` の後ろも補完する)
Register-ArgumentCompleter -Native -CommandName ssh, scp, sftp -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)

  $config = [System.IO.Path]::Combine($HOME, '.ssh', 'config')
  if ($wordToComplete.StartsWith('-') -or -not [System.IO.File]::Exists($config)) {
    return
  }
  $user = ''
  $prefix = $wordToComplete
  $at = $wordToComplete.LastIndexOf('@')
  if ($at -ge 0) {
    $user = $wordToComplete.Substring(0, $at + 1)
    $prefix = $wordToComplete.Substring($at + 1)
  }
  [System.IO.File]::ReadAllLines($config) |
    ForEach-Object { if ($_ -match '^\s*Host\s+(.+?)\s*$') { $Matches[1] -split '\s+' } } |
    Where-Object { $_ -notmatch '[*?!]' -and $_.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) } |
    Select-Object -Unique |
    ForEach-Object {
      [System.Management.Automation.CompletionResult]::new("$user$_", "$user$_", 'ParameterValue', $_)
    }
}
