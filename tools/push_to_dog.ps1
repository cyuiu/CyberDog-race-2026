param(
    [string[]]$Files,
    [string]$Dir,
    [switch]$All
)

. "$PSScriptRoot\config.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path -LiteralPath $LocalProgramDir -PathType Container)) {
    Write-Error "Local program directory not found: $LocalProgramDir"
    exit 1
}

$LocalProgramRoot = [System.IO.Path]::GetFullPath($LocalProgramDir).TrimEnd("\", "/")
$LocalProgramPrefix = $LocalProgramRoot + [System.IO.Path]::DirectorySeparatorChar

function Get-ProgramRelativePath {
    param([System.IO.FileInfo]$File)

    $fullPath = [System.IO.Path]::GetFullPath($File.FullName)
    if (-not $fullPath.StartsWith($LocalProgramPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "File is outside the local program directory: $fullPath"
    }

    return $fullPath.Substring($LocalProgramPrefix.Length).Replace("\", "/")
}

function Get-ProgramFiles {
    return Get-ChildItem -LiteralPath $LocalProgramRoot -File -Recurse |
        Where-Object { $_.Extension -in ".py", ".sh", ".toml" }
}

if ($Dir) {
    $dirPath = Join-Path $LocalProgramRoot ($Dir.Replace("/", "\"))
    if (-not (Test-Path -LiteralPath $dirPath -PathType Container)) {
        Write-Error "Directory not found: $Dir"
        exit 1
    }
    $selected = @(
        Get-ChildItem -LiteralPath $dirPath -File -Recurse |
        Where-Object { $_.Extension -in ".py", ".sh", ".toml" } |
        Sort-Object FullName
    )
    if ($selected.Count -eq 0) {
        Write-Error "No .py/.sh/.toml files found in $Dir"
        exit 1
    }
} elseif ($All) {
    $selected = @(Get-ProgramFiles | Sort-Object FullName)
} elseif ($Files -and $Files.Count -gt 0) {
    $selected = @(
        foreach ($name in $Files) {
            if ([System.IO.Path]::IsPathRooted($name)) {
                $path = $name
            } else {
                $path = Join-Path $LocalProgramRoot ($name.Replace("/", "\"))
            }

            $fullPath = [System.IO.Path]::GetFullPath($path)
            if (-not $fullPath.StartsWith($LocalProgramPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                Write-Error "File is outside the local program directory: $name"
                exit 1
            }
            if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
                Write-Error "File not found: $fullPath"
                exit 1
            }

            Get-Item -LiteralPath $fullPath
        }
    )
} else {
    $available = @(Get-ProgramFiles | Sort-Object FullName)

    if ($available.Count -eq 0) {
        Write-Error "No .py, .sh or .toml files found in $LocalProgramRoot"
        exit 1
    }

    Write-Host ""
    Write-Host "Select files to push. Examples: 1 or 1,3,5 or all"
    for ($i = 0; $i -lt $available.Count; $i++) {
        "{0}) {1}" -f ($i + 1), (Get-ProgramRelativePath $available[$i])
    }

    $choice = Read-Host "Choice"
    if ($choice -match "^(q|quit)$") {
        Write-Host "[INFO] Cancelled."
        exit 0
    }

    if ($choice -match "^(all|a)$") {
        $selected = $available
    } else {
        $indexes = $choice -split "," | ForEach-Object { $_.Trim() }
        $selected = @(
            foreach ($idxText in $indexes) {
                if ($idxText -notmatch "^\d+$") {
                    Write-Error "Invalid choice: $idxText"
                    exit 1
                }
                $idx = [int]$idxText
                if ($idx -lt 1 -or $idx -gt $available.Count) {
                    Write-Error "Choice out of range: $idx"
                    exit 1
                }
                $available[$idx - 1]
            }
        )
    }
}

if ($selected.Count -eq 0) {
    Write-Error "No files selected."
    exit 1
}

Write-Host "[INFO] Ensuring remote directory: $RemoteProgramDir"
ssh $DogTarget "mkdir -p '$RemoteProgramDir'"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

foreach ($file in $selected) {
    $relativePath = Get-ProgramRelativePath $file
    $remotePath = "$RemoteProgramDir/$relativePath"
    $remoteParent = $remotePath.Substring(0, $remotePath.LastIndexOf("/"))

    Write-Host "[INFO] Copying $relativePath"
    ssh $DogTarget "mkdir -p '$remoteParent'"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    scp $file.FullName "${DogTarget}:$remotePath"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if ($file.Extension -eq ".sh") {
        ssh $DogTarget "chmod +x '$remotePath'"
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
}

Write-Host "[OK] Pushed $($selected.Count) file(s) to ${DogTarget}:$RemoteProgramDir"
