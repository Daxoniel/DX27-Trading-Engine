@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-report.ps1" %*
set "ReportExitCode=%ERRORLEVEL%"
if not "%ReportExitCode%"=="0" pause
exit /b %ReportExitCode%
