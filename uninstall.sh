#!/usr/bin/env bash
# claude-statusline uninstaller (Linux / WSL / macOS).
#
# Thin wrapper around the cross-platform Python uninstaller
# (statusline/uninstall.py). Respects CLAUDE_CONFIG_DIR.
#
# https://github.com/archius11/claude-statusline                     MIT License

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNINSTALLER="$HERE/statusline/uninstall.py"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$UNINSTALLER" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$UNINSTALLER" "$@"
fi

printf 'python3 not found, cannot safely edit settings.json.\n' >&2
exit 1
