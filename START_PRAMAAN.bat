@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM PRAMAAN local launcher for Windows.
REM Run this file from the repository root (double-click is supported).
REM It starts the API and web UI in separate terminal windows.
REM ---------------------------------------------------------------------------

if /I "%~1"=="api" goto :RUN_API
if /I "%~1"=="web" goto :RUN_WEB
goto :MAIN

:RUN_API
cd /d "%~dp0"
set "PROJECT_ROOT=%CD%"
set "LAUNCH_DIR=%PROJECT_ROOT%\launcher"
set "PYTHONPATH=%LAUNCH_DIR%"
set "PRAMAAN_DATA=%PROJECT_ROOT%\.demo\runtime"
"%PROJECT_ROOT%\.venv-p4\Scripts\python.exe" -m uvicorn Pramaan.backend.app:app --host 127.0.0.1 --port 8000 --no-access-log
echo.
echo PRAMAAN API process has stopped. Review errors above.
pause
exit /b

:RUN_WEB
cd /d "%~dp0web"
call npm run dev
echo.
echo PRAMAAN web process has stopped. Review errors above.
pause
exit /b

:MAIN
cd /d "%~dp0"
if errorlevel 1 goto :ROOT_FAILED
set "PROJECT_ROOT=%CD%"
set "ROOT_FORWARD=%CD:\=/%"
set "LAUNCH_DIR=%PROJECT_ROOT%\launcher"
set "PACKAGE_SHIM=%LAUNCH_DIR%\Pramaan"
set "VENV_PY=%PROJECT_ROOT%\.venv-p4\Scripts\python.exe"
set "DEMO_DATA=%PROJECT_ROOT%\.demo\runtime"
set "CREDENTIALS_FILE=%DEMO_DATA%\LOCAL_DEMO_CREDENTIALS.txt"

echo.
echo ============================================================
echo                    PRAMAAN LOCAL LAUNCHER
echo ============================================================
echo.
echo Project: %PROJECT_ROOT%
echo.

REM Check Python launcher / interpreter.
set "PY_LAUNCH="
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_LAUNCH=py -3"
)
if not defined PY_LAUNCH (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_LAUNCH=python"
    )
)
if not defined PY_LAUNCH goto :PYTHON_MISSING

REM Check Node.js and npm versions supported by this repository.
where node >nul 2>&1
if errorlevel 1 goto :NODE_MISSING
node -e "const [a,b]=process.versions.node.split('.').map(Number); process.exit(((a===20&&b>=19)||(a>=22&&(a>22||b>=12)))?0:1)" >nul 2>&1
if errorlevel 1 goto :NODE_OLD
where npm >nul 2>&1
if errorlevel 1 goto :NPM_MISSING

REM Create the virtual environment only once.
if not exist "%VENV_PY%" (
    echo [1/6] Creating Python virtual environment...
    call %PY_LAUNCH% -m venv "%PROJECT_ROOT%\.venv-p4"
    if errorlevel 1 goto :VENV_FAILED
) else (
    echo [1/6] Reusing Python virtual environment...
)
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 goto :VENV_OLD

REM Install/update pinned backend and development dependencies.
echo [2/6] Checking Python dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%PROJECT_ROOT%\backend\requirements-dev.txt"
if errorlevel 1 goto :PIP_FAILED

REM Install frontend dependencies on first launch, and again whenever
REM web\package-lock.json changes (for example after pulling new packages).
REM A copy of the lock file is kept in node_modules as the install marker.
set "LOCK_FILE=%PROJECT_ROOT%\web\package-lock.json"
set "LOCK_MARKER=%PROJECT_ROOT%\web\node_modules\.pramaan-installed-lock.json"
set "NEED_NPM=0"
if not exist "%PROJECT_ROOT%\web\node_modules" set "NEED_NPM=1"
if not exist "%LOCK_MARKER%" set "NEED_NPM=1"
if "%NEED_NPM%"=="0" (
    fc /b "%LOCK_FILE%" "%LOCK_MARKER%" >nul 2>&1
    if errorlevel 1 set "NEED_NPM=1"
)
if "%NEED_NPM%"=="1" (
    echo [3/6] Installing frontend dependencies with npm ci ^(new or changed package-lock.json^)...
    pushd "%PROJECT_ROOT%\web"
    call npm ci
    if errorlevel 1 (
        popd
        goto :NPM_INSTALL_FAILED
    )
    copy /y "%LOCK_FILE%" "%LOCK_MARKER%" >nul
    popd
) else (
    echo [3/6] Frontend dependencies are up to date.
)

REM The source imports the package as Pramaan.backend even when the downloaded
REM repository folder is named PRAMAAN-main. The tracked launcher\Pramaan shim
REM resolves that import name to this repository root at run time (no absolute paths).
if not exist "%PACKAGE_SHIM%\__init__.py" goto :SHIM_FAILED

REM Never overwrite existing local demo data automatically.
if not exist "%DEMO_DATA%\demo-state.json" (
    if exist "%DEMO_DATA%" goto :DATA_INCOMPLETE
    echo [4/6] Creating the synthetic demo workspace...
    set "PYTHONPATH=%LAUNCH_DIR%"
    set "PRAMAAN_DATA=%DEMO_DATA%"
    "%VENV_PY%" -m Pramaan.backend.demo reset
    if errorlevel 1 goto :DEMO_RESET_FAILED
) else (
    echo [4/6] Existing demo workspace found; preserving it.
)

