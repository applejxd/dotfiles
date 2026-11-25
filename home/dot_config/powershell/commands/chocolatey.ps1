# Chocolatey のプロファイル (refreshenv と choco の補完) は読み込みに 0.3 秒かかり、
# 起動の idle に置くと打鍵が止まる。仮の定義だけを置き、使われたときに読み込む。
# 読み込むと本物の refreshenv (エイリアス) と choco の補完が登録され、仮の定義より優先される。
# see docs/spec/shell.md#powershellプロファイル
function Register-ChocolateyLazyProfile {
  if ([string]::IsNullOrEmpty($env:ChocolateyInstall)) {
    return
  }
  if (-not [System.IO.File]::Exists("$env:ChocolateyInstall\helpers\chocolateyProfile.psm1")) {
    return
  }
  # プロファイルの再読み込み (`. $PROFILE`) で、読み込み済みの本物の補完を仮の補完で上書きしない
  if (Get-Module chocolateyProfile) {
    return
  }

  function global:refreshenv {
    Import-Module "$env:ChocolateyInstall\helpers\chocolateyProfile.psm1" -Scope Global -ErrorAction Stop
    Update-SessionEnvironment
  }

  Register-ArgumentCompleter -Native -CommandName choco -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    # -Force: 読み込み済みでも本物の補完を登録し直す。無いと、仮の補完が本物を上書きした状態で
    # Import-Module が何もせず、下の CompleteInput がこの補完へ戻って止まらなくなる
    try {
      Import-Module "$env:ChocolateyInstall\helpers\chocolateyProfile.psm1" -Scope Global -Force -ErrorAction Stop
    } catch {
      return
    }
    # 読み込むと本物の補完が同じ名前で登録されるので、入力全体をもう一度補完させる
    $root = $commandAst
    while ($root.Parent) {
      $root = $root.Parent
    }
    [System.Management.Automation.CommandCompletion]::CompleteInput(
      $root.Extent.Text, $cursorPosition, $null
    ).CompletionMatches
  }
}
