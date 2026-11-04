$ErrorActionPreference = 'Stop'
$TaskName = 'MS Football Automation Agent'

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host 'Agent MS Football retiré du démarrage automatique. Les vidéos et journaux sont conservés.'

