param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$AgentUri
)

$ErrorActionPreference = 'Stop'

try {
    $ParsedUri = [System.Uri]$AgentUri
} catch {
    throw 'Lien de lancement MS Football invalide.'
}

if ($ParsedUri.Scheme -ne 'msfootball-agent') {
    throw 'Protocole de lancement MS Football invalide.'
}

$AgentName = $ParsedUri.Host.ToLowerInvariant()
if ($AgentName -notin @('performance', 'highlights')) {
    throw 'Agent MS Football inconnu.'
}

$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepositoryRoot = (
    Resolve-Path -LiteralPath (Join-Path $AgentDirectory '..\..')
).Path
$ConfiguredPython = [Environment]::GetEnvironmentVariable(
    'MS_FOOTBALL_PYTHON',
    'User'
)
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
    ) | Where-Object {
        $_ -and (Test-Path -LiteralPath $_ -PathType Leaf)
    } | Select-Object -Unique
)

if (-not $PythonCandidates) {
    throw 'Python introuvable. Définissez MS_FOOTBALL_PYTHON ou créez .venv.'
}

$PythonExecutable = [string]$PythonCandidates[0]
if ($AgentName -eq 'performance') {
    $WindowTitle = 'MS Football - Agent Performance'
    $ProcessMarker = 'sportsbase_data.local_agent'
    $AgentModule = 'sportsbase_data.local_agent'
} else {
    $WindowTitle = 'MS Football - Agent Highlights'
    $ProcessMarker = 'gestion_joueurs.automation_agent'
    $AgentModule = 'gestion_joueurs.automation_agent'
}

try {
    $ExistingAgent = Get-CimInstance Win32_Process `
        -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" `
        -ErrorAction Stop | Where-Object {
            $_.CommandLine -and (
                $_.CommandLine.Contains($ProcessMarker) -or
                ($AgentName -eq 'highlights' -and $_.CommandLine.Contains('automation_agent.py'))
            )
        } | Select-Object -First 1
} catch {
    $ExistingAgent = $null
}

try {
    $Host.UI.RawUI.WindowTitle = $WindowTitle
} catch {
    # Certains hôtes PowerShell ne permettent pas de modifier le titre.
}

if ($ExistingAgent) {
    Write-Host (
        '[INFO] Cet agent est déjà actif (PID {0}).' -f $ExistingAgent.ProcessId
    ) -ForegroundColor Yellow
    return
}

Set-Location -LiteralPath $RepositoryRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

Write-Host ("[INFO] Démarrage : $WindowTitle") -ForegroundColor Cyan
Write-Host ("[INFO] Python : $PythonExecutable")
Write-Host ("[INFO] Dossier : $RepositoryRoot")
Write-Host ''

& $PythonExecutable -X utf8 -u -m $AgentModule

