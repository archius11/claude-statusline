#!/usr/bin/env python3
# claude-statusline uninstaller (cross-platform: Linux / WSL / macOS / Windows).
#
# Restores the statusLine that was present before install (if we backed one up),
# or removes ours entirely, and deletes the copied files. Only touches
# settings.json if the current statusLine is ours, so your own config is safe.
#
# Respects CLAUDE_CONFIG_DIR so it targets the active Claude profile.
#
# https://github.com/archius11/claude-statusline                     MIT License

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _settings_patch as patch  # noqa: E402


if sys.stdout.isatty():
    GREEN, CYAN, YELLOW, NC = "\033[32m", "\033[36m", "\033[33m", "\033[0m"
else:
    GREEN = CYAN = YELLOW = NC = ""


def ok(msg):
    print(f"{GREEN}✓{NC}  {msg}")


def info(msg):
    print(f"{CYAN}→{NC}  {msg}")


def warn(msg):
    print(f"{YELLOW}⚠{NC}  {msg}")


def main():
    cfg_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    settings = os.path.join(cfg_dir, "settings.json")
    backup = os.path.join(cfg_dir, "claude-statusline.statusline.bak")
    config_dest = os.path.join(cfg_dir, "claude-statusline.config.json")

    # Everything we may have copied in, on any platform.
    copied = [
        os.path.join(cfg_dir, "claude-statusline-render.py"),
        os.path.join(cfg_dir, "claude-statusline.schema.json"),
        os.path.join(cfg_dir, "claude-statusline.sh"),
        os.path.join(cfg_dir, "claude-statusline.ps1"),
    ]

    try:
        result = patch.uninstall(settings, backup)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)

    # Our own copied files are always removed: they are inert once we no longer
    # own the statusLine, so cleaning them up is correct regardless of who owns it.
    for path in copied:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    if result == "restored":
        ok("Restored your previous statusLine and removed our files")
    elif result == "restored-missing":
        ok("Removed our statusLine and our files")
        warn("The previously backed-up statusLine pointed at a command that no longer "
             "resolves, so it was not restored. Set one manually if you want it back.")
    elif result == "removed":
        ok("Removed our statusLine and our files")
    elif result == "not-ours":
        info("settings.json statusLine points at another tool (e.g. claude-buddy), left "
             "it untouched; removed our installed files")
    elif result == "no-settings":
        info("No settings.json found, removed our installed files if present")
    else:
        ok("Removed our installed files")

    if os.path.isfile(config_dest):
        info(f"Kept your settings file: {config_dest}")
        info(f"Delete it manually if you want a clean slate: rm \"{config_dest}\"")
    info("Restart Claude Code to apply.")


if __name__ == "__main__":
    main()
