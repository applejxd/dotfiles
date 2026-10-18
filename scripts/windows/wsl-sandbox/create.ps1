<#
  .SYNOPSIS
    隔離 GPU サンドボックス用の WSL2 ディストロを作る (Docker + Tailscale SSH)

  .DESCRIPTION
    手動で実行する。chezmoi apply では実行されない。
    Ubuntu 24.04 の公式 rootfs を取り込み、Windows のドライブと interop を切ったうえで、
    Docker Engine / nvidia-container-toolkit / Tailscale を入れ、リモートから
    `ssh <User>@<TailnetHostname>` で使える状態にする。
    同名のディストロがあれば何もせず中止する (削除は手動)。
    管理者権限は要らない (スケジュールタスクの登録に失敗した場合のみ警告する)。
    Tailscale のログインは表示された URL をブラウザで開く。ACL の SSH ルールは管理画面で手動変更する。

    see docs/spec/wsl-sandbox.md
#>
[CmdletBinding()]
param(
  # PowerShell・sed・タスク引数へそのまま渡すため、英数字・_・- だけを許す
  [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]*$')][string]$Name = 'sandbox',
  [ValidatePattern('^[a-z][a-z0-9_-]*$')][string]$User = 'sbx',
  [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9-]*$')][string]$TailnetHostname = 'sandbox-gpu',
  [string]$InstallDir,
  # コンテナのメモリ上限 (例: 34g)。既定は WSL VM の上限の約 7 割
  [ValidatePattern('^[0-9]+[mg]$')][string]$Memory,
  [string]$CudaImage = 'nvidia/cuda:12.4.1-base-ubuntu22.04',
  [switch]$Update,
  [switch]$SkipTailscale,
  [switch]$NoKeepalive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rootfsBase = 'https://cloud-images.ubuntu.com/wsl/releases/24.04/current'
$rootfsName = 'ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz'
$wslHome = Join-Path $HOME 'wsl'
if (-not $InstallDir) { $InstallDir = Join-Path $wslHome $Name }
$guestSrc = Join-Path $PSScriptRoot 'guest'
$failures = New-Object System.Collections.Generic.List[string]

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

# wsl.exe には引数を配列で渡す。関数呼び出しの `--` は PowerShell が消すため。
# 出力は UTF-16 なので NUL を除く。stderr を束ねると Stop で例外になるので Continue にする
function Get-WslText([string[]]$WslArgs) {
  $ErrorActionPreference = 'Continue'
  ((& wsl.exe @WslArgs 2>&1 | Out-String) -replace "`0", '')
}

function Get-WslExit([string[]]$WslArgs) {
  $ErrorActionPreference = 'Continue'
  & wsl.exe @WslArgs 2>&1 | Out-Null
  $LASTEXITCODE
}

function Invoke-Wsl([string[]]$WslArgs) {
  & wsl.exe @WslArgs
  if ($LASTEXITCODE -ne 0) { throw "wsl.exe $($WslArgs -join ' ') が終了コード $LASTEXITCODE で失敗" }
}

function Add-Check([string]$Label, [bool]$Ok) {
  if ($Ok) { Write-Host "  OK   $Label" -ForegroundColor Green }
  else { Write-Host "  NG   $Label" -ForegroundColor Red; $failures.Add($Label) }
}

function Get-ContainerMemory {
  $gb = 0
  $cfg = Join-Path $HOME '.wslconfig'
  if (Test-Path $cfg) {
    $m = Select-String -Path $cfg -Pattern '^\s*memory\s*=\s*(\d+)\s*GB' | Select-Object -First 1
    if ($m) { $gb = [int]$m.Matches[0].Groups[1].Value }
  }
  if ($gb -le 0) {
    $total = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    $gb = [math]::Floor($total / 1GB / 2)
  }
  '{0}g' -f [math]::Max(1, [math]::Floor($gb * 0.7))
}

# ---- 1. 事前確認 (読み取りのみ) ----
Step '事前確認'
& wsl.exe --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'WSL が未導入です。309_admin の WslPlatform (chezmoi apply) か wsl --install --no-distribution を先に実行してください' }
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { throw 'nvidia-smi が見つかりません (Windows 側の NVIDIA ドライバが必要)' }
& nvidia-smi -L
if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi が失敗しました' }

