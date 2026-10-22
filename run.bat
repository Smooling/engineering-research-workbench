@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist "build\.venv\Scripts\python.exe" (
    "build\.venv\Scripts\python.exe" server.py
) else (
    python server.py
)
if errorlevel 1 pause
