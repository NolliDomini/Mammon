$ErrorActionPreference = "Stop"
$WarningPreference = "SilentlyContinue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "           MAMMON TRADING ENGINE - WEB INSTALLER" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Dependency Checks
Write-Host "[*] Checking for Python..."
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "    Download: https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "    (Make sure to check 'Add Python to PATH' during installation)" -ForegroundColor Red
    exit 1
}

Write-Host "[*] Checking for Docker..."
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Docker Desktop is not installed." -ForegroundColor Red
    Write-Host "    Download: https://www.docker.com/products/docker-desktop" -ForegroundColor Red
    exit 1
}

# 2. Installation Path
$InstallDir = Join-Path -Path $env:USERPROFILE -ChildPath "Mammon"
Write-Host "[*] Target Directory: $InstallDir"

if (Test-Path -Path $InstallDir) {
    Write-Host "[!] Directory already exists at $InstallDir" -ForegroundColor Yellow
    $response = Read-Host "Do you want to overwrite it? This will delete the existing folder. (Y/N)"
    if ($response -match "^y$|^yes$") {
        Write-Host "[*] Removing existing directory..."
        Remove-Item -Path $InstallDir -Recurse -Force
    } else {
        Write-Host "[!] Installation aborted."
        exit 1
    }
}

# 3. Download and Extract ZIP
# TODO: Replace with the actual URL when the repository is public
$ZipUrl = "https://github.com/YOUR_ORG/Mammon/archive/refs/heads/main.zip" 
$TempZip = Join-Path -Path $env:TEMP -ChildPath "Mammon_Download_$([guid]::NewGuid().ToString().Substring(0,8)).zip"
$TempExt = Join-Path -Path $env:TEMP -ChildPath "Mammon_Extract_$([guid]::NewGuid().ToString().Substring(0,8))"

Write-Host "[*] Downloading Mammon Trading Engine..."
try {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing
} catch {
    Write-Host "[!] Failed to download from $ZipUrl" -ForegroundColor Red
    Write-Host "    Update `$ZipUrl in the installer script with your valid repository URL." -ForegroundColor Yellow
    exit 1
}

Write-Host "[*] Extracting files..."
Expand-Archive -Path $TempZip -DestinationPath $TempExt -Force

# GitHub ZIPs extract into a subfolder (e.g., 'Mammon-main'). Find it and move it.
$InnerDir = Get-ChildItem -Path $TempExt -Directory | Select-Object -First 1
Move-Item -Path $InnerDir.FullName -Destination $InstallDir -Force

# Cleanup
Write-Host "[*] Cleaning up temporary files..."
Remove-Item -Path $TempZip -Force
Remove-Item -Path $TempExt -Recurse -Force

# 5. Register MCP Server (Optional, for Claude Desktop)
$ClaudeConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json"
if (Test-Path $ClaudeConfigPath) {
    Write-Host "[*] Found Claude Desktop configuration. Registering Mammon MCP..."
    try {
        $config = Get-Content $ClaudeConfigPath | ConvertFrom-Json
        if (-not $config.mcpServers) { $config | Add-Member -MemberType NoteProperty -Name mcpServers -Value @{} }
        
        # Add or Update the mammon-db server
        $config.mcpServers | Add-Member -MemberType NoteProperty -Name "mammon-db" -Value @{
            type = "sse"
            url  = "http://localhost:5001/sse"
        } -ErrorAction SilentlyContinue
        
        $config | ConvertTo-Json -Depth 10 | Set-Content $ClaudeConfigPath
        Write-Host "[+] Mammon MCP registered successfully." -ForegroundColor Green
    } catch {
        Write-Host "[!] Warning: Failed to update Claude Desktop configuration." -ForegroundColor Yellow
    }
}

# 6. Bootstrap
$BootBat = Join-Path -Path $InstallDir -ChildPath "boot\Start_Mammon.bat"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Mammon Engine has been successfully installed to:"
Write-Host "   $InstallDir"
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (Test-Path -Path $BootBat) {
    Write-Host "[+] Launching Mammon Bootstrapper..." -ForegroundColor Green
    # Launch in a new window so the installer script can terminate cleanly
    Start-Process -FilePath $BootBat -WorkingDirectory (Join-Path -Path $InstallDir -ChildPath "boot")
} else {
    Write-Host "[!] Installation finished, but Start_Mammon.bat was not found." -ForegroundColor Yellow
    Write-Host "    You may need to start it manually." -ForegroundColor Yellow
}
