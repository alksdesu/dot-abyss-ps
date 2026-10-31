param(
    [string]$Source = (Join-Path $PSScriptRoot '..\..\dotabyss_x_cl'),
    [string]$Destination,
    [string]$Release,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$preparePython = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $preparePython -PathType Leaf)) { throw 'Run setup-pc.ps1 to prepare the project environment first.' }
$arguments = @((Join-Path $PSScriptRoot 'prepare_client.py'))
if ($Destination) { $arguments += @('--destination', $Destination) }
if ($Release) { $arguments += @('--release', $Release) }
if ($Verify) { $arguments += '--verify' } else { $arguments += @('--source', $Source) }
& $preparePython @arguments
if ($LASTEXITCODE -ne 0) { throw 'Local PC client preparation failed.' }
