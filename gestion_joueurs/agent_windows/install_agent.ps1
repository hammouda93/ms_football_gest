$ErrorActionPreference = 'Stop'

$TaskName = 'MS Football Automation Agent'
$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerPath = (Resolve-Path -LiteralPath (Join-Path $AgentDirectory 'run_agent.ps1')).Path
$RepositoryRoot = (Resolve-Path -LiteralPath (Join-Path $AgentDirectory '..\..')).Path

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
Write-Host 'Agent MS Football installé et démarré. Son état apparaîtra dans le tableau de bord.'

