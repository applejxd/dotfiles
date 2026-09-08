Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# カバーを閉じたらスリープ
& powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 1
if ($LASTEXITCODE -ne 0) {
  throw "Failed to configure the DC lid action: $LASTEXITCODE"
}

& powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 1
if ($LASTEXITCODE -ne 0) {
  throw "Failed to configure the AC lid action: $LASTEXITCODE"
}
