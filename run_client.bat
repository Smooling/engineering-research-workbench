@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1
rem Prefer the most recently built executable when an in-use version was retained.
for /f "delims=" %%E in ('dir /b /a:-d /o:-d ResearchWorkbench*.exe 2^>nul') do (
    if /I "%%E"=="ResearchWorkbench.exe" (
        start "" "%CD%\%%E" %*
        exit /b 0
    )
    if /I "%%E"=="ResearchWorkbench-Updated.exe" (
        start "" "%CD%\%%E" %*
        exit /b 0
    )
)
if exist "build\.venv\Scripts\pythonw.exe" (
    start "" "%CD%\build\.venv\Scripts\pythonw.exe" "%CD%\client.py" %*
    exit /b 0
)
echo Run build_client.bat first to prepare the Windows desktop application.
pause
exit /b 1
