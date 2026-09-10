$ErrorActionPreference = 'Stop'

$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
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
    throw 'Python introuvable. Définissez MS_FOOTBALL_PYTHON ou créez .venv dans le projet.'
}

$PythonExecutable = [string]$PythonCandidates[0]
$LogDirectory = Join-Path $RepositoryRoot 'gestion_joueurs\agent_logs'
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LogFile = Join-Path $LogDirectory 'automation_agent.log'
$ErrorLogFile = Join-Path $LogDirectory 'automation_agent_error.log'

Set-Location -LiteralPath $RepositoryRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $PythonExecutable `
    -X utf8 `
    -u `
    (Join-Path $RepositoryRoot 'gestion_joueurs\automation_agent.py') `
    1>> $LogFile `
    2>> $ErrorLogFile

