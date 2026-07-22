param(
    [string]$HostName
)

. "$PSScriptRoot\config.ps1"

if (-not $HostName) {
    $HostName = $DogTarget
}

Write-Host "[INFO] SSH connecting to $HostName"
ssh $HostName
