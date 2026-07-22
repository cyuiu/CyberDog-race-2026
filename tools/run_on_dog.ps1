param(
    [string]$Script,
    [string[]]$Args = @(),
    [switch]$PushFirst
)

. "$PSScriptRoot\config.ps1"

if (-not (Test-Path -LiteralPath $LocalProgramDir -PathType Container)) {
    Write-Error "Local program directory not found: $LocalProgramDir"
    exit 1
}

$LocalProgramRoot = [System.IO.Path]::GetFullPath($LocalProgramDir).TrimEnd("\", "/")
$LocalProgramPrefix = $LocalProgramRoot + [System.IO.Path]::DirectorySeparatorChar

function Get-ProgramRelativePath {
    param([System.IO.FileInfo]$File)

    return $File.FullName.Substring($LocalProgramPrefix.Length).Replace("\", "/")
}

if (-not $Script) {
    $available = @(Get-ChildItem -LiteralPath $LocalProgramRoot -File -Recurse -Filter "*.py" | Sort-Object FullName)
    if ($available.Count -eq 0) {
        Write-Error "No .py files found in $LocalProgramRoot"
        exit 1
    }

    Write-Host ""
    Write-Host "Select Python file to run on CyberDog:"
    for ($i = 0; $i -lt $available.Count; $i++) {
        "{0}) {1}" -f ($i + 1), (Get-ProgramRelativePath $available[$i])
    }
    Write-Host "q) quit"

    $choice = Read-Host "Choice"
    if ($choice -match "^(q|quit)$") {
        Write-Host "[INFO] Cancelled."
        exit 0
    }
    if ($choice -notmatch "^\d+$") {
        Write-Error "Invalid choice: $choice"
        exit 1
    }
    $idx = [int]$choice
    if ($idx -lt 1 -or $idx -gt $available.Count) {
        Write-Error "Choice out of range: $idx"
        exit 1
    }
    $Script = Get-ProgramRelativePath $available[$idx - 1]
}

if ([System.IO.Path]::IsPathRooted($Script)) {
    Write-Error "Script must be relative to the program directory: $Script"
    exit 1
}

$Script = $Script.Replace("\", "/").TrimStart("/")
$localScriptPath = [System.IO.Path]::GetFullPath((Join-Path $LocalProgramRoot $Script.Replace("/", "\")))
if (-not $localScriptPath.StartsWith($LocalProgramPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Error "Script is outside the local program directory: $Script"
    exit 1
}
if (-not (Test-Path -LiteralPath $localScriptPath -PathType Leaf)) {
    Write-Error "Script not found: $localScriptPath"
    exit 1
}

if ($PushFirst) {
    & "$PSScriptRoot\push_to_dog.ps1" -Files $Script
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$argText = ($Args | ForEach-Object { "'$($_ -replace "'", "'\''")'" }) -join " "

# Only explicitly listed read-only or vision scripts skip the motion warning.
$NoMotionScripts = @(
    "manual_tests/check_status.py"
    "perception/camera_view.py"
    "perception/ball_detect2.py"
    "perception/fisheye_probe.py"
)
$motionRisk = $Script -notin $NoMotionScripts
if ($motionRisk) {
    Write-Host ""
    Write-Host "[SAFETY] $Script may move the robot."
    Write-Host "[SAFETY] Keep the robot on open ground and have APP emergency stop ready."
    $confirm = Read-Host "Continue? [y/N]"
    if ($confirm -notin @("y", "Y")) {
        Write-Host "[INFO] Cancelled."
        exit 1
    }
}

$remoteScript = "$RemoteProgramDir/$Script"
Write-Host "[INFO] Running on CyberDog with ROS2 environment: python3 $remoteScript $argText"

$quotedRemoteDir = "'$($RemoteProgramDir -replace "'", "'\''")'"
$quotedScript = "'$($Script -replace "'", "'\''")'"
$remoteInvoke = "bash -s -- $quotedRemoteDir $quotedScript $argText"

$bootstrap = @'
set +u

source /opt/ros2/galactic/setup.bash >/tmp/run_on_dog_source.log 2>&1 || true
source /opt/ros2/cyberdog/setup.bash >>/tmp/run_on_dog_source.log 2>&1 || true

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///etc/mi/cyclonedds.xml
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0

program_dir="$1"
script="$2"
shift 2

cd "$program_dir"

echo "[REMOTE] python3 ${script} $*"
python3 "$script" "$@"
'@

$bootstrap | ssh $DogTarget $remoteInvoke
