#!/usr/bin/env python3
# claude-statusline: the renderer (one core for Linux / WSL / macOS / Windows).
#
# Reads Claude Code's JSON payload from stdin and prints the status line:
# workspace / git branch / model / context usage / rate-limit info. If
# claude-buddy (https://github.com/1270011/claude-buddy) is installed AND its
# buddy-status.sh is present (Linux/macOS only — buddy doesn't support Windows),
# the info is woven into the empty left margin of the buddy's ASCII art.
# Otherwise it renders as a clean single line.
#
# Pure python3, no third-party dependencies. git is optional (branch detection).
# Thin platform launchers (statusline.sh / statusline.ps1) just locate python and
# exec this file, so the logic lives here once instead of in two languages.
#
# https://github.com/archius11/claude-statusline                     MIT License

import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# Emit UTF-8 regardless of the platform's default code page, so the box-drawing
# (█░⎇), Braille (⠀) and emoji (🔴🟢) glyphs survive on Windows consoles too.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# On Windows, keep git / buddy subprocesses from flashing a console window on
# every one-second refresh. A no-op (0) everywhere else.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

BRAILLE = "⠀"  # U+2800 Braille blank, buddy pads art lines with this.
DOLLAR = "$"   # literal now that this is a real file, not a bash-quoted string.
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"
GRN = "\033[32m"
YLW = "\033[33m"
RED = "\033[31m"


def num(v):
    # Coerce a JSON value to a float, or None when it isn't numeric. Claude Code
    # sends percentages / timestamps / sizes as numbers, but if a future payload
    # variant sends one as a string we must degrade, never crash mid-render.
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cpct(p):
    # Traffic-light colour for a 0-100 percentage.
    if p >= 80:
        return RED
    if p >= 50:
        return YLW
    return GRN


def bar(p, w=10):
    # A w-wide filled/empty block bar for percentage p.
    p = max(0, min(100, int(p)))
    f = p * w // 100
    return "█" * f + "░" * (w - f)


def fmtsz(n):
    # Human-readable token count: 1000000 -> '1M', 200000 -> '200K'.
    if not n:
        return ""
    n = int(n)
    if n >= 1_000_000:
        w, f = n // 1_000_000, (n % 1_000_000) // 100_000
        return f"{w}.{f}M" if f else f"{w}M"
    return f"{n // 1000}K"


def fmtrst(ts, win):
    # Time left until a rate-limit window resets, as '1.5h' or '2.3d'.
    ts = num(ts)
    if not ts:
        return ""
    left = max(0, int(ts - datetime.datetime.now(datetime.timezone.utc).timestamp()))
    h = left / 3600
    if win == 604800 and h >= 24:
        d = h / 24
        return f"{d:.1f}d"
    return f"{h:.1f}h"


def burn(used, ts, win):
    # Burn-rate flag for a rate-limit window: are you on track to hit 100%
    # BEFORE it resets? Everything comes straight from stdin (used_percentage +
    # resets_at) plus the fixed window length 'win' (5h = 18000s, 7d = 604800s).
    #
    #   time_left = resets_at - now        # seconds until the window resets
    #   elapsed   = win - time_left        # seconds already spent in the window
    #
    # Compare your real spend rate (used / elapsed) with the even rate that lands
    # exactly on 100% at reset (100 / win). Burning faster means you run out
    # early -> 🔴; on pace or with room to spare -> 🟢. This is the same test as
    # the 'eta < time_left' ETA framing, just rearranged to avoid any division
    # (so used = 0 falls out as a plain 🟢 with no divide-by-zero).
    used = num(used)
    ts = num(ts)
    if used is None or ts is None:
        return ""
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    time_left = ts - now
    if time_left <= 0:
        return ""  # window already at / past its reset: nothing to flag
    elapsed = win - time_left
    if elapsed <= 0:
        return ""  # window just opened (or clock skew): too early to judge a rate
    return "🔴" if used * win > 100 * elapsed else "🟢"


