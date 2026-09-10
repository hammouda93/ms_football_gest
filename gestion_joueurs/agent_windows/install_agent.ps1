$ErrorActionPreference = 'Stop'

$TaskName = 'MS Football Automation Agent'
$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPath = (Resolve-Path -LiteralPath (Join-Path $AgentDirectory 'run_agent.ps1')).Path
$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $AgentDirectory '..\..')).Path
$ConfiguredPython = [Environment]::GetEnvironmentVariable('MS_FOOTBALL_PYTHON', 'User')
$PathPython = Get-Command python.exe -ErrorAction SilentlyContinue
$PythonCandidates = @(
    @(
        $ConfiguredPython,
        (Join-Path $RepositoryRoot '.venv\Scripts\python.exe'),
        (Join-Path $RepositoryRoot 'venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python39\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        $(if ($PathPython) { $PathPython.Source } else { $null })
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique
)

if (-not $PythonCandidates) {
    throw 'Python introuvable. Installez Python ou définissez MS_FOOTBALL_PYTHON.'
}

$PythonExecutable = [string]$PythonCandidates[0]
[Environment]::SetEnvironmentVariable('MS_FOOTBALL_PYTHON', $PythonExecutable, 'User')

$ActionArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $RunnerPath + '"'
$Action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument $ActionArguments `
    -WorkingDirectory $RepositoryRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description 'Agent local SportsBase, Premiere Pro, YouTube et livraison MS Football.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host ('Agent MS Football installé et démarré avec ' + $PythonExecutable)
Write-Host 'Son état apparaîtra dans le tableau de bord sous quelques secondes.'
