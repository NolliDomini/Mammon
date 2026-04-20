@echo off
SETLOCAL EnableDelayedExpansion

:: 0. Ensure we are running from the boot directory
cd /d "%~dp0"
set "ROOT_DIR=%~dp0.."

echo ============================================================
echo           MAMMON TRADING ENGINE - SHUTDOWN
echo ============================================================
echo.

:: 1. Check for Docker
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Docker CLI not found. Cannot stop containers.
    pause
    exit /b 1
)

:: 2. Check for docker-compose.yml
if not exist "!ROOT_DIR!\docker-compose.yml" (
    echo [!] Warning: docker-compose.yml not found in !ROOT_DIR!
    echo [!] Are you sure you are in the correct directory?
    pause
    exit /b 1
)

echo [*] Stopping all Mammon containers...
docker compose -f "!ROOT_DIR!\docker-compose.yml" down --remove-orphans

if %errorlevel% equ 0 (
    echo.
    echo [+] Mammon has been safely shut down.
) else (
    echo.
    echo [!] There was an issue stopping the containers.
    echo [!] Please check Docker Desktop.
)

echo.
timeout /t 5 >nul
