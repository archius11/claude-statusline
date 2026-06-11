# claude-statusline uninstaller (Windows / PowerShell).
#
# Thin wrapper around the cross-platform Python uninstaller
# (statusline\uninstall.py). Respects CLAUDE_CONFIG_DIR.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
#
# https://github.com/archius11/claude-statusline                     MIT License

$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$uninstaller = Join-Path $here 'statusline\uninstall.py'

$pyExe  = $null
$pyArgs = @()
foreach ($cand in @('py', 'python', 'python3')) {
    if (-not (Get-Command $cand -ErrorAction SilentlyContinue)) { continue }
    $probe = @(); if ($cand -eq 'py') { $probe = @('-3') }
    # Skip the Microsoft Store python.exe stub (on PATH by default): a real
    # Python answers '--version' with exit 0, the stub exits non-zero.
    try { & $cand @probe '--version' *> $null } catch { continue }
    if ($LASTEXITCODE -ne 0) { continue }
    $pyExe = $cand
    $pyArgs = $probe
    break
}

if (-not $pyExe) {
    Write-Error "Python 3 not found, cannot safely edit settings.json."
    exit 1
}

& $pyExe @pyArgs $uninstaller @args
exit $LASTEXITCODE
