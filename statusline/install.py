#!/usr/bin/env python3
# claude-statusline installer (cross-platform: Linux / WSL / macOS / Windows).
#
# Wires the status line into Claude Code by:
#   1. copying the renderer + schema + the platform launcher to a stable home, and
#   2. pointing settings.json's "statusLine" at the launcher.
#
# Safe & idempotent: any pre-existing statusLine is backed up before the first
# overwrite, and re-running just refreshes the install. Undo with uninstall.py.
#
# Respects CLAUDE_CONFIG_DIR so it targets the active Claude profile. python3 is
# the only dependency (it renders the bar too); git is optional.
#
# https://github.com/archius11/claude-statusline                     MIT License

import os
import shutil
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _settings_patch as patch  # noqa: E402


# Pretty output (ANSI only on a real terminal, so captured output stays clean).
if sys.stdout.isatty():
    GREEN, CYAN, YELLOW, RED = "\033[32m", "\033[36m", "\033[33m", "\033[31m"
    BOLD, DIM, NC = "\033[1m", "\033[2m", "\033[0m"
else:
    GREEN = CYAN = YELLOW = RED = BOLD = DIM = NC = ""


def ok(msg):
    print(f"{GREEN}✓{NC}  {msg}")


def info(msg):
    print(f"{CYAN}→{NC}  {msg}")


def warn(msg):
    print(f"{YELLOW}⚠{NC}  {msg}")


def err(msg):
    print(f"{RED}✗{NC}  {msg}", file=sys.stderr)


def make_executable(path):
    # Unix needs the launcher/renderer marked executable; a no-op on Windows.
    if os.name == "nt":
        return
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def main():
    here = os.path.dirname(os.path.abspath(__file__))  # the statusline/ dir
    is_windows = os.name == "nt"

    print(f"\n{BOLD}  claude-statusline{NC} installer\n")

    cfg_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    settings = os.path.join(cfg_dir, "settings.json")
    backup = os.path.join(cfg_dir, "claude-statusline.statusline.bak")
    config_dest = os.path.join(cfg_dir, "claude-statusline.config.json")

    render_src = os.path.join(here, "claude-statusline-render.py")
    schema_src = os.path.join(here, "claude-statusline.schema.json")
    render_dest = os.path.join(cfg_dir, "claude-statusline-render.py")
    schema_dest = os.path.join(cfg_dir, "claude-statusline.schema.json")

    if os.environ.get("CLAUDE_CONFIG_DIR"):
        info(f"Target profile: {cfg_dir} {DIM}(from CLAUDE_CONFIG_DIR){NC}")
    else:
        info(f"Target profile: {cfg_dir} {DIM}(default){NC}")

    if not os.path.isfile(render_src):
        err("Cannot find claude-statusline-render.py next to this installer.")
        err("Run install.py from inside a cloned claude-statusline repository.")
        sys.exit(1)

    if not os.path.isdir(cfg_dir):
        warn(f"{cfg_dir} does not exist yet, creating it.")
        warn("If Claude Code has never run, start it once so it can manage settings.json.")
        os.makedirs(cfg_dir, exist_ok=True)

    # Copy the renderer (the shared core) and the schema (defaults / types).
    shutil.copyfile(render_src, render_dest)
    make_executable(render_dest)
    ok(f"Installed renderer → {render_dest}")

    if os.path.isfile(schema_src):
        shutil.copyfile(schema_src, schema_dest)
        ok(f"Installed settings schema → {schema_dest}")
    else:
        warn(f"Schema not found next to installer ({schema_src}); the status line will")
        warn("use its built-in default values until the schema is present.")

    # Copy the platform launcher and build the settings.json command for it.
    if is_windows:
        launcher_src = os.path.join(here, "statusline.ps1")
        launcher_dest = os.path.join(cfg_dir, "claude-statusline.ps1")
        shutil.copyfile(launcher_src, launcher_dest)
        command = (
            "powershell.exe -NoProfile -ExecutionPolicy Bypass "
            f"-File '{launcher_dest}'"
        )
    else:
        launcher_src = os.path.join(here, "statusline.sh")
        launcher_dest = os.path.join(cfg_dir, "claude-statusline.sh")
        shutil.copyfile(launcher_src, launcher_dest)
        make_executable(launcher_dest)
        command = launcher_dest
    ok(f"Installed launcher → {launcher_dest}")

    # Create a default (empty) settings file on first install; never overwrite.
    # Empty means "all defaults active"; the file only ever holds user overrides.
    if os.path.exists(config_dest):
        ok(f"Settings file already exists → {config_dest} {DIM}(left untouched){NC}")
    else:
        try:
            with open(config_dest, "w") as f:
                f.write("{}\n")
            ok(f"Settings file created → {config_dest} {DIM}(all defaults active){NC}")
        except OSError:
            warn("Could not create settings file now; it will appear on first run.")

    # Patch settings.json (backing up any pre-existing third-party statusLine).
    try:
        backed_up = patch.install(settings, command, backup)
    except ValueError as e:
        err(str(e))
        sys.exit(2)
    if backed_up:
        ok(f"Previous statusLine backed up → {backed_up}")
    ok(f"settings.json updated → {settings}")

    line = GREEN + "━" * 52 + NC
    print(f"\n{line}")
    print(f"{GREEN}  Done! Restart Claude Code to see the new status line.{NC}")
    print(f"{line}\n")
    print(f"{DIM}  Configure it with the {NC}/statusline{DIM} command")
    print(f"{DIM}  (guided menu or direct args, e.g. {NC}/statusline branch disable{DIM}),{NC}")
    print(f"{DIM}  or edit the settings file directly:{NC}")
    print(f"{DIM}    {config_dest}{NC}")
    if is_windows:
        print(f"{DIM}  Note: claude-buddy is Linux/macOS only, so on Windows the bar")
        print(f"{DIM}  renders as a clean single line.{NC}")
    else:
        print(f"{DIM}  claude-buddy is optional; if installed, its companion")
        print(f"{DIM}  appears on the right and the info weaves into the art.{NC}")
    print(f"{DIM}  Uninstall any time with uninstall.py (or uninstall.sh/.ps1).{NC}\n")


if __name__ == "__main__":
    main()
