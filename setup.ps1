# Thread Network Monitor - Setup Script for Windows
# Run as Administrator on Q

$ErrorActionPreference = "Continue"
$installDir = "C:\tools\thread-monitor"

Write-Host "=== Thread Network Monitor Setup ===" -ForegroundColor Cyan
Write-Host ""

# Create install directory
if (!(Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}

# --- Step 1: Check Python ---
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pyVer = python --version 2>&1
    Write-Host "  Found: $pyVer" -ForegroundColor Green
} else {
    $pyPath = "C:\Program Files\Python312\python.exe"
    if (Test-Path $pyPath) {
        Write-Host "  Found Python at $pyPath (not in PATH yet)" -ForegroundColor Yellow
        $env:PATH = "C:\Program Files\Python312;C:\Program Files\Python312\Scripts;$env:PATH"
        [Environment]::SetEnvironmentVariable("PATH", "C:\Program Files\Python312;C:\Program Files\Python312\Scripts;" + [Environment]::GetEnvironmentVariable("PATH", "Machine"), "Machine")
        Write-Host "  Added to PATH" -ForegroundColor Green
    } else {
        Write-Host "  Python not found. Downloading..." -ForegroundColor Yellow
        $pyInstaller = "$env:TEMP\python-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe" -OutFile $pyInstaller -UseBasicParsing
        Write-Host "  Installing Python 3.12..."
        Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -NoNewWindow
        $env:PATH = "C:\Program Files\Python312;C:\Program Files\Python312\Scripts;$env:PATH"
        Write-Host "  Python installed" -ForegroundColor Green
    }
}

# --- Step 2: Check Wireshark ---
Write-Host "[2/5] Checking Wireshark..." -ForegroundColor Yellow
$ws = "C:\Program Files\Wireshark\Wireshark.exe"
if (Test-Path $ws) {
    Write-Host "  Found Wireshark" -ForegroundColor Green
} else {
    Write-Host "  Wireshark not found. Downloading..." -ForegroundColor Yellow
    $wsInstaller = "$env:TEMP\wireshark-installer.exe"
    Invoke-WebRequest -Uri "https://2.na.dl.wireshark.org/win64/Wireshark-4.4.3-x64.exe" -OutFile $wsInstaller -UseBasicParsing
    Write-Host "  Installing Wireshark (this may take a minute)..."
    Start-Process -FilePath $wsInstaller -ArgumentList "/S /desktopicon=yes" -Wait -NoNewWindow
    Write-Host "  Wireshark installed" -ForegroundColor Green
}

# --- Step 3: Install Python dependencies ---
Write-Host "[3/5] Installing Python packages..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet 2>$null
python -m pip install pyserial flask --quiet
Write-Host "  pyserial + flask installed" -ForegroundColor Green

# --- Step 4: Install nrfutil and flash dongle ---
Write-Host "[4/5] Setting up nRF Sniffer..." -ForegroundColor Yellow
python -m pip install nrfutil --quiet 2>$null

# Download sniffer firmware
$snifferDir = "$installDir\nrf-sniffer"
if (!(Test-Path $snifferDir)) {
    New-Item -ItemType Directory -Path $snifferDir -Force | Out-Null
}

$fwUrl = "https://github.com/NordicSemiconductor/nRF-Sniffer-for-802.15.4/archive/refs/heads/main.zip"
$zipPath = "$env:TEMP\nrf-sniffer.zip"

if (!(Test-Path "$snifferDir\main")) {
    Write-Host "  Downloading nRF Sniffer package..."
    Invoke-WebRequest -Uri $fwUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $snifferDir -Force
    Write-Host "  Downloaded" -ForegroundColor Green
} else {
    Write-Host "  nRF Sniffer package already present" -ForegroundColor Green
}

# Copy extcap plugin to Wireshark
$extcapDir = "$env:APPDATA\Wireshark\extcap"
if (!(Test-Path $extcapDir)) {
    New-Item -ItemType Directory -Path $extcapDir -Force | Out-Null
}

$snifferSrc = "$snifferDir\nRF-Sniffer-for-802.15.4-main\nrf802154_sniffer"
if (Test-Path $snifferSrc) {
    Copy-Item "$snifferSrc\nrf802154_sniffer.py" "$extcapDir\" -Force
    Copy-Item "$snifferSrc\nrf802154_sniffer.bat" "$extcapDir\" -Force
    Write-Host "  Extcap plugin installed for Wireshark" -ForegroundColor Green
}

# --- Step 5: Copy dashboard files ---
Write-Host "[5/5] Deploying dashboard..." -ForegroundColor Yellow
# These will be copied by the deploy script
Write-Host "  Dashboard ready at $installDir" -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Flash the dongle firmware (requires pressing the RESET button on the dongle):"
Write-Host "     cd $snifferDir\nRF-Sniffer-for-802.15.4-main"
Write-Host '     nrfutil pkg generate --hw-version 52 --sd-req 0x00 --application nrf802154_sniffer\nrf802154_sniffer_nrf52840dongle.hex --application-version 1 sniffer.zip'
Write-Host '     # Press the RESET button on the dongle, then:'
Write-Host '     nrfutil dfu usb-serial -pkg sniffer.zip -p COM3'
Write-Host ""
Write-Host "  2. Start the dashboard:"
Write-Host "     cd $installDir"
Write-Host "     python dashboard.py --port COM3 --channel 15"
Write-Host ""
Write-Host "  3. Open http://localhost:8154 in your browser"
Write-Host ""
