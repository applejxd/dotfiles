Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 有効な電源プランへ毎回明示的に設定する (既定値と同じものも書く)。see docs/spec/structure.md#電源設定
# 単位は秒 (0 = なし)。LIDACTION は 0 = 何もしない / 1 = スリープ。
# 設定した値を、あとで読み取って確かめる (グループポリシーなどで上書きされていないか)
$script:Expected = @()

function Get-PowerValue {
  # powercfg /q の末尾の 2 つの 0x… が現在の AC・DC の値。表示の言語に依らない。設定が無い機種は $null
  param([string]$Subgroup, [string]$Setting)
  $lines = & powercfg /q SCHEME_CURRENT $Subgroup $Setting 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $lines) { return $null }
  $hex = @([regex]::Matches(($lines -join "`n"), '0x[0-9A-Fa-f]{8}') | ForEach-Object { [Convert]::ToInt64($_.Value, 16) })
  if ($hex.Count -lt 2) { return $null }
  return @{ Ac = $hex[$hex.Count - 2]; Dc = $hex[$hex.Count - 1] }
}

function Set-PowerValue {
  param(
    [string]$Subgroup,
    [string]$Setting,
    [int]$Ac,
    [int]$Dc = -1,
    [switch]$Optional
  )
  $script:Expected += , @{ Subgroup = $Subgroup; Setting = $Setting; Ac = $Ac; Dc = $Dc; Optional = [bool]$Optional }
  $steps = @(, @('/setacvalueindex', $Ac))
  if ($Dc -ge 0) { $steps += , @('/setdcvalueindex', $Dc) }
  foreach ($step in $steps) {
    & powercfg $step[0] SCHEME_CURRENT $Subgroup $Setting $step[1] | Out-Null
    if ($LASTEXITCODE -ne 0) {
      $message = "powercfg $($step[0]) $Subgroup $Setting failed: $LASTEXITCODE"
      if (-not $Optional) { throw $message }
      Write-Warning "$message (skipped)"
    }
  }
}

Set-PowerValue SUB_SLEEP STANDBYIDLE -Ac 0 -Dc 600
Set-PowerValue SUB_SLEEP HIBERNATEIDLE -Ac 0 -Dc 0
# AC は蓋を閉じても何もしない、バッテリーはスリープ。蓋の無い機種では設定が無い
Set-PowerValue SUB_BUTTONS LIDACTION -Ac 0 -Dc 1 -Optional
# 無人時 (ssh / RDP 中など) のスリープ。隠し設定なので GUID で指定する。AC のみ
Set-PowerValue SUB_SLEEP 7bc4a2f9-d8fc-4469-b07b-33eb785aaca0 -Ac 0 -Optional

& powercfg /setactive SCHEME_CURRENT
if ($LASTEXITCODE -ne 0) {
  throw "powercfg /setactive failed: $LASTEXITCODE"
}

# 読み取って確かめる。違えば警告する (apply は止めない)。設定が無い (蓋の無い機種など) は確かめない
$mismatch = @()
foreach ($e in $script:Expected) {
  $current = Get-PowerValue $e.Subgroup $e.Setting
  if ($null -eq $current) {
    if (-not $e.Optional) { $mismatch += "$($e.Setting): could not read" }
    continue
  }
  if ($current.Ac -ne $e.Ac) { $mismatch += "$($e.Setting) AC: expected $($e.Ac), actual $($current.Ac)" }
  if ($e.Dc -ge 0 -and $current.Dc -ne $e.Dc) { $mismatch += "$($e.Setting) DC: expected $($e.Dc), actual $($current.Dc)" }
}
if ($mismatch.Count -gt 0) {
  Write-Warning ('Power settings differ from the managed values (Group Policy or another tool may override them): ' + ($mismatch -join '; '))
}
