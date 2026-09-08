# GIT_CONFIG_* の不整合を取り除く。
#
# PowerShell の Env: プロバイダー (Test-Path / Get-Item / Get-ChildItem Env:) は
# Microsoft.PowerShell.Management の読み込みを伴い、これだけで 0.25 秒かかる。
# プロファイルの起動経路で使うため、同等の .NET API だけで実装する。
# なお空文字の環境変数は親プロセスから渡された場合のみ存在し、
# [Environment]::GetEnvironmentVariable は未設定を $null、空を '' で返す。
$gitConfigCount = 0
$invalidGitConfig = $false
# WSL/agent processes can forward GIT_CONFIG_COUNT without every indexed
# KEY/VALUE pair, which makes all Windows Git commands fail.
if ([int]::TryParse([Environment]::GetEnvironmentVariable('GIT_CONFIG_COUNT'), [ref]$gitConfigCount)) {
  for ($i = 0; $i -lt $gitConfigCount; $i++) {
    $gitConfigKey = [Environment]::GetEnvironmentVariable("GIT_CONFIG_KEY_$i")
    $gitConfigValue = [Environment]::GetEnvironmentVariable("GIT_CONFIG_VALUE_$i")
    if ($null -eq $gitConfigKey -or $null -eq $gitConfigValue) {
      $invalidGitConfig = $true
      break
    }
    # Python env restoration drops empty values on Windows. For fsmonitor,
    # "false" preserves the disabled state without breaking subsequent Git calls.
    if ($gitConfigKey -eq 'core.fsmonitor' -and $gitConfigValue -eq '') {
      [Environment]::SetEnvironmentVariable("GIT_CONFIG_VALUE_$i", 'false')
    }
  }
}
if ($invalidGitConfig) {
  foreach ($gitConfigName in @([Environment]::GetEnvironmentVariables().Keys)) {
    if ($gitConfigName -match '^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)$') {
      [Environment]::SetEnvironmentVariable($gitConfigName, $null)
    }
  }
}
