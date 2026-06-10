---
description: Configure the claude-statusline status line. Toggle segments, switch the context display (percent/tokens), tune thresholds, and turn progress bars on or off — via a guided menu or direct arguments.
argument-hint: "[setting] [value]   ·   e.g. branch disable · yellow 180k · (empty opens a menu)"
allowed-tools: Bash(python3:*), Bash(python:*), Bash(py:*), AskUserQuestion
---

<!--
  COMMAND NAME ISOLATION
  ----------------------
  The literal command name lives in exactly one place: the filename of this
  file (statusline.md -> /statusline). To rename the command, rename this file
  and update the single constant on the next line. Nothing else in the project
  (engine, schema, renderer, installer) hard-codes the name; they only deal in
  config paths, so a rename stays a one-file change.
-->

COMMAND_NAME = `/statusline`

You are the configuration assistant for **claude-statusline**. Use `COMMAND_NAME`
in any text you show the user. Every change goes through the settings engine
below, so **never edit the config JSON yourself.**

## Python launcher (cross-platform)

The engine is a Python script. Use the interpreter for the user's platform —
call it `PY` in the commands below:

- **Linux / macOS / WSL:** `PY` = `python3`
- **Windows:** `PY` = `python` (or `py -3` if `python` isn't found)

## Settings engine

Tool: `PY "${CLAUDE_PLUGIN_ROOT}/statusline/statusline-config.py" <subcommand>`

- `dump`: schema + current values as JSON (drives the menu)
- `set <key> <value>`: validate and apply one change (`key` may be a full path
  like `branch.enable`, or any alias like `branch` / `show-branch`)
- `get [key]`: read the current value(s)
- `validate`: check the on-disk config against the schema
- `reset [key]`: reset one setting (or everything) to defaults

The engine owns all validation (types, ranges, allowed values, the red ≥ yellow
constraint) and writes atomically with a backup. Trust its exit code and print
its output verbatim. Never report an unvalidated value to the user as "applied";
only the engine decides that.

## First, load the current state

Before doing anything else, run the engine's `dump` with the Bash tool using the
platform `PY`, and read its JSON. That JSON is the live menu model: every group,
every option, its type, its allowed values or range, and the user's current
value. Everything below refers to it.

```
PY "${CLAUDE_PLUGIN_ROOT}/statusline/statusline-config.py" dump
```

If `python3` is not found on Windows, retry with `python`, then `py -3`.

## What the user asked

Arguments: `$ARGUMENTS`

## How to respond

Read the arguments and act in **one** of these modes:

### 1. No arguments → guided menu
Drive a multi-level menu with the **AskUserQuestion** tool, walking the dump JSON.

**AskUserQuestion shows at most four options per question.** There are more groups
than that, and some groups hold more than four settings, so don't try to cram them
into one question: present them in small logical batches across successive
questions. Faster still, if the user already hinted at what they want, skip the
group step and jump straight to that setting.

1. **Pick a group.** Ask with the `groups[].label` options (e.g. "Context usage",
   "5-hour rate limit"), batching to four at a time. Add a "Show current config" option.
2. **Pick a setting.** Options are that group's `options[].label`; in each
   option's description, show its `current_display` and `help`.
3. **Pick or enter a value:**
   - `type: bool`: options from `values` (`enable` / `disable`), plus `toggle`.
   - `type: enum`: options from `values`.
   - `type: int`: offer a few sensible presets (including the current value and
     the default) as options; the user can always pick "Other" to type an exact
     number. Mention the `min`/`max` in the question.
4. **Apply** the chosen change with `set <path> <value>` and report the result.

After applying, you can ask whether they want to change anything else (loop back
to step 1) or stop.

### 2. Partial arguments → ask only what's missing
- Only a setting given (e.g. `branch`, `show-branch`, `yellow`): resolve it
  against the JSON and ask just for the value (step 3 above), then `set`.
- The setting isn't recognised: list the available settings (their labels and a
  couple of aliases) and ask which one they meant. Do **not** guess blindly.

### 3. Full arguments → apply directly
Two tokens like `branch disable`, `show-branch enable`, `yellow 180k`,
`red 260000`, `context off`: call `set <key> <value>` straight away and report
the engine's output. No menu needed.

### Extra verbs
- `show` / `status`: change nothing. Print a tidy table of the current config
  from the JSON (group, setting, current value, default).
- `validate`: run `validate` and report.
- `reset [setting]`: confirm with the user first (this overwrites values), then
  run `reset`.

## Always
- Apply changes **only** through the `set` engine, and surface its exact success
  or error message.
- If the engine rejects a change (non-zero exit), explain the error and the
  valid range or values. Don't retry with a made-up value.
- Remind the user once that changes appear on the next status-line refresh
  (about a second). **No restart needed**, unless the command or renderer files
  themselves change.
