#!/usr/bin/env python3
# claude-statusline: settings engine for the /statusline command.
#
# This is the ONLY component that writes the config file. It reads the schema
# (claude-statusline.schema.json, the single source of truth for types,
# defaults, allowed values, aliases and cross-field constraints), validates any
# requested change against it, and writes the result atomically with a backup.
#
# The /statusline slash command never edits the JSON itself: it parses the user's
# intent and shells out to this tool, so all correctness lives here in code
# rather than in the model.
#
# Subcommands:
#   dump              Print schema + current values as JSON (drives the menu).
#   get [path]        Print the effective value of one setting, or all of them.
#   set <key> <val>   Validate and apply one change (key may be a path or alias).
#   validate          Check the on-disk config file against the schema.
#   reset [path]      Reset one setting (or everything) to its default.
#
# Pure python3, no third-party dependencies, matching the renderer's footprint.
#
# https://github.com/archius11/claude-statusline                     MIT License

import json
import math
import os
import sys


# Path resolution
# Both files follow the active Claude profile (CLAUDE_CONFIG_DIR) and can be
# pinned explicitly for tests / unusual installs. The schema also falls back to
# the copy bundled next to this script, so the tool works straight from the repo
# before anything is installed.

def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")


def resolve_config_path():
    explicit = os.environ.get("STATUSLINE_CONFIG")
    if explicit:
        return explicit
    return os.path.join(config_dir(), "claude-statusline.config.json")


def resolve_schema_path():
    explicit = os.environ.get("STATUSLINE_SCHEMA")
    if explicit and os.path.exists(explicit):
        return explicit
    installed = os.path.join(config_dir(), "claude-statusline.schema.json")
    if os.path.exists(installed):
        return installed
    # Bundled copy sitting next to this script (repo / plugin layout).
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "claude-statusline.schema.json")
    return bundled


# Schema helpers

def load_schema():
    path = resolve_schema_path()
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"Schema file not found: {path}")
    except json.JSONDecodeError as e:
        fail(f"Schema file is not valid JSON ({path}): {e}")


def leaf_nodes(schema):
    # Flatten the schema into an ordered list of (path, group_key, node) tuples.
    # 'path' is the dotted location ('branch.enable') used inside the config.
    nodes = []
    for group_key, group in schema.get("groups", {}).items():
        for child_key, node in group.get("children", {}).items():
            nodes.append((f"{group_key}.{child_key}", group_key, node))
    return nodes


def alias_map(schema):
    # Map every alias AND every full path to its canonical dotted path, so the
    # user can type 'branch', 'show-branch' or 'branch.enable' interchangeably.
    mapping = {}
    for path, _group, node in leaf_nodes(schema):
        mapping[path] = path
        for alias in node.get("aliases", []):
            mapping[alias.lower()] = path
    return mapping


def schema_defaults(schema):
    # Nested dict of every default value, keyed by group/child.
    defaults = {}
    for group_key, group in schema.get("groups", {}).items():
        section = {}
        for child_key, node in group.get("children", {}).items():
            section[child_key] = node.get("default")
        defaults[group_key] = section
    return defaults


def node_for_path(schema, path):
    for p, _group, node in leaf_nodes(schema):
        if p == path:
            return node
    return None


# Config loading / merging

def read_config_file(path):
    # Returns (data, status). status is 'ok', 'missing' or 'malformed'.
    if not path or not os.path.exists(path):
        return {}, "missing"
    try:
        with open(path) as f:
            return json.load(f), "ok"
    except Exception:
        return {}, "malformed"


def effective_config(schema, user_data):
    # Defaults with the user's stored values shallow-merged over each section,
    # the same forgiving merge the renderer uses.
    cfg = schema_defaults(schema)
    for section, values in cfg.items():
        stored = user_data.get(section)
        if isinstance(stored, dict):
            for key in values:
                if key in stored:
                    values[key] = stored[key]
    return cfg


