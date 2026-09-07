Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$pycachePath = Join-Path $HOME '.config\agents\__pycache__'
if (Test-Path -LiteralPath $pycachePath -PathType Container) {
    Remove-Item -LiteralPath $pycachePath -Recurse -Force
}
