@echo off
rem ==========================================================
rem v261008 - .scratch one-click cleanup (ASCII only: a batch
rem file with UTF-8 Chinese comments is mis-parsed by cmd.exe
rem under a non-UTF-8 console codepage).
rem Same as: python tools\scratch_clean.py
rem   Double-click        -> clean with the default retention
rem   With arguments      -> passed through unchanged, e.g.
rem     tools\scratch_clean.bat --dry-run
rem     tools\scratch_clean.bat --status
rem     tools\scratch_clean.bat --days 3
rem ==========================================================
chcp 65001 >nul
cd /d "%~dp0.."
python "tools\scratch_clean.py" %*
set "RC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RC%
