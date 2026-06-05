#!/usr/bin/env bash
# claude-statusline launcher (Linux / WSL / macOS).
#
# All rendering logic lives in claude-statusline-render.py — one Python core
# shared with the Windows launcher (statusline.ps1). This shim just locates a
# Python interpreter and hands Claude Code's JSON (stdin) straight to it.
#
# If python is unavailable we degrade to a bare, dependency-free directory line
# so the status bar never breaks. python3 remains a documented requirement.
#
# https://github.com/archius11/claude-statusline                     MIT License

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER="$SCRIPT_DIR/claude-statusline-render.py"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$RENDER"
elif command -v python >/dev/null 2>&1; then
    exec python "$RENDER"
fi

# No Python: drain stdin and print just the current directory.
cat >/dev/null 2>&1 || true
printf '%s\n' "${PWD/#$HOME/~}"
