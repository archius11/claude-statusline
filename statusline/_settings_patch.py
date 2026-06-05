#!/usr/bin/env python3
# claude-statusline: the one place that mutates Claude Code's settings.json.
#
# Both install.py and uninstall.py import these helpers, so the (delicate) logic
# of backing up a pre-existing statusLine, taking ours over, and restoring it
# lives once instead of being duplicated as embedded Python in two shell scripts.
#
# Every write is atomic (temp file + os.replace) so an interrupted run can never
# leave settings.json truncated.
#
# https://github.com/archius11/claude-statusline                     MIT License

import json
import os

# Substring that identifies OUR statusLine command. It must match both the Unix
# launcher path (.../claude-statusline.sh) and the Windows command
# (powershell ... -File '...claude-statusline.ps1'), so we key on the shared
# stem rather than a single filename.
MARKER = "claude-statusline"


def is_ours(status_line):
    return isinstance(status_line, dict) and MARKER in status_line.get("command", "")


def _read_settings(path):
    # Returns the parsed settings dict. Missing file -> {}. Invalid JSON raises
    # ValueError so the caller can abort loudly instead of clobbering the file.
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"settings.json is not valid JSON ({e}). Aborting.")


def _atomic_write_json(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _write_backup(old, backup_path):
    with open(backup_path, "w") as f:
        json.dump(old, f, indent=2)
        f.write("\n")


def install(settings_path, command, backup_path):
    # Point settings.json's statusLine at `command`. Backs up a pre-existing
    # third-party statusLine first (a different one on a later run lands in a
    # numbered secondary backup rather than being dropped). Returns the path we
    # backed up to this run, or None.
    settings = _read_settings(settings_path)
    old = settings.get("statusLine")
    backed_up = None

    if old is not None and not is_ours(old):
        if not os.path.exists(backup_path):
            _write_backup(old, backup_path)
            backed_up = backup_path
        else:
            try:
                with open(backup_path) as f:
                    stored = json.load(f)
            except Exception:
                stored = None
            if stored != old:
                n = 1
                while os.path.exists(f"{backup_path}.{n}"):
                    n += 1
                secondary = f"{backup_path}.{n}"
                _write_backup(old, secondary)
                backed_up = secondary

    settings["statusLine"] = {
        "type": "command",
        "command": command,
        "padding": 1,
        "refreshInterval": 1,
    }
    _atomic_write_json(settings_path, settings)
    return backed_up


def uninstall(settings_path, backup_path):
    # Restore the statusLine that was present before install (if we backed one
    # up), or remove ours entirely. Leaves settings.json alone unless the current
    # statusLine is ours. Returns a marker describing what happened:
    #   no-settings | not-ours | restored | restored-missing | removed
    if not os.path.exists(settings_path):
        return "no-settings"

    settings = _read_settings(settings_path)
    sl = settings.get("statusLine")
    if not is_ours(sl):
        # Someone else (e.g. claude-buddy) owns the status line now: leave it.
        return "not-ours"

    if os.path.exists(backup_path):
        with open(backup_path) as f:
            restored = json.load(f)
        os.remove(backup_path)
        settings["statusLine"] = restored
        cmd = restored.get("command", "") if isinstance(restored, dict) else ""
        # Flag when the restored command points at a script that no longer exists
        # so the user isn't silently left on a dead command. Best-effort: a
        # multi-word command (e.g. a Windows powershell invocation) won't resolve
        # as a bare path, so this only ever downgrades to a harmless warning.
        marker = "restored" if (cmd and os.path.exists(cmd)) else "restored-missing"
    else:
        settings.pop("statusLine", None)
        marker = "removed"

    _atomic_write_json(settings_path, settings)
    return marker
