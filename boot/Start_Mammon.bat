@echo off
SETLOCAL EnableDelayedExpansion

:: 0. Ensure we are running from the boot directory
cd /d "%~dp0"
set "ROOT_DIR=%~dp0.."

echo ============================================================
echo           MAMMON TRADING ENGINE - BOOTSTRAPPER
echo ============================================================
echo.

:: 1. Check for Python
echo [*] Checking for Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found in PATH.
    echo [!] Please install Python 3.12+ from https://www.python.org/downloads/
    echo [!] Ensure "Add Python to PATH" is checked during installation.
    pause
    exit /b 1
)

:: Verify Python version (optional but recommended)
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python 3.10 or higher is required.
    python --version
    pause
    exit /b 1
)

:: 2. Check for Docker Installation
echo [*] Checking for Docker...
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Docker CLI not found. 
    echo [!] Please install Docker Desktop from https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

:: 3. Check if Docker Daemon is Running
echo [*] Checking Docker Engine status...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Docker Engine is not responding.
    echo [!] Attempting to wake up Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    echo [*] Waiting for Docker to initialize (up to 60 seconds)...
    set /a TIMER=0
    :docker_wait
    docker info >nul 2>&1
    if %errorlevel% equ 0 goto docker_ready
    set /a TIMER+=5
    if %TIMER% geq 60 (
        echo [!] Docker failed to start in time.
        echo [!] Please start Docker Desktop manually and try again.
        pause
        exit /b 1
    )
    <nul set /p="."
    timeout /t 5 >nul
    goto docker_wait
)

:docker_ready
echo.
echo [+] Docker is ready.

:: 4. Run Onboarding Wizard
if not exist "!ROOT_DIR!\.env" (
    echo [*] First-time setup detected. Starting onboarding...
    if not exist "onboard.py" (
        echo [!] Error: onboard.py missing from boot/ directory.
        pause
        exit /b 1
    )
    python onboard.py
    if !errorlevel! neq 0 (
        echo [!] Onboarding failed or was cancelled.
        pause
        exit /b 1
    )
)

:: 5. Create Desktop Shortcut (One-time)
if not exist "%USERPROFILE%\Desktop\Mammon.lnk" (
    echo [*] Creating Desktop shortcut...
    set "ICON_PATH=shell32.dll,147"
    if exist "%~dp0icon.ico" set "ICON_PATH=%~dp0icon.ico"
    
    powershell -NoProfile -Command ^
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%USERPROFILE%\Desktop\Mammon.lnk');" ^
        "$s.TargetPath='%~dp0Start_Mammon.bat';" ^
        "$s.WorkingDirectory='%~dp0';" ^
        "$s.IconLocation='!ICON_PATH!';" ^
        "$s.Description='Start Mammon Trading Engine';" ^
        "$s.Save()" >nul 2>&1
    
    if exist "%USERPROFILE%\Desktop\Mammon.lnk" (
        echo [+] Shortcut created on Desktop.
    ) else (
        echo [!] Warning: Failed to create shortcut.
    )
)

:: 6. Pull/Build Containers
echo [*] Orchestrating infrastructure (Redis, TimescaleDB, Engine)...
docker compose -f "!ROOT_DIR!\docker-compose.yml" up -d --remove-orphans
if %errorlevel% neq 0 (
    echo [!] Failed to start Docker containers.
    echo [!] Check your docker-compose.yml or Docker logs for details.
    pause
    exit /b 1
)

:: 7. Wait for Engine to be Ready (with Timeout)
echo [*] Waiting for Mammon Dashboard to wake up...
where curl >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] curl not found. Skipping health check and waiting 10 seconds...
    timeout /t 10 >nul
    goto launch_browser
)

set MAX_RETRIES=30
set RETRY_COUNT=0

:wait_loop
curl -s http://localhost:5000/__health >nul
if %errorlevel% neq 0 (
    set /a RETRY_COUNT+=1
    if !RETRY_COUNT! geq !MAX_RETRIES! (
        echo.
        echo [!] Timeout waiting for the engine to respond.
        echo [!] Check logs: docker compose -f "!ROOT_DIR!\docker-compose.yml" logs dashboard
        pause
        exit /b 1
    )
    <nul set /p="."
    timeout /t 2 >nul
    goto wait_loop
)
echo.

:launch_browser
:: 8. Launch Dashboard
echo [+] Mammon is Online.
for /f "usebackq tokens=2 delims==" %%a in (`findstr /b "MAMMON_API_TOKEN=" "!ROOT_DIR!\.env"`) do set TOKEN=%%a

if "%TOKEN%"=="" (
    echo [!] Warning: MAMMON_API_TOKEN not found in .env. Launching without token...
    start "" "http://localhost:5000/"
) else (
    echo [*] Opening Dashboard...
    start "" "http://localhost:5000/?token=!TOKEN!"
)

echo.
echo ============================================================
echo   MAMMON ENGINE IS ACTIVE
echo ============================================================
echo   Dashboard: http://localhost:5000/
echo   MCP Server: http://localhost:5001/sse
echo   Shutdown:  Run boot\Stop_Mammon.bat
echo ============================================================
echo.
timeout /t 5 >nul
