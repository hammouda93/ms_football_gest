@echo off
title Installation Agent MS Football
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_agent.ps1"
if errorlevel 1 (
    echo.
    echo L'installation a echoue. Envoyez une capture de cette fenetre a Codex.
) else (
    echo.
    echo Installation terminee. Vous pouvez fermer cette fenetre.
)
pause
