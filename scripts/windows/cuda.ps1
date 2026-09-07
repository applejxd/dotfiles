Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Install-WingetPackage {
    param([Parameter(Mandatory)][string]$PackageId)

    & winget list --id $PackageId --exact --disable-interactivity `
        --accept-source-agreements | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    & winget install --id $PackageId --exact --silent --disable-interactivity `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for ${PackageId}: $LASTEXITCODE"
    }
}

Install-WingetPackage Microsoft.VisualStudio.2022.BuildTools
Install-WingetPackage Microsoft.VCRedist.2015+.x64
Install-WingetPackage Nvidia.CUDA
