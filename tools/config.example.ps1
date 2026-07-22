$DogUser = "mi"
$DogHost = "192.168.x.x"
$DogTarget = "$DogUser@$DogHost"

$RemoteProgramDir = "/home/mi/cyberdog_course/program"
$LocalProgramDir = Join-Path $PSScriptRoot "..\program"
$LogDir = Join-Path $PSScriptRoot "..\log"
