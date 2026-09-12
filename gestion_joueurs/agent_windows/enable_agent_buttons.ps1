$ErrorActionPreference = 'Stop'

$ProtocolName = 'msfootball-agent'
$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$LauncherPath = (
    Resolve-Path -LiteralPath (
        Join-Path $AgentDirectory 'launch_agent_from_url.ps1'
    )
).Path
$PowerShellExecutable = Join-Path `
    $env:SystemRoot `
    'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not (Test-Path -LiteralPath $PowerShellExecutable -PathType Leaf)) {
    throw "Windows PowerShell est introuvable : $PowerShellExecutable"
}

$ProtocolKey = "HKCU:\Software\Classes\$ProtocolName"
$CommandKey = Join-Path $ProtocolKey 'shell\open\command'
$ProtocolCommand = [string]::Format(
    '"{0}" -NoExit -NoProfile -ExecutionPolicy Bypass -File "{1}" "%1"',
    $PowerShellExecutable,
    $LauncherPath
)

New-Item -Path $ProtocolKey -Force | Out-Null
Set-Item -Path $ProtocolKey -Value 'URL:MS Football Agent'
New-ItemProperty `
    -Path $ProtocolKey `
    -Name 'URL Protocol' `
    -Value '' `
    -PropertyType String `
    -Force | Out-Null
New-Item -Path $CommandKey -Force | Out-Null
Set-Item -Path $CommandKey -Value $ProtocolCommand

Write-Host '[OK] Protocole Windows msfootball-agent activé.' -ForegroundColor Green
Write-Host '[OK] Aucun logiciel et aucun droit administrateur nécessaires.' -ForegroundColor Green
Write-Host 'Vous pouvez maintenant utiliser les deux boutons dans le menu MS Football.'
