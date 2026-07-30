<#
.SYNOPSIS
    Build Warden-Setup-<version>.exe.

.DESCRIPTION
    Runs the bundle build, then compiles installer\warden.iss with Inno Setup.
    The result is a single file to hand someone: no zip to extract, a Start Menu
    entry, an uninstaller, and an entry in Add/Remove Programs.

    Build artefacts belong on a GitHub Release rather than in the repository --
    the standard installer would fit, but the offline edition is 967 MB, past
    both GitHub's 100 MB file limit and Vercel's. The website's download button
    points at the release, so it needs no editing when a version ships:

        https://github.com/genix2600/warden/releases/latest/download/Warden-Setup-0.1.0.exe

.PARAMETER SkipBuild
    Compile the installer against the existing dist\Warden. For iterating on the
    .iss itself, where the payload has not changed.

.PARAMETER Offline
    Build the edition that carries the model weights inside it -- about 967 MB
    rather than 46 MB. Stage the payload with scripts\fetch-model.ps1 (no
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

# Warden runs without a model, but a build with no *runtime* cannot even fetch
# one, so that absence is permanent and should never pass unremarked into
# something handed to strangers. Weights being present or absent decides which
# edition this is, and the two must not end up under the same filename.
$runtimeDir = Join-Path $root 'dist\Warden\_internal\runtime'
if (-not (Test-Path (Join-Path $runtimeDir 'ollama.exe'))) {
    Write-Warning "This bundle has no model runtime, so it cannot download a model"
    Write-Warning "either -- it is stuck on the rules engine. Run"
    Write-Warning "scripts\fetch-model.ps1 -RuntimeOnly first."
}
$hasWeights = Test-Path (Join-Path $runtimeDir 'models')
if ($Offline -and -not $hasWeights) {
    throw "-Offline was asked for, but no weights are staged. Re-run scripts\fetch-model.ps1 without -RuntimeOnly."
}
if (-not $Offline -and $hasWeights) {
    Write-Warning "Weights are staged but -Offline was not passed, so this would be a"
    Write-Warning "967 MB installer under the standard name. Re-stage with -RuntimeOnly."
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
