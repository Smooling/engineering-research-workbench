@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0" || exit /b 1

rem v261013: Build in an isolated venv, never installing packages into Anaconda base.
rem Only build artifacts are changed. Existing config/ and Workspace/ are not touched.
set "BUILD_LOG=%CD%\build_client.log"
set "VENV_DIR=%CD%\build\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "BUILD_NAME=ResearchWorkbench"
set "STAGE=initialization"
> "%BUILD_LOG%" echo ResearchWorkbench desktop build log
>> "%BUILD_LOG%" echo Working directory: %CD%
>> "%BUILD_LOG%" echo Date: %DATE% %TIME%

echo.
echo ResearchWorkbench - Windows desktop build
echo Build log: "%BUILD_LOG%"
echo.

set "STAGE=isolated Python environment"
echo [1/3] Creating or reusing isolated build environment...
if not exist "build" mkdir "build"
if not exist "%VENV_PY%" (
    echo Creating virtual environment in build\.venv...
    if not defined ERW_BUILD_PYTHON set "ERW_BUILD_PYTHON=python"
    call :create_venv
    if errorlevel 1 goto :failed
)
if not exist "%VENV_PY%" (
    >> "%BUILD_LOG%" echo ERROR: Virtual environment Python was not created.
    goto :failed
)
"%VENV_PY%" -c "import sys; print('Build Python:', sys.executable, sys.version); assert sys.prefix != sys.base_prefix; assert sys.version_info >= (3, 11)" >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed
"%VENV_PY%" -m pip --version >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed
echo Installing build dependencies into build\.venv...
"%VENV_PY%" -m pip install --disable-pip-version-check --prefer-binary -r requirements-desktop.txt >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed

set "STAGE=resources and icon"
echo [2/3] Checking resources and preparing the icon...
if not exist "client.py" (
    >> "%BUILD_LOG%" echo ERROR: Missing client.py
    goto :failed
)
if not exist "web\index.html" (
    >> "%BUILD_LOG%" echo ERROR: Missing web\index.html
    goto :failed
)
if not exist "VERSION" (
    >> "%BUILD_LOG%" echo ERROR: Missing VERSION
    goto :failed
)

set "STAGE=PyInstaller packaging"
echo [3/3] Packaging ResearchWorkbench.exe...
echo Detailed PyInstaller output is written to build_client.log.
rem Do not terminate a running application: that could lose unsaved edits.
tasklist /FI "IMAGENAME eq ResearchWorkbench.exe" 2>nul | find /I "ResearchWorkbench.exe" >nul
if not errorlevel 1 (
    set "BUILD_NAME=ResearchWorkbench-Updated"
    echo A running application is retained. Building ResearchWorkbench-Updated.exe instead.
    >> "%BUILD_LOG%" echo Running app retained; output renamed ResearchWorkbench-Updated.exe.
)
"%VENV_PY%" tools\build_windows.py --name "%BUILD_NAME%" >> "%BUILD_LOG%" 2>&1
if errorlevel 1 goto :failed
if not exist "%BUILD_NAME%.exe" (
    >> "%BUILD_LOG%" echo ERROR: PyInstaller finished without producing %BUILD_NAME%.exe
    goto :failed
)

echo.
echo SUCCESS: "%CD%\%BUILD_NAME%.exe"
echo The existing Workspace and config folders were left unchanged.
echo Full log: "%BUILD_LOG%"
if /I not "%~1"=="--no-pause" pause
exit /b 0

:failed
echo.
echo ERROR during: %STAGE%
echo Full log: "%BUILD_LOG%"
echo.
echo Last lines of the build log:
powershell -NoProfile -Command "Get-Content -LiteralPath $env:BUILD_LOG -Tail 80"
if errorlevel 1 type "%BUILD_LOG%"
echo.
echo Copy the above error output or share build_client.log for troubleshooting.
if /I not "%~1"=="--no-pause" pause
exit /b 1

:create_venv
"%ERW_BUILD_PYTHON%" -c "import sys; print('Bootstrap Python:', sys.executable, sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)" >> "%BUILD_LOG%" 2>&1
if errorlevel 1 exit /b 1
"%ERW_BUILD_PYTHON%" -m venv "%VENV_DIR%" >> "%BUILD_LOG%" 2>&1
exit /b %errorlevel%
