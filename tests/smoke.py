#!/usr/bin/env python3
# claude-statusline: cross-platform smoke tests.
#
# Drives the renderer and the installer through subprocess (using the current
# Python interpreter), so the SAME tests run identically on Linux, macOS and
# Windows. The buddy-weave and config-engine tests stay in CI as a Unix-only
# bash step, since buddy is Linux/macOS only.
#
# Run:  python tests/smoke.py

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SL = os.path.join(REPO, "statusline")
RENDER = os.path.join(SL, "claude-statusline-render.py")
INSTALL = os.path.join(SL, "install.py")
UNINSTALL = os.path.join(SL, "uninstall.py")
SCHEMA = os.path.join(SL, "claude-statusline.schema.json")
PY = sys.executable

DEMO = ('{"workspace":{"current_dir":"/tmp/demo"},'
        '"model":{"display_name":"Claude Opus 4.8"},'
        '"context_window":{"used_percentage":12,"context_window_size":1000000}}')

_failures = []


def check(cond, msg):
    print(("PASS: " if cond else "FAIL: ") + msg)
    if not cond:
        _failures.append(msg)


def run(cmd, payload=None, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, input=payload, text=True,
                          capture_output=True, env=env)


def no_buddy(sandbox):
    # Point home / config dir at an empty sandbox and the buddy override at a
    # nonexistent path, so buddy discovery finds nothing -> clean single line.
    return {
        "CLAUDE_CONFIG_DIR": sandbox,
        "HOME": sandbox,
        "USERPROFILE": sandbox,
        "BUDDY_STATUS_SCRIPT": os.path.join(sandbox, "nope"),
        "STATUSLINE_CONFIG": os.path.join(sandbox, "cfg.json"),
        "STATUSLINE_SCHEMA": SCHEMA,
    }


def test_render_single_line():
    with tempfile.TemporaryDirectory() as sb:
        r = run([PY, RENDER], DEMO, no_buddy(sb))
        check(r.returncode == 0, "render exits 0")
        check("Opus 4.8" in r.stdout, "render shows the model name")
        check("\n" not in r.stdout.strip(), "no-buddy render is a single line")


def test_render_crash_proof():
    odd = [
        "{}",
        "not json at all",
        '{"context_window":{"used_percentage":"50","context_window_size":200000}}',
        '{"rate_limits":{"five_hour":{"used_percentage":30,"resets_at":"9999999999"}}}',
    ]
    with tempfile.TemporaryDirectory() as sb:
        for payload in odd:
            r = run([PY, RENDER], payload, no_buddy(sb))
            check(r.returncode == 0, f"crash-proof exit 0 for {payload[:32]!r}")


def _count_bars(s):
    # A rendered progress bar is a '[' immediately followed by a block glyph
    # (█ / ░). ANSI escapes are '[' + digits + 'm', never '[' + a block, so this
    # counts real bars without tripping over colour codes or '2.5h'-style text.
    return sum(1 for i in range(len(s) - 1) if s[i] == "[" and s[i + 1] in "█░")


def test_render_new_options():
    # Per-stat config groups reach the renderer, and the new display / progress-bar
    # options change the output as expected.
    payload = ('{"context_window":{"used_percentage":40,"context_window_size":1000000},'
               '"rate_limits":{"five_hour":{"used_percentage":30,"resets_at":9999999999}}}')
    with tempfile.TemporaryDirectory() as sb:
        env = no_buddy(sb)
        cfgp = env["STATUSLINE_CONFIG"]

        # context.display = tokens -> show the token count instead of a percentage.
        with open(cfgp, "w") as f:
            json.dump({"context": {"display": "tokens"}}, f)
        r = run([PY, RENDER], payload, env)
        check(r.returncode == 0, "new-options render exits 0")
        check("400K" in r.stdout, "context display=tokens shows the token count")
        check("40%" not in r.stdout, "context tokens mode drops the percentage")

        # Default: one bar (context on, 5h off).
        with open(cfgp, "w") as f:
            json.dump({}, f)
        base = run([PY, RENDER], payload, env)
        check(_count_bars(base.stdout) == 1, "one progress bar by default (context)")

        # context bar off -> no bars left.
        with open(cfgp, "w") as f:
            json.dump({"context": {"progress_bar": False}}, f)
        off = run([PY, RENDER], payload, env)
        check(_count_bars(off.stdout) == 0, "context progress_bar=false removes the bar")


