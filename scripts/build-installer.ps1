<#
.SYNOPSIS
    Build Warden-Setup-<version>.exe.

.DESCRIPTION
    Runs the bundle build, then compiles installer\warden.iss with Inno Setup.
    The result is a single file to hand someone: no zip to extract, a Start Menu
    entry, an uninstaller, and an entry in Add/Remove Programs.

    The installer is roughly a gigabyte, which is too large for GitHub to accept
    as a repository file and too large for Vercel to serve. It belongs on a
    GitHub Release, where the website's download button points:

        https://github.com/genix2600/warden/releases/latest/download/Warden-Setup-0.1.0.exe

.PARAMETER SkipBuild
    Compile the installer against the existing dist\Warden. For iterating on the
    .iss itself, where the payload has not changed.

.PARAMETER Offline
    Build the edition that carries the model weights inside it -- about 967 MB
    rather than 160 MB. Stage the payload with scripts\fetch-model.ps1 (no
    -RuntimeOnly) first, or this produces the small build under the big name.
#>
[CmdletBinding()]
param([switch]$SkipBuild, [switch]$Offline)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }

# -- Inno Setup ---------------------------------------------------------------

# winget installs Inno Setup per-user by default, so %LOCALAPPDATA% has to be
# searched too -- the Program Files paths alone find nothing after a plain
# `winget install`.
$iscc = $null
foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $candidate) { $iscc = $candidate; break }
}
if (-not $iscc) {
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
}
if (-not $iscc) {
    throw "Inno Setup 6 is not installed. Run: winget install --id JRSoftware.InnoSetup -e"
}
Write-Note "using $iscc"

# -- The bundle ---------------------------------------------------------------

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot 'build-exe.ps1')
    if ($LASTEXITCODE -ne 0) { throw "the bundle build failed" }
}

if (-not (Test-Path (Join-Path $root 'dist\Warden\Warden.exe'))) {
    throw "dist\Warden\Warden.exe is missing. Drop -SkipBuild and build it."
}

# The model runtime is what makes a shared install behave like this machine. Its
# absence is legal but should never pass unremarked into something being handed
# to strangers.
if (-not (Test-Path (Join-Path $root 'dist\Warden\_internal\runtime\ollama.exe'))) {
    Write-Warning "This bundle has no model runtime. Anyone installing it will see"
    Write-Warning "'rules engine' in the header. Run scripts\fetch-model.ps1 first."
}

# -- Compile ------------------------------------------------------------------

Write-Step "Compiling the installer"
# ISCC writes progress to stderr, and PowerShell 5.1 with ErrorActionPreference
# set to Stop turns each line into a NativeCommandError and aborts the script.
# The third tool in this repository to need this; see build-exe.ps1 and
# fetch-model.ps1 for the same workaround.
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$edition = if ($Offline) { '-offline' } else { '' }
& $iscc "/DEdition=$edition" (Join-Path $root 'installer\warden.iss')
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) { throw "Inno Setup failed (exit $code)" }

# -- Report -------------------------------------------------------------------

$version = (Select-String -Path 'pyproject.toml' -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$setup = Join-Path $root "dist\Warden-Setup-$version$edition.exe"
if (-not (Test-Path $setup)) { throw "Inno Setup reported success but $setup does not exist" }

$size = '{0:N0} MB' -f ((Get-Item $setup).Length / 1MB)
Write-Host ""
Write-Step "Built $setup ($size)"
Write-Note "Too large for the repository. Attach it to a GitHub Release:"
Write-Note "  gh release create v$version `"$setup`" --title `"Warden $version`""
Write-Note "The website links to /releases/latest/download/, so it needs no edit."
