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
#>
[CmdletBinding()]
param([string]$Model = 'qwen2.5:1.5b-instruct')

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

Write-Step "Pulling $Model"
& $ollama pull $Model
if ($LASTEXITCODE -ne 0) { throw "could not pull $Model" }

$source = Join-Path $env:USERPROFILE '.ollama\models'
if (-not (Test-Path $source)) { throw "no model store at $source" }

# -- Stage --------------------------------------------------------------------

$runtime = Join-Path $root 'runtime'
if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
New-Item -ItemType Directory $runtime | Out-Null

Write-Step "Staging into runtime\"
Copy-Item $ollama (Join-Path $runtime 'ollama.exe')

# Ollama ships supporting DLLs and GPU runners beside the executable. Missing
# them shows up only at inference time, which is far too late to notice.
$binDir = Split-Path -Parent $ollama
foreach ($extra in @('*.dll', 'lib')) {
    $found = Join-Path $binDir $extra
    if (Test-Path $found) { Copy-Item $found $runtime -Recurse -Force }
}

Copy-Item $source (Join-Path $runtime 'models') -Recurse -Force

# -- Attribution --------------------------------------------------------------

$notice = @"
Third-party components bundled with Warden
==========================================

ollama.exe and supporting libraries
    Ollama, MIT License. https://github.com/ollama/ollama

models/
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
