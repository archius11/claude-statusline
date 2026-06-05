---
description: Wire claude-statusline into settings.json (run after enabling the plugin)
allowed-tools: Bash(bash:*), Bash(powershell:*), Bash(powershell.exe:*), Bash(pwsh:*)
---

Run the bundled claude-statusline installer so the custom status line gets wired
into the user's `settings.json`. This is needed because Claude Code plugins
can't set the main `statusLine` directly.

The installer is cross-platform — one Python core (`statusline/install.py`) with
a thin launcher per OS. Pick the launcher for the user's operating system:

- **Linux / macOS / WSL:**

  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/install.sh"
  ```

- **Windows (PowerShell):**

  ```
  powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}\install.ps1"
  ```

Both wrappers run the same installer, which copies the renderer, schema and the
platform launcher into the Claude config dir and points `settings.json`'s
`statusLine` at it.

Steps:

1. Detect the platform and run the matching command above.
2. Report the installer's output to the user verbatim.
3. Remind them to **restart Claude Code** for the status line to take effect.

If the installer says Python 3 is missing, tell the user to install it and run
`/statusline-install` again:

- Debian/Ubuntu: `sudo apt install python3`
- macOS: `brew install python3`
- Windows: install from python.org or `winget install Python.Python.3` (tick
  "Add python.exe to PATH").

Don't edit `settings.json` yourself. The installer handles it safely, including
backing up any existing status line.

Note: claude-buddy is Linux/macOS only, so on Windows the bar renders as a clean
single line (workspace · branch · model · context · rate limits) with no buddy
art — this is expected, not an error.