def git_info(cwd):
    # Current branch and whether the working tree has uncommitted changes.
    # The result is cached briefly in a temp file keyed by the directory, so a
    # 1-second status refresh doesn't fork git on every tick; the cache expires
    # after GIT_CACHE_TTL seconds. Every failure degrades to a live read or to
    # empty values, never a crash. (Unlike a single shared cache file, the
    # per-directory key keeps separate repos / worktrees from clobbering each
    # other, and mtime comes from os.path.getmtime so it is correct everywhere.)
    GIT_CACHE_TTL = 3
    key = hashlib.sha256(cwd.encode("utf-8", "replace")).hexdigest()[:16]
    cache_path = os.path.join(tempfile.gettempdir(), f"claude-statusline-git.{key}.json")

    # Fresh cache wins outright.
    try:
        if time.time() - os.path.getmtime(cache_path) < GIT_CACHE_TTL:
            with open(cache_path) as f:
                c = json.load(f)
            return c.get("branch", ""), bool(c.get("dirty", False))
    except Exception:
        pass  # missing / stale / unreadable -> fall through to a live read

    branch, dirty = "", False
    try:
        branch = subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, creationflags=_NO_WINDOW).strip()
        if branch == "HEAD":
            # Detached HEAD (rebase / bisect / a checked-out tag or commit):
            # show the short commit instead of the literal word 'HEAD'.
            short = subprocess.check_output(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL, text=True, creationflags=_NO_WINDOW).strip()
            if short:
                branch = "@" + short
    except Exception:
        branch = ""  # not a repo (or git missing); cached below so we don't retry

    if branch:
        # --quiet exits non-zero when there ARE changes; check unstaged + staged.
        # (Untracked files are not counted as dirty, mirroring 'git diff'.)
        try:
            unstaged = subprocess.call(
                ["git", "-C", cwd, "diff", "--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            staged = subprocess.call(
                ["git", "-C", cwd, "diff", "--cached", "--quiet"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            dirty = unstaged != 0 or staged != 0
        except Exception:
            dirty = False

    # Persist the result (atomically; a non-writable temp dir just means no cache).
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"branch": branch, "dirty": dirty}, f)
        os.replace(tmp, cache_path)
    except Exception:
        pass
    return branch, dirty


def _runnable_buddy_status(root):
    # buddy's status script always lives at <install root>/statusline/buddy-status.sh.
    # Return it if it's present and executable, else "".
    if not root:
        return ""
    candidate = os.path.join(root, "statusline", "buddy-status.sh")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return ""


def buddy_script_from_registration():
    # The robust signal. When buddy installs, it registers itself as an MCP server
    # in Claude Code's user config, and a manual install records cwd = the clone
    # root (a plugin install records the entrypoint in args). Reading that lets us
    # find buddy-status.sh no matter where the user cloned buddy, instead of
    # guessing a handful of clone locations. The registration survives buddy
    # updates and is left untouched when we take over the statusLine (we only edit
    # settings.json), so it stays a reliable anchor.
    #
    # buddy keeps this file at $CLAUDE_CONFIG_DIR/.claude.json when that variable is
    # set, otherwise at ~/.claude.json. We mirror that exactly so we read the same
    # file buddy wrote (see claude-buddy's server/path.ts claudeUserConfigPath).
    ccd = os.environ.get("CLAUDE_CONFIG_DIR")
    if ccd:
        user_config = os.path.join(ccd, ".claude.json")
    else:
        user_config = os.path.join(os.path.expanduser("~"), ".claude.json")
    try:
        with open(user_config, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        # Missing, unreadable, or malformed: nothing to learn from, degrade quietly.
        return ""

    # Gather every claude-buddy MCP entry: the global one buddy writes, plus any
    # per-project blocks just in case. First entry that resolves to a real, runnable
    # script wins.
    entries = []
    top = (data.get("mcpServers") or {}).get("claude-buddy")
    if isinstance(top, dict):
        entries.append(top)
    for block in (data.get("projects") or {}).values():
        if isinstance(block, dict):
            per_project = (block.get("mcpServers") or {}).get("claude-buddy")
            if isinstance(per_project, dict):
                entries.append(per_project)

    for entry in entries:
        # Prefer cwd (the clone root). Otherwise derive the root from the server
        # entrypoint in args, e.g. <root>/server/index.ts -> <root>.
        roots = []
        cwd = entry.get("cwd")
        if isinstance(cwd, str):
            roots.append(cwd)
        for arg in entry.get("args") or []:
            if isinstance(arg, str) and os.path.basename(arg) in ("index.ts", "index.js"):
                roots.append(os.path.dirname(os.path.dirname(arg)))
        for root in roots:
            hit = _runnable_buddy_status(root)
            if hit:
                return hit
    return ""


def find_buddy_script():
    # Locate claude-buddy's status script (optional). buddy is Linux/macOS only,
    # so on Windows the renderer cleanly falls back to the single line.
    #
    # 1) Explicit override: power users and tests pin an exact path.
    override = os.environ.get("BUDDY_STATUS_SCRIPT")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override

    # buddy doesn't support Windows. Skip auto-discovery there: nothing to find,
    # and this avoids reading Claude's user config on every one-second refresh.
    if os.name == "nt":
        return ""

    home = os.path.expanduser("~")
    # Honour multi-profile installs: buddy resolves paths against CLAUDE_CONFIG_DIR.
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")

    # 2) Fixed, well-known locations (the cheap fast path: no file is parsed).
    fixed = [
        os.path.join(cfg, "buddy-state", "statusline", "buddy-status.sh"),
        os.path.join(home, ".claude-buddy", "statusline", "buddy-status.sh"),
        os.path.join(home, "claude-buddy", "statusline", "buddy-status.sh"),
        os.path.join(cfg, "skills", "buddy", "statusline", "buddy-status.sh"),
    ]
    for candidate in fixed:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # 3) Plugin install directories (path is version-stamped, so we glob).
    for pattern in (
        os.path.join(cfg, "plugins", "*", "claude-buddy", "statusline", "buddy-status.sh"),
        os.path.join(cfg, "plugins", "*", "statusline", "buddy-status.sh"),
    ):
        for candidate in glob.glob(pattern):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    # 4) Ask buddy where it lives: its MCP registration in Claude's user config
    #    records the install root, so we find it even in a non-standard clone dir.
    from_registration = buddy_script_from_registration()
    if from_registration:
        return from_registration

    # 5) Last resort: anything named buddy-status.sh on PATH.
    found = shutil.which("buddy-status.sh")
    if found:
        return found
    return ""


def run_buddy():
    # Run the buddy status script (if any) and capture its art. buddy reads its
    # own state files; it does not consume our stdin, so we hand it /dev/null.
    # Any failure (missing, not executable, errored) degrades to no art.
    script = find_buddy_script()
    if not script:
        return ""
    try:
        return subprocess.run(
            [script], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, creationflags=_NO_WINDOW).stdout
    except Exception:
        return ""


# Built-in safety net, used ONLY if the schema file is missing or unreadable,
# so the status line still renders. The real defaults and types live in
# claude-statusline.schema.json (the single source of truth); this just mirrors
# them as a last resort. Settings are grouped by stat: one group per segment,
# holding that segment's own 'enable' toggle plus any extra options (display
# mode, progress bar, and the token thresholds where context turns yellow / red).
SAFETY_NET = {
    "workspace": {"enable": True},
    "branch": {"enable": True, "dirty": True},
    "diff": {"enable": True},
    "model": {"enable": True, "effort": True},
    "cost": {"enable": False},
    "context": {
        "enable": True,
        "display": "percent",
        "progress_bar": True,
        "yellow": 200000,
        "red": 250000,
    },
    "five_hour": {"enable": True, "burn_rate": True},
    "seven_day": {"enable": True, "burn_rate": True},
}


def schema_defaults(schema_path):
    # Build the default config from the schema's 'default' values. Falls back to
    # the safety net if the schema can't be read or is empty.
    try:
        with open(schema_path) as f:
            schema = json.load(f)
        defaults = {}
        for group_key, group in schema.get("groups", {}).items():
            section = {}
            for child_key, node in group.get("children", {}).items():
                section[child_key] = node.get("default")
            defaults[group_key] = section
        return defaults if defaults else json.loads(json.dumps(SAFETY_NET))
    except Exception:
        return json.loads(json.dumps(SAFETY_NET))


def load_config(path, defaults):
    # Start from the schema defaults, shallow-merge each section of the user's
    # file over them so partial / older config files keep working. A missing
    # file is created EMPTY ({}); the file holds only the keys the user has
    # overridden, so a future change to a schema default still reaches users who
    # never touched that setting (the engine writes the same sparse shape).
    cfg = json.loads(json.dumps(defaults))
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                user = json.load(f)
            for section in cfg:
                if isinstance(user.get(section), dict):
                    cfg[section].update(user[section])
        except Exception:
            pass
    elif path:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w") as f:
                json.dump({}, f, indent=2)
                f.write("\n")
        except Exception:
            pass
    return cfg


def cfg_int(d, key, default):
    # Tolerate non-numeric values someone may have hand-typed into the config.
    try:
        return int(d.get(key, default))
    except (TypeError, ValueError):
        return default


def resolve_schema_path():
    # STATUSLINE_SCHEMA wins (tests / unusual installs); otherwise the copy that
    # sits next to this script (the installer copies it alongside).
    explicit = os.environ.get("STATUSLINE_SCHEMA")
    if explicit:
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "claude-statusline.schema.json")


def resolve_config_path():
    # STATUSLINE_CONFIG wins; otherwise it sits in the active Claude profile.
    explicit = os.environ.get("STATUSLINE_CONFIG")
    if explicit:
        return explicit
    cfg_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(cfg_dir, "claude-statusline.config.json")


def main():
    # Claude Code's JSON arrives on stdin. INPUT_JSON is honoured as a fallback
    # so the renderer stays easy to drive directly in tests.
    raw_stdin = sys.stdin.read()
    try:
        data = json.loads(os.environ.get("INPUT_JSON") or raw_stdin)
    except Exception:
        data = {}

    defaults = schema_defaults(resolve_schema_path())
    cfg = load_config(resolve_config_path(), defaults)
    # Settings are grouped by stat; each segment reads its own group below.
    ws_cfg = cfg.get("workspace", {})
    br_cfg = cfg.get("branch", {})
    diff_cfg = cfg.get("diff", {})
    md_cfg = cfg.get("model", {})
    cost_cfg = cfg.get("cost", {})
    ctx_cfg = cfg.get("context", {})
    fh_cfg = cfg.get("five_hour", {})
    sd_cfg = cfg.get("seven_day", {})

    # Normalise Windows '\' to '/' so path display and the "last two components"
    # split below behave the same on every platform.
    home = os.path.expanduser("~").replace("\\", "/")
    cwd = ((data.get("workspace") or {}).get("current_dir") or data.get("cwd", "") or "").replace("\\", "/")
    if home and cwd.startswith(home):
        cwd_short = cwd.replace(home, "~", 1)
    elif home and os.name == "nt" and cwd.lower().startswith(home.lower()):
        # Windows paths are case-insensitive; match the home prefix regardless.
        cwd_short = "~" + cwd[len(home):]
    else:
        cwd_short = cwd

    model = (data.get("model") or {}).get("display_name", "")
    # Plain slice instead of str.removeprefix so we don't silently require Python 3.9+.
    model_short = model[len("Claude "):] if model.startswith("Claude ") else model
    # Drop the window-size note from the model name, since the context segment below
    # already shows it (e.g. 'ctx 1M'), so 'Opus 4.8 (1M context)' -> 'Opus 4.8'.
    paren = model_short.find(" (")
    if paren != -1 and model_short.rstrip().endswith("context)"):
        model_short = model_short[:paren].rstrip()

    # Current reasoning effort (low/medium/high/xhigh/max). Absent when the active
    # model has no effort parameter; in that case we simply skip the segment.
    effort = (data.get("effort") or {}).get("level", "") or ""

    ctx = data.get("context_window") or {}
    ctx_pct = num(ctx.get("used_percentage"))
    ctx_size = num(ctx.get("context_window_size"))

    rl = data.get("rate_limits") or {}
    fh = rl.get("five_hour") or {}
    sd = rl.get("seven_day") or {}

    # Session spend + line changes (Claude Code reports both under 'cost').
    cost_data = data.get("cost") or {}
    cost = num(cost_data.get("total_cost_usd"))
    if cost is None:
        cost = 0.0
    lines_added = int(num(cost_data.get("total_lines_added")) or 0)
    lines_removed = int(num(cost_data.get("total_lines_removed")) or 0)

    # Branch + dirty state (cached; see git_info). Skip the git work entirely when
    # neither the branch nor the dirty marker is shown.
    branch, dirty = "", False
    if cwd and (br_cfg.get("enable", True) or br_cfg.get("dirty", True)):
        branch, dirty = git_info(cwd)

    # Each info segment is (ansi_text, visual_width). visual_width excludes the
    # zero-width ANSI escapes, so we can right-align against the buddy art by hand.
    info = []

    if ws_cfg.get("enable", True) and cwd_short:
        # Keep only the last two path components to stay compact.
        parts = cwd_short.split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else cwd_short
        info.append((f"{BOLD}{short}{RST}", len(short)))

    # Repo line: branch glyph + name (+ dirty '*') + session line diff, grouped so
    # they read as one unit, e.g. '⎇ main* +12/-3'. The diff comes from the session
    # (not git), so it can still appear on its own when there is no branch.
    repo_bits = []
    repo_w = 0
    if br_cfg.get("enable", True) and branch:
        mark, mark_w = "", 0
        if br_cfg.get("dirty", True) and dirty:
            mark, mark_w = f"{YLW}*{RST}", 1
        repo_bits.append(f"{DIM}⎇{RST} {BOLD}{branch}{RST}{mark}")
        repo_w += 2 + len(branch) + mark_w  # '⎇ ' occupies two columns
    if diff_cfg.get("enable", True) and (lines_added or lines_removed):
        repo_bits.append(f"{GRN}+{lines_added}{RST}/{RED}-{lines_removed}{RST}")
        repo_w += 3 + len(str(lines_added)) + len(str(lines_removed))  # '+N/-M'
    if repo_bits:
        info.append((" ".join(repo_bits), repo_w + (len(repo_bits) - 1)))

    # Model line: model name, reasoning effort, session cost, joined by ' | '. Each
    # entry is collected as (text, visual_width) so the ' | ' separators (3 columns
    # each) are counted once, in one place, rather than threaded through every if.
    meta = []
    if md_cfg.get("enable", True) and model_short:
        meta.append((model_short, len(model_short)))
    if md_cfg.get("effort", True) and effort:
        # 'max effort': the level in normal weight, the word 'effort' dimmed to match
        # the 'ctx' / '5h' / '7d' labels elsewhere.
        meta.append((f"{effort} {DIM}effort{RST}", len(effort) + 1 + len("effort")))
    if cost_cfg.get("enable", False) and cost is not None:
        # Running session spend in USD, coloured like a budget gauge.
        if cost >= 10:
            cc = RED
        elif cost >= 5:
            cc = YLW
        elif cost > 0:
            cc = GRN
        else:
            cc = DIM
        cs = f"{cost:.2f}"
        meta.append((f"{cc}{DOLLAR}{cs}{RST}", 1 + len(cs)))  # '$' + digits
    if meta:
        sep = f" {DIM}|{RST} "
        text = sep.join(t for t, _w in meta)
        width = sum(w for _t, w in meta) + 3 * (len(meta) - 1)  # ' | ' is 3 columns
        info.append((text, width))

    if ctx_cfg.get("enable", True) and ctx_pct is not None:
        p = int(round(ctx_pct))
        used = ctx_pct * int(ctx_size) / 100 if ctx_size else None
        if used is not None:
            # Colour by absolute tokens used, against the configured thresholds.
            if used >= cfg_int(ctx_cfg, "red", 250000):
                c = RED
            elif used >= cfg_int(ctx_cfg, "yellow", 200000):
                c = YLW
            else:
                c = GRN
        else:
            # No window size reported, so fall back to a percentage traffic light.
            c = cpct(p)
        # Value text per display mode. 'tokens' / 'both' need the absolute token
        # count, so they fall back to plain percent when no window size is known.
        mode = ctx_cfg.get("display", "percent")
        if mode == "tokens" and used:
            value = fmtsz(used)
        elif mode == "both" and used:
            value = f"{p}% {fmtsz(used)}"
        else:
            value = f"{p}%"
        sl = fmtsz(ctx_size)
        sp = f" {sl}" if sl else ""
        if ctx_cfg.get("progress_bar", True):
            # The bar carries the threshold colour; the value stays plain.
            head = f"{c}[{bar(p)}]{RST} {value}"
            bar_w = 1 + 10 + 1 + 1  # '[' + bar(10) + ']' + ' '
        else:
            # No bar to colour, so the value itself carries the colour signal.
            head = f"{c}{value}{RST}"
            bar_w = 0
        text = f"{head} {DIM}ctx{sp}{RST}"
        vw = bar_w + len(value) + 1 + 3 + len(sp)  # value + ' ' + 'ctx' + sp
        info.append((text, vw))

    fh_pct = num(fh.get("used_percentage"))
    if fh_cfg.get("enable", True) and fh_pct is not None:
        p = int(round(fh_pct))
        c = cpct(p)
        rs = fmtrst(fh.get("resets_at"), 18000)
        br = burn(fh_pct, fh.get("resets_at"), 18000) if fh_cfg.get("burn_rate", True) else ""
        ps = str(p)
        text = f"{DIM}5h{RST} {c}{ps}%{RST}"
        vw = 4 + len(ps)  # '5h ' + digits + '%'
        if rs:
            text += f" {rs}"
            vw += 1 + len(rs)
        if br:
            # The flag sits after the reset time, e.g. '5h 40% 4.5h 🔴'. The emoji
            # renders two columns wide, so it counts as 2 (plus its leading space).
            text += f" {br}"
            vw += 1 + 2
        info.append((text, vw))

    sd_pct = num(sd.get("used_percentage"))
    if sd_cfg.get("enable", True) and sd_pct is not None:
        p = int(round(sd_pct))
        c = cpct(p)
        rs = fmtrst(sd.get("resets_at"), 604800)
        br = burn(sd_pct, sd.get("resets_at"), 604800) if sd_cfg.get("burn_rate", True) else ""
        ps = str(p)
        text = f"{DIM}7d{RST} {c}{ps}%{RST}"
        vw = 4 + len(ps)  # '7d ' + digits + '%'
        if rs:
            text += f" {rs}"
            vw += 1 + len(rs)
        if br:
            # Same flag as the 5h window: after the reset time, two-column emoji.
            text += f" {br}"
            vw += 1 + 2
        info.append((text, vw))

    # buddy art (Linux/macOS only; empty on Windows -> single line below).
    buddy_output = run_buddy()
    buddy_lines = buddy_output.splitlines() if buddy_output.strip() else []

    # No buddy: single-line status.
    if not buddy_lines:
        print(f"  {DIM}|{RST}  ".join(text for text, _w in info))
        return

    # Buddy present: weave each info segment into a padded art line.
    # We only touch lines that start with the braille blank AND have enough blank
    # space to fit the segment without disturbing the right-aligned art. For each
    # blank line we place the first *still-pending* segment that fits, rather than
    # only the next one in order, so a wide segment (e.g. context) that can't fit a
    # narrow margin doesn't block the narrower trailing segments (5h / 7d) behind it.
    pending = list(info)
    out = []
    for line in buddy_lines:
        placed = False
        if pending and line.startswith(BRAILLE):
            after = line[1:]
            stripped = after.lstrip(" ")
            spaces = len(after) - len(stripped)
            for idx, (txt, vw) in enumerate(pending):
                if spaces >= vw + 2:
                    pad = " " * (spaces - vw)
                    out.append(BRAILLE + txt + pad + stripped)
                    pending.pop(idx)
                    placed = True
                    break
        if not placed:
            out.append(line)

    print("\n".join(out))


if __name__ == "__main__":
    main()
