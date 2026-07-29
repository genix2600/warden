<#
.SYNOPSIS
    Package Warden into a folder that can be copied to another machine.

.DESCRIPTION
    Produces dist\Warden\Warden.exe. Every step is checked and the script stops
    on the first failure: a build that half-succeeds is worse than one that
    fails, because a bundle missing its interface or a hidden import only shows
    that up when someone double-clicks it in front of an audience.

    The result is unsigned, so SmartScreen will warn on first run on a machine
    that has not seen it before. That is expected and documented in the README.

.PARAMETER SkipUi
    Reuse the existing ui\dist instead of rebuilding it. For iterating on
    packaging itself, where the interface has not changed.
#>
[CmdletBinding()]
param([switch]$SkipUi)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run .\run.ps1 once first."
}

# -- The interface ------------------------------------------------------------

if (-not $SkipUi) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm is not on PATH. Warden needs Node 18 or newer to build the interface."
    }
    Write-Step "Building the interface"
    Push-Location ui
    try {
        # The TypeScript types are generated from the backend's OpenAPI document,
        # so this has to run before tsc or the build compiles against stale types.
        npm run gen:types
        if ($LASTEXITCODE -ne 0) { throw "type generation failed" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "interface build failed" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path 'ui\dist\index.html')) {
    throw "ui\dist\index.html is missing. Drop -SkipUi and build the interface."
}

# -- PyInstaller --------------------------------------------------------------

# find_spec rather than a bare import: an import that fails writes a traceback to
# stderr, and redirecting a native command's stderr in PowerShell 5.1 raises
# NativeCommandError even when the exit code is what we asked for.
& $venvPython -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Step "Installing PyInstaller"
    & $venvPython -m pip install -e ".[build]" --quiet
    if ($LASTEXITCODE -ne 0) { throw "could not install PyInstaller" }
}

# PyInstaller clears dist\ and build\ itself, but fails outright if anything
# holds a handle -- and something usually does for a few seconds after a build:
# OneDrive indexing the new files, Defender scanning them, or a previous
# Warden.exe still shutting down. Retrying beats making the developer guess.
function Remove-Tree($path) {
    if (-not (Test-Path $path)) { return }
    foreach ($attempt in 1..5) {
        try {
            Remove-Item $path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 5) {
                throw "could not clear $path -- close Warden.exe and pause OneDrive sync, then retry"
            }
            Write-Note "$path is locked; retrying ($attempt of 5)"
            Start-Sleep -Seconds 2
        }
    }
}

Get-Process Warden -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Tree (Join-Path $root 'build')
Remove-Tree (Join-Path $root 'dist')

Write-Step "Packaging"
# PyInstaller logs progress to stderr. With ErrorActionPreference set to Stop,
# PowerShell 5.1 turns each of those lines into a NativeCommandError and kills
# the build partway through, so the preference is relaxed across the call and
# the exit code checked explicitly instead.
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $venvPython -m PyInstaller warden.spec --clean --noconfirm --log-level WARN
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "PyInstaller failed (exit $code)" }

# -- Prove it produced what it claims -----------------------------------------

$exe = Join-Path $root 'dist\Warden\Warden.exe'
if (-not (Test-Path $exe)) { throw "PyInstaller reported success but $exe does not exist" }

# The interface is the one asset whose absence is invisible until launch: the
# app starts, serves a 503 and shows an empty window. Checking it here turns a
# demo-day failure into a build-time one.
$bundledUi = Join-Path $root 'dist\Warden\_internal\ui\dist\index.html'
if (-not (Test-Path $bundledUi)) {
    throw "the bundle has no interface at _internal\ui\dist -- check datas in warden.spec"
}

# The bundled model is the difference between a shared build that answers with
# a real model and one that quietly falls back to the rules engine. Absent is
# legal -- the build still works -- but it should never be a surprise.
$bundledModel = Join-Path $root 'dist\Warden\_internal\runtime\ollama.exe'
if (Test-Path $bundledModel) {
    Write-Note "model runtime bundled: a shared copy will answer with a real model"
} else {
    Write-Warning "No model runtime in this build. On a machine without Ollama the"
    Write-Warning "header will read 'rules engine'. Run scripts\fetch-model.ps1 first."
}

$size = '{0:N0} MB' -f ((Get-ChildItem 'dist\Warden' -Recurse -File |
            Measure-Object -Property Length -Sum).Sum / 1MB)

# Zip the whole folder, because someone will inevitably try to send just the
# .exe -- which is meaningless without _internal\ beside it. The zip is the
# thing to link to.
$version = (Select-String -Path 'pyproject.toml' -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$archive = Join-Path $root "dist\Warden-$version.zip"
Write-Step "Compressing"
Remove-Item $archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path 'dist\Warden' -DestinationPath $archive -CompressionLevel Optimal
$zipSize = '{0:N0} MB' -f ((Get-Item $archive).Length / 1MB)

Write-Host ""
Write-Step "Built dist\Warden ($size)"
Write-Note "Share:   $archive ($zipSize)"
Write-Note "Launch:  $exe"
Write-Note "Verify it properly by copying the whole dist\Warden folder somewhere"
Write-Note "outside this repository and running it from there."
Write-Note "Unsigned, so SmartScreen warns on first run: More info -> Run anyway."
