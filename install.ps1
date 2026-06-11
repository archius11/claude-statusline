# claude-statusline installer (Windows / PowerShell).
#
# Thin wrapper around the cross-platform Python installer (statusline\install.py)
# so the install logic lives once and runs identically on every platform.
# Respects CLAUDE_CONFIG_DIR. Undo with .\uninstall.ps1
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
#
# https://github.com/archius11/claude-statusline                     MIT License

$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$installer = Join-Path $here 'statusline\install.py'

$pyExe  = $null
$pyArgs = @()
foreach ($cand in @('py', 'python', 'python3')) {
    if (-not (Get-Command $cand -ErrorAction SilentlyContinue)) { continue }
    $probe = @(); if ($cand -eq 'py') { $probe = @('-3') }
    # Reject the Microsoft Store python.exe stub (and any broken shim): it is on
    # PATH by default on Windows 10/11, so Get-Command alone would pick a dead
    # interpreter and the user would see the Store's message instead of ours. A
    # real Python answers '--version' with exit code 0; the stub exits non-zero.
    try { & $cand @probe '--version' *> $null } catch { continue }
    if ($LASTEXITCODE -ne 0) { continue }
    $pyExe = $cand
    $pyArgs = $probe
    break
}

if (-not $pyExe) {
    Write-Error "Python 3 not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run this installer."
    exit 1
}

& $pyExe @pyArgs $installer @args
exit $LASTEXITCODE
