Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 有効な電源プランへ毎回明示的に設定する (既定値と同じものも書く)。see docs/spec/structure.md#電源設定
# 単位は秒 (0 = なし)。LIDACTION は 0 = 何もしない / 1 = スリープ。
function Set-PowerValue {
  param(
    [string]$Subgroup,
    [string]$Setting,
    [int]$Ac,
    [int]$Dc = -1,
    [switch]$Optional
  )
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
