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
    # Returns the parsed settings dict. Missing file -> {}. Invalid JSON (or
    # valid JSON that isn't an object) raises ValueError so the caller aborts
    # loudly instead of clobbering the file or crashing on .get/[]. Always UTF-8:
    # Claude Code writes settings.json as UTF-8 (hook/command paths may hold a
    # non-ASCII username), and the platform ANSI code page would mojibake them.
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"settings.json is not valid JSON ({e}). Aborting.")
    if not isinstance(data, dict):
        raise ValueError("settings.json is not a JSON object. Aborting.")
    return data


def _atomic_write_json(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _write_backup(old, backup_path):
    # Atomic + fsync, like the settings write: a crash mid-backup must never
    # leave a truncated backup that then blocks (or silently corrupts) restore.
    tmp = backup_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(old, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, backup_path)


def _backup_slots(backup_path):
    # Every existing backup, oldest first: the primary .bak (written by the first
    # install) then any numbered secondaries .bak.1, .bak.2, ... (each a real
    # third-party statusLine displaced by a later re-install). The last entry is
    # thus the most recently displaced statusLine — the one uninstall restores.
    slots = []
    if os.path.exists(backup_path):
        slots.append(backup_path)
    n = 1
    while os.path.exists(f"{backup_path}.{n}"):
        slots.append(f"{backup_path}.{n}")
        n += 1
    return slots


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
                with open(backup_path, encoding="utf-8") as f:
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

    slots = _backup_slots(backup_path)
    if slots:
        # Restore the MOST RECENTLY displaced statusLine (highest-numbered slot),
        # not the oldest primary .bak — otherwise an install → switch tools →
        # re-install → uninstall sequence would restore an ancient config and
        # orphan the user's real one in a .bak.N nobody ever reads.
        latest = slots[-1]
        with open(latest, encoding="utf-8") as f:
            restored = json.load(f)
        settings["statusLine"] = restored
        cmd = restored.get("command", "") if isinstance(restored, dict) else ""
        cmd = cmd.strip() if isinstance(cmd, str) else ""
        # Only warn "no longer resolves" when the command is a single bare token
        # that doesn't exist as a path. A multi-word command (a Windows
        # 'powershell ... -File ...', an 'npx ccusage statusline') can't be path-
        # checked, so we assume it restored fine instead of warning spuriously.
        single_token = bool(cmd) and " " not in cmd
        marker = "restored-missing" if (single_token and not os.path.exists(cmd)) else "restored"
        # Write settings FIRST, then drop the backups. If the write fails the
        # user's original statusLine is still on disk and recoverable — deleting
        # the only copy beforehand could lose it permanently on a failed write.
        _atomic_write_json(settings_path, settings)
        for slot in slots:
            try:
                os.remove(slot)
            except OSError:
                pass
        return marker

    settings.pop("statusLine", None)
    _atomic_write_json(settings_path, settings)
    return "removed"
