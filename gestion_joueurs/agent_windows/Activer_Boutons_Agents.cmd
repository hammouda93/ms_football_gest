@echo off
setlocal
chcp 65001 >nul
title Activation boutons agents MS Football

echo Desactivation de l'ancien demarrage automatique...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_agent.ps1"
if errorlevel 1 goto :error

echo.
echo Activation des deux boutons du menu...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_agent_buttons.ps1"
if errorlevel 1 goto :error

echo.
echo [OK] Les agents demarrent maintenant uniquement depuis les boutons ou un terminal.
goto :end

:error
echo.
echo [ERREUR] L'activation des boutons agents a echoue.

:end
echo.
pause

