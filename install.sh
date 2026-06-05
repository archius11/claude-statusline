#!/usr/bin/env bash
# claude-statusline installer (Linux / WSL / macOS).
#
# Thin wrapper around the cross-platform Python installer (statusline/install.py)
# so the install logic lives once and runs identically on every platform.
# Respects CLAUDE_CONFIG_DIR. Undo with ./uninstall.sh
#
# https://github.com/archius11/claude-statusline                     MIT License

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$HERE/statusline/install.py"

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$INSTALLER" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$INSTALLER" "$@"
fi

printf 'python3 not found. Install it first:\n' >&2
printf '  Debian/Ubuntu:  sudo apt install python3\n' >&2
printf '  macOS:          brew install python3\n' >&2
exit 1