def get_at(nested, path):
    section, key = path.split(".", 1)
    return nested.get(section, {}).get(key)


def set_at(nested, path, value):
    section, key = path.split(".", 1)
    nested.setdefault(section, {})[key] = value


def overrides_only(schema, nested):
    # Emit ONLY the values that differ from the schema default, in schema order,
    # dropping any section that ends up empty. Keeping the on-disk file sparse is
    # what lets a future change to a schema default still reach users who never
    # set that key (the renderer merges this file over the live defaults). An
    # all-default config therefore serialises to '{}'.
    defaults = schema_defaults(schema)
    out = {}
    for group_key, group in schema.get("groups", {}).items():
        section = {}
        for child_key in group.get("children", {}):
            value = nested.get(group_key, {}).get(child_key)
            if value != defaults.get(group_key, {}).get(child_key):
                section[child_key] = value
        if section:
            out[group_key] = section
    return out


# Value parsing & validation

BOOL_TRUE = {"enable", "on", "true", "yes", "1"}
BOOL_FALSE = {"disable", "off", "false", "no", "0"}


def parse_value(node, raw, current):
    # Turn the user's raw string into a typed value for this node, raising
    # ValueError with a friendly message when it doesn't fit the schema.
    ntype = node.get("type")
    token = str(raw).strip()

    if ntype == "bool":
        low = token.lower()
        if low == "toggle":
            return not bool(current)
        if low in BOOL_TRUE:
            return True
        if low in BOOL_FALSE:
            return False
        raise ValueError(
            f"expected enable/disable (got '{raw}')")

    if ntype == "enum":
        values = node.get("values", [])
        if token in values:
            return token
        raise ValueError(
            f"expected one of {', '.join(values)} (got '{raw}')")

    if ntype == "int":
        number = parse_int(token)
        if number is None:
            raise ValueError(f"expected a whole number (got '{raw}')")
        low, high = node.get("min"), node.get("max")
        if low is not None and number < low:
            raise ValueError(f"must be >= {low} (got {number})")
        if high is not None and number > high:
            raise ValueError(f"must be <= {high} (got {number})")
        return number

    raise ValueError(f"unsupported setting type '{ntype}'")


