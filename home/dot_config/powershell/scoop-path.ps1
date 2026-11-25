# ssh 経由のセッションで、scoop の `current` (junction) を辿れない問題への対処。
# profile.ps1 が `$env:SSH_CONNECTION` のあるときだけ dot-source する。起動経路で読まれるため、
# profile.ps1 冒頭の制約 (cmdlet を使わない) に従い、.NET だけで書く。
# see docs/spec/shell.md#powershellプロファイル

# sshd は RedirectionGuard を有効にして動き、子のシェルも引き継ぐ。RedirectionGuard は、管理者でないユーザーが
# 作った junction を辿らせない。scoop の shim と PATH の `current` は junction を通るので、ssh では全部が
# `Shim: Could not create process` や「見つからない」になる。junction の実体のバージョンのディレクトリで置き換える。
#   1. PATH にある `apps\<app>\current` の項目は、その位置で実体へ置き換える (優先順位を変えない)。
#      入れ子のシェルが引き継いだ、前の版の実体の項目 (`apps\<app>\<版>`) も、最新の実体へ置き換える。
#   2. shim の指す先のディレクトリ (`.shim` の path の親) を、scoop の shims の直前へ足す。
#      直前なので、ローカルと同じ優先順位 (shims より前の Windows 標準のコマンドが先) を保つ。
#      shim の無いディレクトリは足さない。
# `current` が壊れている (実体が無い)・無いアプリは対象にしない。失敗しても PATH は変えず、警告だけ出す。
# ResolveLinkTarget は .NET 6+ (PowerShell 7.2 以降) だけ。sshd の既定シェルは pwsh 7 (docs/spec/windows-admin.md)。
function Add-ScoopRealPathEntry {
  if ($null -eq [System.IO.Directory].GetMethod('ResolveLinkTarget')) {
    return
  }
  try {
    $scoopRoot = $env:SCOOP
    if ([string]::IsNullOrEmpty($scoopRoot)) {
      $scoopRoot = [System.IO.Path]::Combine($env:USERPROFILE, 'scoop')
    }
    $appsDirectory = [System.IO.Path]::Combine($scoopRoot, 'apps')
    if ([string]::IsNullOrEmpty($env:Path) -or -not [System.IO.Directory]::Exists($appsDirectory)) {
      return
    }

    # app 名 -> `current` の実体 (バージョンのディレクトリ)
    $realVersions = [System.Collections.Generic.Dictionary[string, string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($appDirectory in [System.IO.Directory]::GetDirectories($appsDirectory)) {
      try {
        $target = [System.IO.Directory]::ResolveLinkTarget([System.IO.Path]::Combine($appDirectory, 'current'), $false)
      } catch {
        continue
      }
      if ($null -ne $target -and [System.IO.Directory]::Exists($target.FullName)) {
        $realVersions[[System.IO.Path]::GetFileName($appDirectory)] = $target.FullName
      }
    }
    if ($realVersions.Count -eq 0) {
      return
    }

    # `apps\<app>\(current|<版>)\<その下>` を `<実体>\<その下>` にする。対象でなければ $null
    $appsPrefix = $appsDirectory.TrimEnd('\') + '\'
    $toReal = {
      param([string]$path)
      if (-not $path.StartsWith($appsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $null
      }
      $parts = $path.Substring($appsPrefix.Length).Split([char]'\', 3)
      if ($parts.Length -lt 2 -or -not $realVersions.ContainsKey($parts[0])) {
        return $null
      }
      if ($parts.Length -ge 3) {
        return $realVersions[$parts[0]] + '\' + $parts[2]
      }
      return $realVersions[$parts[0]]
    }

    # ssh のセッションは、ユーザー PATH の未展開の `%VAR%` をそのまま渡すことがある
    $shimsDirectory = [System.IO.Path]::Combine($scoopRoot, 'shims').TrimEnd('\')
    $entries = [System.Collections.Generic.List[string]]::new()
    $shimsIndex = -1
    foreach ($entry in $env:Path.Split(';')) {
      if ($entry.Length -eq 0) {
        continue
      }
      $expanded = [System.Environment]::ExpandEnvironmentVariables($entry).TrimEnd('\')
      if ($shimsIndex -lt 0 -and $expanded -eq $shimsDirectory) {
        $shimsIndex = $entries.Count
        $entries.Add($entry)
        continue
      }
      $real = & $toReal $expanded
      if ($null -ne $real) {
        $entries.Add($real)
      } else {
        $entries.Add($entry)
      }
    }

    if ($shimsIndex -ge 0 -and [System.IO.Directory]::Exists($shimsDirectory)) {
      $present = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
      foreach ($entry in $entries) {
        [void]$present.Add([System.Environment]::ExpandEnvironmentVariables($entry).TrimEnd('\'))
      }
      $shimDirectories = [System.Collections.Generic.List[string]]::new()
      foreach ($shimFile in [System.IO.Directory]::GetFiles($shimsDirectory, '*.shim')) {
        foreach ($line in [System.IO.File]::ReadLines($shimFile)) {
          if ($line -match '^\s*path\s*=\s*"?([^"]+?)"?\s*$') {
            $real = & $toReal ([System.IO.Path]::GetDirectoryName($Matches[1]))
            if ($null -ne $real -and $present.Add($real)) {
              $shimDirectories.Add($real)
            }
            break
          }
        }
      }
      $entries.InsertRange($shimsIndex, $shimDirectories)
    }

    $env:Path = $entries -join ';'
  } catch {
    Write-Warning "Failed to resolve the scoop junctions: $_"
  }
}
