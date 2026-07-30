<#
.SYNOPSIS
    Stage the local model runtime into runtime\, ready to be bundled.

.DESCRIPTION
    Copies ollama.exe and the pulled model weights out of the machine's Ollama
    installation and into runtime\, which warden.spec bundles into the build.
    The result is that a shared build answers with a real model on a machine
    that has never installed anything -- which is the whole point.

    runtime\ is gitignored: it is roughly a gigabyte of third-party binaries and
    weights, and neither belongs in the repository. This script is how anyone
    rebuilds it.

    Ollama is MIT licensed and Qwen2.5 is Apache-2.0; both licences are copied
    alongside the binaries so the bundle carries its own attribution.

.PARAMETER Model
    The model tag to stage. The default is deliberately small: Warden ships to
    laptops with no discrete GPU, where a 7B model produces 4-6 tokens/s and
    never finishes a decision inside the client's timeout.

.PARAMETER RuntimeOnly
    Stage ollama.exe and its CPU libraries, but not the model weights.

    This is the default edition. The weights are 940 MB of the 1,061 MB staged
    here, and leaving them out takes the installer from 967 MB to 46 MB
    -- which is the difference between someone trying Warden and closing the
    tab. Warden then fetches the model on request, from the Readiness page,
    into %LOCALAPPDATA% where it survives an upgrade.

    Run without this flag to stage everything and build the offline edition,
    for machines that will never have a usable connection.
#>
[CmdletBinding()]
param(
    [string]$Model = 'qwen2.5:1.5b-instruct',
    [switch]$RuntimeOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -Path $root

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }

# -- Locate Ollama ------------------------------------------------------------

$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $candidate) { $ollama = $candidate }
}
if (-not $ollama) {
    throw "Ollama is not installed. Run: winget install --id Ollama.Ollama -e"
}
Write-Note "using $ollama"

# -- Pull the model -----------------------------------------------------------

# `ollama pull` draws a progress bar on stderr. With ErrorActionPreference set
# to Stop, PowerShell 5.1 turns each of those lines into a NativeCommandError
# and kills the script mid-download, so the preference is relaxed across the
# call and the exit code checked explicitly instead.
if ($RuntimeOnly) {
    Write-Note "runtime only: skipping the model, Warden will fetch it on request"
}
$already = $RuntimeOnly -or ((& $ollama list) -match [regex]::Escape($Model))
if ($already) {
    if (-not $RuntimeOnly) { Write-Note "$Model is already pulled" }
} else {
    Write-Step "Pulling $Model"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $ollama pull $Model
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) { throw "could not pull $Model (exit $code)" }
}

$source = Join-Path $env:USERPROFILE '.ollama\models'
if (-not $RuntimeOnly -and -not (Test-Path $source)) { throw "no model store at $source" }

# -- Stage --------------------------------------------------------------------

$runtime = Join-Path $root 'runtime'
if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
New-Item -ItemType Directory $runtime | Out-Null

Write-Step "Staging into runtime\"
Copy-Item $ollama (Join-Path $runtime 'ollama.exe')

# Ollama ships supporting libraries beside the executable, and missing them
# shows up only at inference time, which is far too late to notice.
#
# The vendor GPU runners are excluded: CUDA and ROCm are 2.6 GB between them and
# neither can be used by the integrated graphics this build targets. On a
# machine that does have a discrete GPU, Ollama simply runs on the CPU instead
# -- slower, but correct, and worth it to keep the download shareable.
#
# The per-generation CPU libraries are all kept, and they are the reason this
# travels: Ollama selects ggml-cpu-haswell, -zen4, -alderlake and so on at
# runtime, so one bundle works on an AMD laptop and a six-year-old Intel one.
$excluded = @('cuda_v12', 'cuda_v13', 'rocm_v7_1')
$binDir = Split-Path -Parent $ollama
Get-ChildItem $binDir -Filter '*.dll' -ErrorAction SilentlyContinue |
    Copy-Item -Destination $runtime -Force

$libSource = Join-Path $binDir 'lib'
if (Test-Path $libSource) {
    $libTarget = Join-Path $runtime 'lib'
    New-Item -ItemType Directory $libTarget -Force | Out-Null
    Get-ChildItem $libSource | ForEach-Object {
        $inner = Join-Path $libTarget $_.Name
        New-Item -ItemType Directory $inner -Force | Out-Null
        Get-ChildItem $_.FullName -Force |
            Where-Object { $_.Name -notin $excluded } |
            Copy-Item -Destination $inner -Recurse -Force
    }
}

if (-not $RuntimeOnly) {
    Copy-Item $source (Join-Path $runtime 'models') -Recurse -Force
}

# -- Attribution --------------------------------------------------------------

$notice = @"
Third-party components bundled with Warden
==========================================

ollama.exe and supporting libraries
    Ollama, MIT License. https://github.com/ollama/ollama

models/ (offline edition only)
    $Model weights. Qwen2.5 is released by Alibaba Cloud under Apache License 2.0.
    https://huggingface.co/Qwen

Both are redistributed unmodified. Warden itself is licensed separately; see
LICENSE in the application folder.
"@
Set-Content -Path (Join-Path $runtime 'THIRD-PARTY-NOTICES.txt') -Value $notice -Encoding utf8

# -- Report -------------------------------------------------------------------

$size = '{0:N0} MB' -f ((Get-ChildItem $runtime -Recurse -File |
            Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host ""
Write-Step "Staged runtime\ ($size)"
Write-Note "warden.spec will bundle this automatically on the next build."
