<#
  .SYNOPSIS
    Turn off ads, suggestions and promoted content in Windows 11 (HKCU, every apply)
  .DESCRIPTION
    Feature updates reset some of these values, so this runs on every apply and only writes what differs.
    A value Windows refuses to write (protected keys) is reported and skipped.
    The taskbar widget (weather) is a machine policy set by 309_admin.
    see docs/spec/windows-settings.md#広告と推奨の抑止
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$cdm = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'
$advanced = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
$settings = @()
# Content Delivery Manager: suggested apps, lock screen / Settings / Start tips, silent installs
foreach ($name in @(
    'ContentDeliveryAllowed', 'FeatureManagementEnabled', 'OemPreInstalledAppsEnabled',
    'PreInstalledAppsEnabled', 'PreInstalledAppsEverEnabled', 'RotatingLockScreenOverlayEnabled',
    'SilentInstalledAppsEnabled', 'SoftLandingEnabled', 'SystemPaneSuggestionsEnabled',
    'SubscribedContentEnabled', 'SubscribedContent-310093Enabled', 'SubscribedContent-338387Enabled',
    'SubscribedContent-338388Enabled', 'SubscribedContent-338389Enabled', 'SubscribedContent-338393Enabled',
    'SubscribedContent-353694Enabled', 'SubscribedContent-353696Enabled', 'SubscribedContent-353698Enabled'
  )) {
  $settings += @{ Path = $cdm; Name = $name }
}
# Explorer: OneDrive / sync provider banners, Start recommendations and account notifications
foreach ($name in 'ShowSyncProviderNotifications', 'Start_IrisRecommendations', 'Start_AccountNotifications') {
  $settings += @{ Path = $advanced; Name = $name }
}
# Search box highlights ("daily doodle"), "finish setting up your device", tailored experiences, advertising ID, language list
$settings += @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\SearchSettings'; Name = 'IsDynamicSearchBoxEnabled' }
$settings += @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement'; Name = 'ScoobeSystemSettingEnabled' }
$settings += @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Privacy'; Name = 'TailoredExperiencesWithDiagnosticDataEnabled' }
$settings += @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo'; Name = 'Enabled' }

$failed = @()
foreach ($setting in $settings) {
  $item = Get-Item -LiteralPath $setting.Path -ErrorAction Ignore
  $current = if ($null -eq $item) { $null } else { $item.GetValue($setting.Name, $null) }
  if ($current -eq 0) { continue }
  try {
    if ($null -eq $item) { New-Item -Path $setting.Path -Force | Out-Null }
    New-ItemProperty -LiteralPath $setting.Path -Name $setting.Name -PropertyType DWord -Value 0 -Force | Out-Null
  } catch {
    $failed += "$($setting.Path)\$($setting.Name)"
  }
}
# Websites must not see the language list (a DWord of 1 = opt out)
$international = 'HKCU:\Control Panel\International\User Profile'
$optOut = (Get-Item -LiteralPath $international -ErrorAction Ignore)
if ($null -ne $optOut -and $optOut.GetValue('HttpAcceptLanguageOptOut', $null) -ne 1) {
  try {
    New-ItemProperty -LiteralPath $international -Name 'HttpAcceptLanguageOptOut' -PropertyType DWord -Value 1 -Force | Out-Null
  } catch {
    $failed += "$international\HttpAcceptLanguageOptOut"
  }
}

if ($failed.Count -gt 0) {
  Write-Warning ("Windows refused to write: " + ($failed -join ', '))
}
