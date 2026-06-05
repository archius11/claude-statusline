# Security & privacy

claude-statusline runs entirely on your machine. It makes **no network
requests**, collects **no telemetry**, and sends **no data** anywhere.

It only:

- reads the JSON Claude Code passes on stdin,
- reads your Claude config (`.claude.json`, read-only) to find claude-buddy,
- edits `settings.json` in your Claude config dir (install / uninstall),
- shells out to `git` for the branch, and to claude-buddy when it's present.

Found a security problem (command injection, `settings.json` corruption)? Please
email the maintainer (see the repository profile) rather than opening a public issue.
