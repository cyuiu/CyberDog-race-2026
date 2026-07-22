param(
    [int]$LocalPort = 18080,
    [int]$RemotePort = 8080,
    [int]$Duration = 3600,
    [ValidateSet("rgb", "fisheye")]
    [string]$Source = "rgb",
    [string]$LeftDevice = "/dev/video2",
    [string]$RightDevice = "/dev/video3",
    [switch]$PushFirst
)

. "$PSScriptRoot\config.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

ssh -o BatchMode=yes -o ConnectTimeout=5 $DogTarget "echo key_login_ok" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] start_camera_view.ps1 needs passwordless SSH, because it starts hidden background ssh processes."
    Write-Host "[ERROR] Please run first:"
    Write-Host "  .\tools\setup_ssh_key.ps1"
    exit 1
}

if ($PushFirst) {
    & "$PSScriptRoot\push_to_dog.ps1" -Files @(
        "perception/cyberdog_camera.py"
        "perception/cyberdog_fisheye.py"
        "perception/camera_view.py"
        "perception/run_camera_view.sh"
    )
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$tunnelOutLog = Join-Path $LogDir "win_camera_tunnel_$timestamp.out.log"
$tunnelErrorLog = Join-Path $LogDir "win_camera_tunnel_$timestamp.err.log"
$remoteOutLog = Join-Path $LogDir "win_camera_remote_$timestamp.out.log"
$remoteErrorLog = Join-Path $LogDir "win_camera_remote_$timestamp.err.log"
$url = "http://127.0.0.1:$LocalPort/"

$tunnel = $null
$remote = $null

function Show-LogFiles {
    param([string[]]$Paths)

    foreach ($path in $Paths) {
        if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 0) {
            Write-Host "--- $path"
            Get-Content -LiteralPath $path
        }
    }
}

try {
    Write-Host "[INFO] Cleaning old camera preview process"
    ssh $DogTarget "pgrep -f 'python3[[:space:]]+([^[:space:]]*/)?camera_view.py([[:space:]]|$)' | xargs -r kill 2>/dev/null || true" | Out-Null

    Write-Host "[INFO] Starting SSH tunnel: local $LocalPort -> robot $RemotePort"
    $tunnelArgs = @(
        "-o", "ExitOnForwardFailure=yes",
        "-N",
        "-L", "${LocalPort}:127.0.0.1:${RemotePort}",
        $DogTarget
    )
    $tunnel = Start-Process -FilePath "ssh" -ArgumentList $tunnelArgs -RedirectStandardOutput $tunnelOutLog -RedirectStandardError $tunnelErrorLog -PassThru -WindowStyle Hidden -ErrorAction Stop

    Start-Sleep -Seconds 1
    if ($tunnel.HasExited) {
        Write-Host "[ERROR] SSH tunnel exited before the camera started."
        Show-LogFiles @($tunnelOutLog, $tunnelErrorLog)
        exit 1
    }

    Write-Host "[INFO] Starting remote camera preview"
    $remoteCommand = "cd '$RemoteProgramDir/perception' && ./run_camera_view.sh --source $Source --duration $Duration --web-port $RemotePort --left-device '$LeftDevice' --right-device '$RightDevice'"
    $remote = Start-Process -FilePath "ssh" -ArgumentList @($DogTarget, $remoteCommand) -RedirectStandardOutput $remoteOutLog -RedirectStandardError $remoteErrorLog -PassThru -WindowStyle Hidden -ErrorAction Stop

    Write-Host "[INFO] Waiting for web page: $url"
    $ready = $false
    for ($i = 1; $i -le 45; $i++) {
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {
            if ($remote.HasExited) {
                Write-Host "[ERROR] Remote camera process exited."
                Show-LogFiles @($remoteOutLog, $remoteErrorLog)
                exit 1
            }
            if ($i % 5 -eq 0) {
                Write-Host "[INFO] Still waiting... ${i}s"
            }
            Start-Sleep -Seconds 1
        }
    }

    if (-not $ready) {
        Write-Host "[ERROR] Timed out waiting for $url"
        Write-Host "[ERROR] Remote log:"
        Show-LogFiles @($remoteOutLog, $remoteErrorLog, $tunnelErrorLog)
        exit 1
    }

    Write-Host "[OK] Camera page ready: $url"
    Start-Process $url
    Write-Host "[INFO] Camera preview running. Press Ctrl-C to stop."

    while (-not $remote.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    if ($remote -and -not $remote.HasExited) {
        Stop-Process -Id $remote.Id -Force -ErrorAction SilentlyContinue
    }
    if ($tunnel -and -not $tunnel.HasExited) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
}
