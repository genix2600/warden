<#
.SYNOPSIS
    Set up if needed, then launch Warden.

.DESCRIPTION
    Safe to run repeatedly: every step checks whether it is already done. The
    first run takes a couple of minutes (virtual environment, npm install, a
    production build of the interface); later runs skip straight to launching.

.PARAMETER Headless
    Run the backend only, with no window. The API is then browsable at /docs.

.PARAMETER Rebuild
    Force the interface to be rebuilt even if ui/dist already exists.
#>
[CmdletBinding()]
param(
    [switch]$Headless,
    [switch]$Rebuild,
    [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }

# -- Python -------------------------------------------------------------------

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not on PATH. Warden needs Python 3.11 or newer."
}

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating the virtual environment"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
}

# The marker file records which pyproject produced the current install, so
# dependencies are reinstalled when they change and skipped when they have not.
$stamp = Join-Path $PSScriptRoot '.venv\.warden-deps'
$pyprojectHash = (Get-FileHash 'pyproject.toml' -Algorithm SHA256).Hash
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $pyprojectHash) {
    Write-Step "Installing Python dependencies"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -e ".[dev]" --quiet
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
    Set-Content -Path $stamp -Value $pyprojectHash -Encoding utf8
} else {
    Write-Note "Python dependencies are up to date"
}

# -- Interface ----------------------------------------------------------------

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not on PATH. Warden needs Node 18 or newer to build the interface."
}

if (-not (Test-Path 'ui\node_modules')) {
    Write-Step "Installing interface dependencies"
    Push-Location ui
    npm install --no-fund --no-audit
    Pop-Location
}

if ($Rebuild -or -not (Test-Path 'ui\dist\index.html')) {
    Write-Step "Building the interface"
    Push-Location ui
    # Types are generated from the backend's OpenAPI document rather than kept
    # in sync by hand, so this must run before tsc.
    npm run gen:types
    npm run build
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "interface build failed" }
} else {
    Write-Note "Interface already built (use -Rebuild to force)"
}

# -- Launch -------------------------------------------------------------------

$arguments = @('-m', 'warden')
if ($Headless) { $arguments += '--headless' }
if ($Port -gt 0) { $arguments += @('--port', $Port) }

Write-Step "Starting Warden"
if (-not ([Security.Principal.WindowsPrincipal]::new(
            [Security.Principal.WindowsIdentity]::GetCurrent()
        )).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Note "Running as a standard user. Warden will refuse elevated actions"
    Write-Note "rather than fail halfway through one. Run elevated for device"
    Write-Note "restarts and hardware temperature sensors."
}

& $venvPython @arguments
