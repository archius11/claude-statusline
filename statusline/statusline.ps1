# claude-statusline launcher (Windows / PowerShell).
#
# All rendering logic lives in claude-statusline-render.py — one Python core
# shared with statusline.sh (Linux / WSL / macOS). This shim sets UTF-8 output
# so box-drawing / emoji glyphs survive, then hands Claude Code's JSON (stdin)
# straight to Python. If no Python is found we degrade to a bare directory line
# so the status bar never breaks.
#
# https://github.com/archius11/claude-statusline                     MIT License

$ErrorActionPreference = 'Continue'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    # InputEncoding too: Claude Code sends the JSON payload as UTF-8, and without
    # this Windows PowerShell 5.1 decodes redirected stdin with the OEM code page
    # (cp437/cp866), mangling non-ASCII workspace paths before Python ever sees
    # them (and breaking the JSON parse on multibyte code pages).
    [Console]::InputEncoding  = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding           = [Console]::OutputEncoding
} catch {}

$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$render = Join-Path $here 'claude-statusline-render.py'

# Read Claude Code's JSON payload from stdin (forwarded to Python below).
$payload = [Console]::In.ReadToEnd()

# Resolve a Python interpreter: the py launcher (py -3), then python, then python3.
$pyExe  = $null
$pyArgs = @()
foreach ($cand in @('py', 'python', 'python3')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $pyExe = $cand
        if ($cand -eq 'py') { $pyArgs = @('-3') }
        break
    }
}

if ($pyExe) {
    $payload | & $pyExe @pyArgs $render
    if ($LASTEXITCODE -eq 0) { exit 0 }
    # Non-zero exit means no usable Python ran: most often the Microsoft Store
    # python.exe stub that ships on PATH by default (it prints an "install from
    # the Store" notice to stderr, emits nothing on stdout, and exits 9009). Fall
    # through to the dependency-free line so the bar is never silently blank.
}

# No (usable) Python: dependency-free fallback — just the current directory.
$cwd = (Get-Location).Path
$up  = $env:USERPROFILE
if ($up -and $cwd.StartsWith($up, [System.StringComparison]::OrdinalIgnoreCase)) {
    $cwd = '~' + $cwd.Substring($up.Length)
}
[Console]::Out.WriteLine(($cwd -replace '\\', '/'))
exit 0
