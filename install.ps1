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
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $pyExe = $cand
        if ($cand -eq 'py') { $pyArgs = @('-3') }
        break
    }
}

if (-not $pyExe) {
    Write-Error "Python 3 not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run this installer."
    exit 1
}

& $pyExe @pyArgs $installer @args
exit $LASTEXITCODE