$existing = (Get-WslText '-l', '-q') -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($existing -contains $Name) {
  throw "ディストロ '$Name' は既にあります。作り直すなら先に手動で 'wsl --unregister $Name' を実行してください"
}
$drive = (Get-Item $HOME).PSDrive
if ($drive.Free -lt 50GB) { throw "$($drive.Name): の空きが 50GB 未満です" }
if (-not $Memory) { $Memory = Get-ContainerMemory }
Write-Host "ディストロ=$Name ユーザー=$User tailnet ホスト=$TailnetHostname メモリ上限=$Memory 配置=$InstallDir"

if ($Update) { Step 'wsl --update'; Invoke-Wsl '--update' }

# ---- 2. rootfs の取得と import ----
Step 'rootfs の取得と import'
New-Item -ItemType Directory -Force $wslHome | Out-Null
$rootfs = Join-Path $wslHome $rootfsName
$sums = (Invoke-WebRequest -UseBasicParsing "$rootfsBase/SHA256SUMS").Content
if ($sums -is [byte[]]) { $sums = [Text.Encoding]::UTF8.GetString($sums) }
$line = ($sums -split "`r?`n") | Where-Object { $_ -match [regex]::Escape($rootfsName) } | Select-Object -First 1
if (-not $line) { throw "SHA256SUMS に $rootfsName がありません" }
$expected = ($line -split '\s+')[0].ToLower()
if (-not ((Test-Path $rootfs) -and ((Get-FileHash $rootfs -Algorithm SHA256).Hash.ToLower() -eq $expected))) {
  Invoke-WebRequest -UseBasicParsing "$rootfsBase/$rootfsName" -OutFile $rootfs
}
if ((Get-FileHash $rootfs -Algorithm SHA256).Hash.ToLower() -ne $expected) { throw 'rootfs の SHA256 が一致しません' }
Write-Host "  SHA256 一致: $expected"

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Invoke-Wsl '--import', $Name, $InstallDir, $rootfs, '--version', '2'

# ---- 3. /etc/wsl.conf (隔離) ----
Step '/etc/wsl.conf'
Invoke-Wsl '-d', $Name, '-u', 'root', '--', 'true'
$unc = "\\wsl.localhost\$Name"
$wslConf = "[boot]`nsystemd=true`n`n[automount]`nenabled=false`n`n[interop]`nenabled=false`nappendWindowsPath=false`n"
[IO.File]::WriteAllText("$unc\etc\wsl.conf", $wslConf, (New-Object Text.UTF8Encoding $false))
Invoke-Wsl '--terminate', $Name
$state = ''
for ($i = 0; $i -lt 30; $i++) {
  $state = (Get-WslText '-d', $Name, '-u', 'root', '--exec', 'systemctl', 'is-system-running').Trim()
  if ($state -in @('running', 'degraded')) { break }
  Start-Sleep -Seconds 2
}
Write-Host "  systemctl is-system-running: $state"
Add-Check 'systemd が起動している' ($state -in @('running', 'degraded'))

# ---- 4. ゲスト内のセットアップ ----
Step 'Docker / nvidia-container-toolkit / Tailscale / ラッパー'
$guestTmp = "$unc\tmp\wsl-sandbox"
New-Item -ItemType Directory -Force $guestTmp | Out-Null
Copy-Item (Join-Path $guestSrc '*') $guestTmp -Force
$tsMode = if ($SkipTailscale) { 'skip' } else { 'tailscale' }
Invoke-Wsl '-d', $Name, '-u', 'root', '--', 'bash', '/tmp/wsl-sandbox/setup.sh', $User, $TailnetHostname, $Memory, $tsMode
Remove-Item $guestTmp -Recurse -Force