REM Issue fresh local-only credentials for this launch. They expire after 8 hours.
set "PYTHONPATH=%LAUNCH_DIR%"
set "PRAMAAN_DATA=%DEMO_DATA%"
echo [5/6] Issuing local demo credentials...
set "CLIENT_TOKEN="
set "AUDITOR_TOKEN="
set "HUMAN_TOKEN="
for /f "delims=" %%T in ('"%VENV_PY%" -m Pramaan.backend.security issue --subject launcher-client --role client_employee --ttl 28800') do set "CLIENT_TOKEN=%%T"
for /f "delims=" %%T in ('"%VENV_PY%" -m Pramaan.backend.security issue --subject launcher-auditor --role auditor --ttl 28800') do set "AUDITOR_TOKEN=%%T"
for /f "delims=" %%T in ('"%VENV_PY%" -m Pramaan.backend.security issue --subject launcher-human-reviewer --role auditor --human-auditor --ttl 28800') do set "HUMAN_TOKEN=%%T"
if not defined CLIENT_TOKEN goto :CREDENTIAL_FAILED
if not defined AUDITOR_TOKEN goto :CREDENTIAL_FAILED
if not defined HUMAN_TOKEN goto :CREDENTIAL_FAILED
(
    echo PRAMAAN LOCAL DEMO CREDENTIALS
    echo Generated by START_PRAMAAN.bat. These credentials expire after 8 hours.
    echo Use only with this local synthetic-data demonstration. Do not share or commit this file.
    echo.
    echo CLIENT WORKSPACE - paste this into the login form:
    echo %CLIENT_TOKEN%
    echo.
    echo AUDITOR WORKSPACE - paste this into the login form:
    echo %AUDITOR_TOKEN%
    echo.
    echo HUMAN REVIEW AUTHORITY - keep this separate; do not give it to an AI agent:
    echo %HUMAN_TOKEN%
) > "%CREDENTIALS_FILE%"
if errorlevel 1 goto :CREDENTIAL_FILE_FAILED

REM Launch the API and frontend in separate windows.
echo [6/6] Starting PRAMAAN API and frontend...
start "PRAMAAN API - port 8000" "%ComSpec%" /k ""%~f0" api"
start "PRAMAAN Web - port 5173" "%ComSpec%" /k ""%~f0" web"

echo.
echo Waiting briefly for the local services to initialize...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173"
start "" notepad.exe "%CREDENTIALS_FILE%"
echo.
echo ============================================================
echo PRAMAAN launch commands have been started.
echo.
echo Web UI:       http://127.0.0.1:5173
echo API health:   http://127.0.0.1:8000/health
echo Credentials: %CREDENTIALS_FILE%
echo.
echo Paste the matching token from Notepad into the login screen.
echo Keep the API and Web terminal windows open while using PRAMAAN.
echo Close this launcher window when finished.
echo ============================================================
echo.
pause
exit /b 0

:ROOT_FAILED
echo ERROR: Could not switch to the repository root.
goto :FAIL
:PYTHON_MISSING
echo ERROR: Python 3.11 or newer was not found. Install Python 3.11+ and enable the Python launcher or PATH entry.
goto :FAIL
:NODE_MISSING
echo ERROR: Node.js was not found. Install Node.js 20.19+ or 22.12+ (or a newer supported release).
goto :FAIL
:NODE_OLD
echo ERROR: Unsupported Node.js version. Use Node 20.19+ or Node 22.12+.
goto :FAIL
:NPM_MISSING
echo ERROR: npm was not found. Reinstall Node.js with npm included and reopen this launcher.
goto :FAIL
:VENV_FAILED
echo ERROR: Could not create .venv-p4.
goto :FAIL
:VENV_OLD
echo ERROR: The existing .venv-p4 uses Python older than 3.11. Delete .venv-p4 and run this launcher again.
goto :FAIL
:PIP_FAILED
echo ERROR: Python dependency installation failed. Check your internet connection and try again.
goto :FAIL
:NPM_INSTALL_FAILED
echo ERROR: npm ci failed. Check your internet connection and web\package-lock.json.
echo If files are locked: close VS Code and any running Vite window, delete web\node_modules, then run this file again.
goto :FAIL
:SHIM_FAILED
echo ERROR: The Python package import shim launcher\Pramaan\__init__.py is missing. Restore it from the repository.
goto :FAIL
:DATA_INCOMPLETE
echo ERROR: .demo\runtime exists but has no demo-state.json.
echo To avoid deleting local work, the launcher did not reset it. Back it up, then rename or remove .demo\runtime and retry.
goto :FAIL
:DEMO_RESET_FAILED
echo ERROR: Synthetic demo initialization failed. Review the error output above.
goto :FAIL
:CREDENTIAL_FAILED
echo ERROR: Could not issue one or more local demo credentials.
goto :FAIL
:CREDENTIAL_FILE_FAILED
echo ERROR: Could not write the local demo credential file.
goto :FAIL
:FAIL
echo.
echo PRAMAAN did not finish starting. Fix the error above and run START_PRAMAAN.bat again.
echo.
pause
exit /b 1
