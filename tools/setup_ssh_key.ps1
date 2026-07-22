param(
    [string]$KeyPath = "$env:USERPROFILE\.ssh\cyberdog_ed25519"
)

. "$PSScriptRoot\config.ps1"

$sshDir = Split-Path -Parent $KeyPath
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

if (-not (Test-Path $KeyPath)) {
    Write-Host "[INFO] Generating SSH key: $KeyPath"
    $keygenCommand = 'ssh-keygen -t ed25519 -f "{0}" -N "" -C "cyberdog-windows"' -f $KeyPath
    cmd.exe /c $keygenCommand
} else {
    Write-Host "[INFO] SSH key already exists: $KeyPath"
}

$pubPath = "$KeyPath.pub"
if (-not (Test-Path $pubPath)) {
    Write-Error "Public key not found: $pubPath"
    exit 1
}

$pub = Get-Content -Raw -LiteralPath $pubPath
$pub = $pub.Trim()
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pub))

Write-Host "[INFO] Installing public key on CyberDog. Password may be requested once."
ssh $DogTarget "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo $encoded | base64 -d >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

$configPath = Join-Path $sshDir "config"
$configBlock = @"

Host cyberdog-win
    HostName $DogHost
    User $DogUser
    IdentityFile $KeyPath
    IdentitiesOnly yes

"@

$needConfig = $true
if (Test-Path $configPath) {
    $existing = Get-Content -Raw -LiteralPath $configPath
    if ($existing -match "(?m)^Host\s+cyberdog-win\s*$") {
        $needConfig = $false
    }
}

if ($needConfig) {
    Add-Content -LiteralPath $configPath -Value $configBlock
    Write-Host "[INFO] Added SSH config host: cyberdog-win"
} else {
    Write-Host "[INFO] SSH config host already exists: cyberdog-win"
}

Write-Host "[INFO] Testing passwordless login..."
ssh -o BatchMode=yes cyberdog-win "echo key_login_ok"

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Windows passwordless SSH is ready."

    $toolConfigPath = Join-Path $PSScriptRoot "config.ps1"
    $toolConfig = Get-Content -Raw -LiteralPath $toolConfigPath
    $toolConfig = $toolConfig -replace '(?m)^\$DogTarget\s*=\s*"\$DogUser@\$DogHost"\s*$', '$DogTarget = "cyberdog-win"'
    Set-Content -LiteralPath $toolConfigPath -Value $toolConfig -Encoding UTF8

    Write-Host "[OK] Updated tools/config.ps1: DogTarget = cyberdog-win"
} else {
    Write-Error "Passwordless SSH test failed."
    exit 1
}