def test_install_uninstall_roundtrip():
    with tempfile.TemporaryDirectory() as sb:
        settings = os.path.join(sb, "settings.json")
        before = {"permissions": {"allow": ["x"]},
                  "statusLine": {"type": "command", "command": "/old/thing.sh"}}
        with open(settings, "w") as f:
            json.dump(before, f)

        env = {"CLAUDE_CONFIG_DIR": sb}
        ri = run([PY, INSTALL], env_extra=env)
        check(ri.returncode == 0, "install exits 0")

        sd = json.load(open(settings))
        check("claude-statusline" in sd.get("statusLine", {}).get("command", ""),
              "settings.json points at our launcher")

        launcher = "claude-statusline.ps1" if os.name == "nt" else "claude-statusline.sh"
        for name in ("claude-statusline-render.py", "claude-statusline.schema.json",
                     "claude-statusline.config.json", launcher):
            check(os.path.isfile(os.path.join(sb, name)), f"installed: {name}")
        check(os.path.isfile(os.path.join(sb, "claude-statusline.statusline.bak")),
              "pre-existing statusLine backed up")

        # Render through the INSTALLED renderer (verifies the copy + sibling schema).
        installed = os.path.join(sb, "claude-statusline-render.py")
        r = run([PY, installed], DEMO, {
            "CLAUDE_CONFIG_DIR": sb, "HOME": sb, "USERPROFILE": sb,
            "BUDDY_STATUS_SCRIPT": os.path.join(sb, "nope"),
        })
        check(r.returncode == 0 and "Opus 4.8" in r.stdout, "installed renderer works")

        ru = run([PY, UNINSTALL], env_extra=env)
        check(ru.returncode == 0, "uninstall exits 0")
        check(not os.path.isfile(os.path.join(sb, launcher)), f"{launcher} removed")
        check(not os.path.isfile(os.path.join(sb, "claude-statusline-render.py")),
              "renderer removed")
        check(os.path.isfile(os.path.join(sb, "claude-statusline.config.json")),
              "user config kept on uninstall")
        check(json.load(open(settings)) == before,
              "settings.json restored to its original contents")


def test_interop_buddy_statusline():
    with tempfile.TemporaryDirectory() as sb:
        settings = os.path.join(sb, "settings.json")
        before = {"statusLine": {"type": "command",
                                 "command": "/home/x/claude-buddy/statusline/buddy-status.sh",
                                 "padding": 1, "refreshInterval": 1}}
        with open(settings, "w") as f:
            json.dump(before, f)

        env = {"CLAUDE_CONFIG_DIR": sb}
        run([PY, INSTALL], env_extra=env)
        bak = json.load(open(os.path.join(sb, "claude-statusline.statusline.bak")))
        check(bak.get("command", "").endswith("buddy-status.sh"),
              "buddy statusLine preserved in backup")
        run([PY, UNINSTALL], env_extra=env)
        check(json.load(open(settings)) == before,
              "buddy statusLine restored verbatim")


def test_buddy_discovery_via_registration():
    # A buddy cloned to a non-standard directory (one our fixed paths don't guess)
    # is still found through its MCP registration in .claude.json, where buddy
    # records cwd = the clone root. Unix-only: the status script is a runnable .sh
    # and buddy is Linux/macOS only (on Windows discovery is skipped by design).
    if os.name == "nt":
        return
    with tempfile.TemporaryDirectory() as sb:
        # Clone buddy somewhere we would never guess.
        clone = os.path.join(sb, "somewhere", "odd", "claude-buddy")
        statusline_dir = os.path.join(clone, "statusline")
        os.makedirs(statusline_dir)
        script = os.path.join(statusline_dir, "buddy-status.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env bash\n"
                    "cat <<'EOF'\n"
                    "⠀                .----.\n"
                    "⠀               ( o.o  )\n"
                    "⠀                 ^  ^\n"
                    "⠀                 ----\n"
                    "EOF\n")
        os.chmod(script, 0o755)

        # buddy's MCP registration points cwd at the clone root.
        with open(os.path.join(sb, ".claude.json"), "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"claude-buddy": {"command": "bun",
                       "args": [os.path.join(clone, "server", "index.ts")],
                       "cwd": clone}}}, f)

        env = {
            "CLAUDE_CONFIG_DIR": sb, "HOME": sb, "USERPROFILE": sb,
            "BUDDY_STATUS_SCRIPT": "",  # unset the override so discovery does the work
            "STATUSLINE_CONFIG": os.path.join(sb, "cfg.json"),
            "STATUSLINE_SCHEMA": SCHEMA,
        }
        r = run([PY, RENDER], DEMO, env)
        check(r.returncode == 0, "registration discovery: exits 0")
        check("o.o" in r.stdout, "registration discovery: buddy found in odd clone dir")
        check("\n" in r.stdout.strip(), "registration discovery: info woven into art")


def main():
    print(f"python: {PY}")
    print(f"platform: {sys.platform} (os.name={os.name})\n")
    test_render_single_line()
    test_render_crash_proof()
    test_render_new_options()
    test_install_uninstall_roundtrip()
    test_interop_buddy_statusline()
    test_buddy_discovery_via_registration()
    print()
    if _failures:
        print(f"{len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()
