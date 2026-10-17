---
description: First-time setup on this computer (install tools, create the profile, choose jobs to look for)
---
Set up JobApplication for the user, step by step. Explain each step in one plain sentence before doing it,
and wait for "ok" before installing anything. Never show raw error output — summarise it.

1. **Detect the computer**: run `uname -s`. On macOS ("Darwin") follow the Mac steps; on Linux use the package
   manager the user already has (ask before any `sudo`).
2. **Homebrew (Mac)**: check `command -v brew`. If missing, tell the user you'll install Homebrew (it asks for
   their Mac password in the Terminal — that's normal) and run the official command from https://brew.sh :
   `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`.
   Afterwards follow the "Next steps" it prints to add brew to the PATH.
3. **uv** (runs the Python app): `command -v uv || brew install uv` (Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`).
4. **tectonic** (makes the PDFs): `command -v tectonic || brew install tectonic`.
5. **pandoc** (only for importing a Word resume): `command -v pandoc || brew install pandoc`.
6. **Install the app**: in this folder run `uv sync`.
7. **Create the profile**: `uv run jobapp init`. Tell them where it is (default `~/JobApplication-data`).
8. **Ask the user** (one question at a time, give examples):
   - What kind of jobs? (job titles / words, e.g. "business analyst, consultant, trainee")
   - Which words should hide a job? (e.g. "senior, manager, lead")
   - Where? (cities/countries; "Remote" is fine)
   - Full-time, internship, part-time?
   - Which sites? LinkedIn (everywhere), FINN.no (Norway), Simplify lists (US students), BI portal (not yet).
   - Their full name as it should appear in PDF file names.
9. **Write `config.yaml`** in the profile folder from their answers (LinkedIn `searches` with keywords +
   location; FINN `searches` with `q`). For Norwegian titles add `*` forms, e.g. `"*analytiker"`, `"*konsulent"`.
   Run `uv run jobapp config validate` and fix anything it reports.
10. **Obsidian (optional)**: ask "Do you use Obsidian for notes?" If yes, find their vault (ask, or look for a
    folder containing `.obsidian/`, e.g. under `~/Documents`), then set `connectors.obsidian.enabled: true`,
    `vault:` and `folder: Jobs` in `config.yaml`, run `uv run jobapp config validate`, then
    `uv run jobapp connectors sync obsidian --dry-run` and, after they say ok, without `--dry-run`. Ask whether
    they want status changes made in a note to come back here (`two_way: true`). If no, leave it off.
11. **Resume**: ask if they have a Word or PDF resume. If yes, run `/import-resume`. If not, explain the example resume
    at `resume/resume.tex` is a placeholder they should replace later.
12. **Check**: `uv run jobapp doctor`. Fix failures using the table in CLAUDE.md.
13. **First search**: offer to run `/find-jobs` now, and `uv run jobapp schedule install` for twice-daily searches.