# ---- 5. 隔離の検証 ----
Step '隔離の検証'
Invoke-Wsl '--terminate', $Name
# automount 無効では /mnt/c 自体が無いこともある (ls が失敗) ので、無いか空なら OK
$mntArgs = '-d', $Name, '-u', $User, '--', 'ls', '-A', '/mnt/c'
$mntRc = Get-WslExit $mntArgs
$mnt = Get-WslText $mntArgs
Add-Check '/mnt/c が無いか空' (($mntRc -ne 0) -or ($mnt.Trim() -eq ''))
$rc = Get-WslExit '-d', $Name, '-u', $User, '--', 'cmd.exe', '/c', 'ver'
Add-Check 'cmd.exe が実行できない (interop 無効)' ($rc -ne 0)
& wsl.exe -d $Name -u $User -- sbx-run $CudaImage nvidia-smi -L
Add-Check 'sbx-run でコンテナから GPU が見える' ($LASTEXITCODE -eq 0)
$nics = (Get-WslText '-d', $Name, '-u', $User, '--', 'sbx-run', $CudaImage, 'ls', '/sys/class/net').Trim()
Add-Check "既定でネットワークが無い (I/F: $nics)" ($nics -eq 'lo')
$rc = Get-WslExit '-d', $Name, '-u', $User, '--', 'sbx-run', '--privileged', $CudaImage, 'true'
Add-Check 'sbx-run が --privileged を拒否する' ($rc -ne 0)

# ---- 6. VM の常駐化 ----
if (-not $NoKeepalive) {
  Step '常駐化 (スケジュールタスク)'
  $taskName = "$Name-keepalive"
  try {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
      Write-Warning "タスク $taskName は既にあるため変更しません"
    }
    else {
      $who = "$env:USERDOMAIN\$env:USERNAME"
      $action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless wsl.exe -d $Name -u root -- sleep infinity"
      $trigger = New-ScheduledTaskTrigger -AtLogOn -User $who
      $principal = New-ScheduledTaskPrincipal -UserId $who -LogonType Interactive -RunLevel Limited
      $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
      Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
      Start-ScheduledTask -TaskName $taskName
      Start-Sleep -Seconds 5
      $running = (Get-ScheduledTask -TaskName $taskName).State -eq 'Running'
      Add-Check "タスク $taskName が実行中 (ログオン時のみ起動。ログオン前は VM が上がらない)" $running
    }
  }
  catch {
    Write-Warning "タスクの登録に失敗しました ($($_.Exception.Message))。管理者の PowerShell で再実行するか手動で登録してください (docs/spec/wsl-sandbox.md)"
    $failures.Add('keepalive タスクの登録')
  }
}

# ---- 7. Windows 側のラッパー ----
$runScript = Join-Path $wslHome "$Name-run.ps1"
Set-Content -Path $runScript -Encoding ASCII -Value "wsl.exe -d $Name -u $User -- sbx-run @args"
Write-Host "`nWindows 側ラッパー: $runScript"

# ---- 8. Tailscale ----
if (-not $SkipTailscale) {
  Step 'Tailscale のログイン'
  Write-Host '表示される URL をブラウザで開いてログインしてください'
  Invoke-Wsl '-d', $Name, '-u', 'root', '--', 'tailscale', 'up', "--hostname=$TailnetHostname"
  Invoke-Wsl '-d', $Name, '-u', 'root', '--', 'tailscale', 'set', '--ssh'
  Invoke-Wsl '-d', $Name, '-u', 'root', '--', 'tailscale', 'status'
}

# ---- 9. 完了 ----
Step '完了'
if ($failures.Count -gt 0) {
  Write-Warning ('失敗した確認: ' + ($failures -join ' / '))
}
Write-Host @"

残りの手作業:
  1. Tailscale の管理画面 (https://login.tailscale.com/admin/acls/file) で、SSH ルールを
     action "accept" / src autogroup:member / dst autogroup:self / users ["$User"] にする
     (既定の "check" は 12 時間ごとに認証 URL の承認が要り、非対話の接続が止まる)
  2. 操作元から確認: ssh $User@$TailnetHostname docker info
  3. agent への案内: 「ssh $User@$TailnetHostname sbx-help を読んで、その指示に従って使う」
元に戻す: wsl --unregister $Name (仮想ディスクごと削除) / Unregister-ScheduledTask -TaskName $Name-keepalive
"@
if ($failures.Count -gt 0) { exit 1 }