def parse_int(token):
    # Accept plain integers and human shorthand like '200k' / '1m'.
    token = token.lower().replace("_", "").replace(",", "").strip()
    multiplier = 1
    if token.endswith("k"):
        multiplier, token = 1000, token[:-1]
    elif token.endswith("m"):
        multiplier, token = 1000000, token[:-1]
    try:
        value = float(token) * multiplier
        # 'inf' / '1e400' parse as a float infinity; int(round(inf)) raises
        # OverflowError. Reject non-finite values so the caller surfaces the
        # friendly 'expected a whole number' message instead of a traceback.
        if not math.isfinite(value):
            return None
        return int(round(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _is_number(value):
    # bool is a subclass of int, but a toggle is never a numeric threshold.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def constraint_errors(schema, cfg):
    # Evaluate the schema's cross-field constraints against an effective config.
    errors = []
    for rule in schema.get("constraints", []):
        kind = rule.get("rule")
        if kind not in ("gte", "lte"):
            # A misspelled / unsupported rule must fail loudly, not be silently
            # treated as satisfied (which would let a real invariant slip).
            errors.append(f"unsupported constraint rule '{kind}'")
            continue
        left = get_at(cfg, rule["left"])
        right = get_at(cfg, rule["right"])
        # Skip the comparison when either side is absent or not a real number
        # (e.g. a threshold hand-edited to a string). The per-field type check in
        # cmd_validate reports that separately; here we must not crash on int>=str.
        if left is None or right is None or not _is_number(left) or not _is_number(right):
            continue
        ok = left >= right if kind == "gte" else left <= right
        if not ok:
            errors.append(rule.get("message", f"constraint failed: {rule}"))
    return errors


# Atomic write

def write_config(path, schema, nested):
    # Back up the previous file, then replace atomically (temp file + rename in
    # the same directory) so a crash mid-write can never leave a half file.
    parent = os.path.dirname(path)
    if parent:  # bare relative filename (e.g. STATUSLINE_CONFIG=cfg.json) lands in cwd
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path) as src:
                previous = src.read()
            with open(path + ".bak", "w") as dst:
                dst.write(previous)
        except Exception:
            pass  # A failed backup must not block the actual write.

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(overrides_only(schema, nested), f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# Output helpers

def fail(message, code=1):
    sys.stderr.write(f"error: {message}\n")
    sys.exit(code)


def display_value(node, value):
    # Human-facing rendering of a stored value (booleans read as enable/disable).
    if node.get("type") == "bool":
        return "enable" if value else "disable"
    return str(value)


# Subcommands

def cmd_dump(schema):
    # Emit schema + current values as a single JSON document. This is what the
    # /statusline command injects so the model has the full menu model and state.
    config_path = resolve_config_path()
    user_data, status = read_config_file(config_path)
    cfg = effective_config(schema, user_data)

    groups = []
    for group_key, group in schema.get("groups", {}).items():
        options = []
        for child_key, node in group.get("children", {}).items():
            path = f"{group_key}.{child_key}"
            current = get_at(cfg, path)
            option = {
                "path": path,
                "key": child_key,
                "label": node.get("label", child_key),
                "help": node.get("help", ""),
                "type": node.get("type"),
                "aliases": node.get("aliases", []),
                "default": node.get("default"),
                "current": current,
                "current_display": display_value(node, current),
            }
            if node.get("type") == "bool":
                option["values"] = node.get("values", ["enable", "disable"])
            elif node.get("type") == "enum":
                option["values"] = node.get("values", [])
            elif node.get("type") == "int":
                option["min"] = node.get("min")
                option["max"] = node.get("max")
            options.append(option)
        groups.append({
            "key": group_key,
            "label": group.get("label", group_key),
            "help": group.get("help", ""),
            "options": options,
        })

    out = {
        "config_file": config_path,
        "schema_file": resolve_schema_path(),
        "config_status": status,
        "groups": groups,
        "constraints": [
            {"message": r.get("message", "")} for r in schema.get("constraints", [])
        ],
    }
    print(json.dumps(out, indent=2))


def cmd_get(schema, args):
    config_path = resolve_config_path()
    user_data, _status = read_config_file(config_path)
    cfg = effective_config(schema, user_data)

    if args:
        path = resolve_key(schema, args[0])
        node = node_for_path(schema, path)
        print(display_value(node, get_at(cfg, path)))
        return

    for path, _group, node in leaf_nodes(schema):
        print(f"{path} = {display_value(node, get_at(cfg, path))}")


def cmd_set(schema, args):
    if len(args) < 2:
        fail("usage: set <key> <value>")
    key, raw = args[0], " ".join(args[1:])
    path = resolve_key(schema, key)
    node = node_for_path(schema, path)

    config_path = resolve_config_path()
    user_data, status = read_config_file(config_path)
    if status == "malformed":
        # Don't silently discard a hand-edited file: preserve it, then rebuild.
        try:
            os.replace(config_path, config_path + ".corrupt.bak")
            sys.stderr.write(
                f"warning: existing config was not valid JSON; backed up to "
                f"{config_path}.corrupt.bak and rebuilt from defaults.\n")
        except Exception:
            pass
        user_data = {}

    cfg = effective_config(schema, user_data)
    current = get_at(cfg, path)

    try:
        value = parse_value(node, raw, current)
    except ValueError as e:
        fail(f"{path}: {e}")

    set_at(cfg, path, value)

    problems = constraint_errors(schema, cfg)
    if problems:
        fail("change rejected: " + "; ".join(problems))

    write_config(config_path, schema, cfg)
    print(f"OK  {path} = {display_value(node, value)}")
    print(f"    saved to {config_path}")
    print("    (the status line picks this up on its next refresh, no restart needed)")


def cmd_validate(schema):
    config_path = resolve_config_path()
    user_data, status = read_config_file(config_path)

    if status == "missing":
        print(f"No config file yet at {config_path}; defaults are in effect.")
        return
    if status == "malformed":
        fail(f"Config file is not valid JSON: {config_path}")

    issues = []
    valid_paths = {p for p, _g, _n in leaf_nodes(schema)}

    # Unknown keys (typos, settings removed from the schema).
    for section, values in user_data.items():
        if not isinstance(values, dict):
            issues.append(f"section '{section}' should be an object")
            continue
        for key in values:
            path = f"{section}.{key}"
            if path not in valid_paths:
                issues.append(f"unknown setting '{path}'")

    # Type / range checks on known keys.
    for path, _group, node in leaf_nodes(schema):
        section, key = path.split(".", 1)
        stored = user_data.get(section, {})
        if not isinstance(stored, dict) or key not in stored:
            continue
        raw = stored[key]
        try:
            parse_value(node, raw if node.get("type") != "bool" else
                        ("enable" if raw else "disable"), None)
            if node.get("type") == "bool" and not isinstance(raw, bool):
                issues.append(f"'{path}' should be true/false (got {raw!r})")
            if node.get("type") == "int" and not isinstance(raw, int):
                issues.append(f"'{path}' should be a number (got {raw!r})")
        except ValueError as e:
            issues.append(f"'{path}': {e}")

    cfg = effective_config(schema, user_data)
    issues.extend(constraint_errors(schema, cfg))

    if issues:
        print(f"Found {len(issues)} issue(s) in {config_path}:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    print(f"OK: {config_path} is valid against the schema.")


def cmd_reset(schema, args):
    config_path = resolve_config_path()
    user_data, status = read_config_file(config_path)
    if status == "malformed":
        # Mirror cmd_set: don't silently discard a hand-edited file; preserve it
        # to .corrupt.bak and warn, then rebuild from defaults.
        try:
            os.replace(config_path, config_path + ".corrupt.bak")
            sys.stderr.write(
                f"warning: existing config was not valid JSON; backed up to "
                f"{config_path}.corrupt.bak and rebuilt from defaults.\n")
        except Exception:
            pass
        user_data = {}
    cfg = effective_config(schema, user_data)

    if args:
        path = resolve_key(schema, args[0])
        node = node_for_path(schema, path)
        set_at(cfg, path, node.get("default"))
        write_config(config_path, schema, cfg)
        print(f"OK  {path} reset to default = {display_value(node, node.get('default'))}")
    else:
        write_config(config_path, schema, schema_defaults(schema))
        print(f"OK  all settings reset to defaults in {config_path}")


def resolve_key(schema, key):
    mapping = alias_map(schema)
    path = mapping.get(key) or mapping.get(key.lower())
    if not path:
        known = sorted({a for _p, _g, n in leaf_nodes(schema)
                        for a in n.get("aliases", [])})
        fail(f"unknown setting '{key}'. Try one of: {', '.join(known)}")
    return path


# Entry point

def main(argv):
    if not argv:
        fail("usage: statusline-config.py <dump|get|set|validate|reset> [args]")

    command, rest = argv[0], argv[1:]
    schema = load_schema()

    if command == "dump":
        cmd_dump(schema)
    elif command == "get":
        cmd_get(schema, rest)
    elif command == "set":
        cmd_set(schema, rest)
    elif command == "validate":
        cmd_validate(schema)
    elif command == "reset":
        cmd_reset(schema, rest)
    else:
        fail(f"unknown command '{command}'")


if __name__ == "__main__":
    main(sys.argv[1:])
