# PATH の読み直し (プロセス) と永続化 (User) の共通関数。
# 取り込み側は includeTemplate "powershell/env-path.ps1" で読み込む
# (波括弧の記法をここに書くと自分自身を再帰して取り込むため書かない)。
# 仕組みと注意は docs/spec/cli-management.md#windows-の-path-の扱い

function Update-PathFromEnvironment {
  # 同じ apply の winget / npm / 管理者権限の導入が増やした PATH を、このプロセスへ取り込む。
  # Machine → User → 現在の順に並べ、重複は先頭だけ残す。
  $seen = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
  )
  $env:Path = (
    @(
      [Environment]::GetEnvironmentVariable('Path', 'Machine'),
      [Environment]::GetEnvironmentVariable('Path', 'User'),
      $env:Path
    ) |
      Where-Object { $_ } |
      ForEach-Object { $_ -split ';' } |
      Where-Object { $_ } |
      ForEach-Object { if ($_.Contains('%')) { [Environment]::ExpandEnvironmentVariables($_) } else { $_ } } |
      Where-Object { $seen.Add($_.TrimEnd('\')) }
  ) -join ';'
}

function Send-EnvironmentChange {
  # 環境変数の変更を Explorer などへ通知する (WM_SETTINGCHANGE)。
  # 通知が無いと、起動済みの Explorer が古い環境のまま、そこから起動するアプリへ渡す。
  if (-not ('ChezmoiNative.EnvBroadcast' -as [type])) {
    Add-Type -Name EnvBroadcast -Namespace ChezmoiNative -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(
    System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam,
    uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@
  }
  $result = [UIntPtr]::Zero
  # HWND_BROADCAST = 0xFFFF, WM_SETTINGCHANGE = 0x1A, SMTO_ABORTIFHUNG = 0x2
  [void][ChezmoiNative.EnvBroadcast]::SendMessageTimeout(
    [IntPtr]0xFFFF, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result
  )
}

function Add-UserPathEntry {
  # User の PATH へ永続的に追記する。既にあれば追記しない (戻り値は追記したか)。
  # [Environment]::SetEnvironmentVariable と setx は REG_EXPAND_SZ を REG_SZ に降格させ、
  # PATH 内の %VAR% が展開されなくなるため、レジストリへ ExpandString で直接書く。
  # 既に降格している場合は、追記が無くても同じ値を ExpandString で書き直して直す。
  param([Parameter(Mandatory)][string]$Path)

  $normalized = $Path.TrimEnd('\')
  $appended = $false
  $dirty = $false
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
  try {
    $current = [string]$key.GetValue(
      'Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
    )
    $isExpand = $true
    if ($null -ne $key.GetValue('Path', $null)) {
      $isExpand = $key.GetValueKind('Path') -eq [Microsoft.Win32.RegistryValueKind]::ExpandString
    }
    $entries = @($current -split ';' | Where-Object { $_ })
    $known = @($entries | ForEach-Object { [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') })
    if ($known -notcontains $normalized) {
      $entries = @($entries + $normalized)
      $appended = $true
      $dirty = $true
    } elseif (-not $isExpand) {
      $dirty = $true
    }
    if ($dirty) {
      $key.SetValue('Path', ($entries -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    }
  } finally {
    $key.Dispose()
  }
  if ($dirty) { Send-EnvironmentChange }
  return $appended
}
