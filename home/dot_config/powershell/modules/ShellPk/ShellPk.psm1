# pk (使い捨ての補助スクリプトの短い入口) の PowerShell 版。bash / zsh の `pk` コマンドに相当する。
# 本体は ~/.local/bin/pk (Python。home/dot_local/bin/executable_pk)。Windows は拡張子の無いファイルを
# 実行できないので、関数から python で呼ぶ。入口の *.sh は sh で実行されるので、PATH に sh が無ければ、
# Git for Windows の sh を、この呼び出しの間だけ PATH へ足す。
# `pk` は interactive.ps1 が、この関数を呼ぶ関数として定義する (~/.local/bin/pk という拡張子の無いファイルが PATH にあり、
# 自動読み込みの関数より先に解決されてしまうため)。
# see docs/spec/development.md#補助スクリプトの短い入口pk

function Invoke-ShellPk {
  $script = [System.IO.Path]::Combine($HOME, '.local', 'bin', 'pk')
  if (-not [System.IO.File]::Exists($script)) {
    Write-Error "pk: $script が無い (chezmoi apply で配られる)"
    return
  }
  $python = Get-Command python, py -CommandType Application -ErrorAction Ignore | Select-Object -First 1
  if (-not $python) {
    Write-Error 'pk: python が PATH に無い'
    return
  }
  $originalPath = $env:Path
  $gitSh = [System.IO.Path]::Combine($env:ProgramFiles, 'Git', 'bin')
  if (-not (Test-ExternalCommand sh) -and [System.IO.File]::Exists([System.IO.Path]::Combine($gitSh, 'sh.exe'))) {
    $env:Path = "$gitSh;$env:Path"
  }
  # Python の標準出力は、Windows では端末のコードページ (cp932) になる。UTF-8 で受けるため、呼び出しの間だけ指定する
  $originalUtf8 = $env:PYTHONUTF8
  $env:PYTHONUTF8 = '1'
  try {
    & $python.Source $script @args
  } finally {
    $env:Path = $originalPath
    $env:PYTHONUTF8 = $originalUtf8
  }
}
