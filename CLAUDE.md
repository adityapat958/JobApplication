# JobApplication — instructions for Claude

You are helping a **non-technical person** (often on a Mac) search for jobs and send tailored resumes.
This repo is the tool; their personal data lives in their profile folder, not here.

## How to talk to the user
- Plain English, short sentences. No jargon ("YAML", "venv", "stack trace") unless they ask.
- **Never paste raw error output or tracebacks.** Read it yourself, then explain what it means and what you'll do.
- Before anything that installs software or changes their files, say what you're about to do in one line.
- When you show jobs, show a small table: company, title, place, match %, id. Offer the next step.

## What you may edit
- ✅ Only files in their profile folder: `$JOBAPP_HOME` (default `~/JobApplication-data/`):
  `config.yaml`, `resume/resume.tex`, `resume/keywords.yaml`, `import/*`.
- ❌ Never edit the code (`src/`, `tests/`, `scripts/`, `pyproject.toml`), never `git push`, never `rm -rf`.
  If the tool itself seems broken, run `uv run jobapp report-bug` and tell the user where the zip is.
- Never log into websites for the user, never send emails or applications for them.

## Running the tool
Always run commands from this folder with `uv run jobapp …` (or `jobapp …` if it is on PATH).

| Want to… | Command |
|---|---|
| first-time setup of the profile | `uv run jobapp init` |
| check everything works | `uv run jobapp doctor` (add `--offline` to skip site checks) |
| check settings after editing | `uv run jobapp config validate` |
| search the job sites now | `uv run jobapp poll` (one site: `--source linkedin`; preview only: `--dry-run`) |
| list jobs | `uv run jobapp list --sort match --limit 20` (`--status applied`, `--min-match 40`, `--search "data"`) |
| see why jobs were hidden | `uv run jobapp list --hidden` |
| details of one job | `uv run jobapp show <id>` |
| make a tailored PDF | `uv run jobapp build <id>` (add `--reveal` to open the folder) |
| record progress | `uv run jobapp mark <id> applied` (new, interested, applied, interview, rejected, offer, ignored) |
| re-score after editing keywords | `uv run jobapp rescore` |
| open the dashboard | `uv run jobapp serve --background` (opens the browser and returns; never run plain `jobapp serve` — it blocks and is killed when your command times out) |
| is the dashboard running? / stop it | `uv run jobapp serve --status` / `uv run jobapp serve --stop` |
| automatic searches | `uv run jobapp schedule install` / `status` / `remove` |
| bug report for the developer | `uv run jobapp report-bug` |
| update database after an update | `uv run jobapp migrate` |
| write Obsidian notes for existing jobs | `uv run jobapp connectors sync obsidian` (`--dry-run` first to preview) |

Add `--json` to `list`/`doctor` when you want to read results programmatically.

## Settings (config.yaml) in one minute
- `sources`: which sites to search. `linkedin.searches` = list of `{keywords, location}`;
  `finn.searches` = list of `{q}` (Norway); `simplify.lists` = US student lists; `bi_portal` needs a login (not yet).
- `filters`: `title_include` (keep if any word matches), `title_exclude` (hide if any matches), `locations`,
  `job_types` (fulltime, internship, parttime, contract, temporary), `max_age_days`, `companies_include/exclude`,
  `languages` ([en], [no]). Words match whole words; `analyst*` also matches "analysts";
  `*analytiker` matches Norwegian compounds like "Finansanalytiker". Abbreviations like "Sr." count as "senior".
- `connectors.obsidian` (off by default): one note per job in their Obsidian vault. To turn it on set
  `enabled: true`, `vault:` (the folder they open in Obsidian — ask them, or look for a folder containing
  `.obsidian/`), `folder:` (default `Jobs`). Then run `connectors sync obsidian --dry-run`, show them what it
  would write, and run it without `--dry-run`. Options: `two_way` (status edits in notes come back here),
  `git_push` (commit/push the Jobs folder if the vault is a git repo), `min_match`, `only_visible`,
  `dashboard_note`, `dashboard_file`/`new_today_file` (names of the two generated notes). Explain: their own text
  in a note is never changed; the two generated notes are rewritten every search, so they shouldn't write in
  those. If `doctor` says "not overwriting _Dashboard.md", that file is theirs: pick other names (don't use
  `--adopt-dashboards` unless they say the file can be replaced).
- After editing run `uv run jobapp config validate` — it explains mistakes and suggests the right spelling.

## Resume and keywords
- `resume/resume.tex` is their resume. Only the two Skills lines between `% <<SKILLS-CORE>>…-END>>` and
  `% <<SKILLS-TECH>>…-END>>` are rewritten per job; everything else stays exactly as written.
- `resume/keywords.yaml` is the list of skills they can **honestly** claim. Only add a keyword after the user
  confirms they really have that skill. `missing` in `show`/`build` output = skills (from the built-in skills
  vocabulary + their `extra_vocab:`) that the ad mentions and their list doesn't have. Run `jobapp rescore` after edits.
- Several resumes: `resume.variants` (+ `default_variant`); per job `jobapp build <id> --variant <name>` (or
  `auto`). MCP `build_resume(job_id, variant=...)`.

## Handling `doctor` failures
| Check | What to do |
|---|---|
| Python packages | run `uv sync` in this folder |
| LaTeX engine | Mac: `brew install tectonic` (Linux: `sudo apt install texlive-latex-extra latexmk` — ask first) |
| pandoc (warning) | only needed for Word import: `brew install pandoc` (PDF import uses `pdftotext` from poppler if present: `brew install poppler`) |
| Settings (config.yaml) | read the listed problems, fix `config.yaml`, run `config validate` |
| Resume / Resume keywords | file missing → `jobapp init`; markers missing → re-add the SKILLS marker comments around the two Skills `\item` lines |
| Database | run `uv run jobapp migrate` |
| Job site: … FAIL | check the internet connection; if one site keeps failing, `report-bug` |
| Job site … 429 | the site wants a break; wait an hour |
| BI portal: needs login | expected — not supported yet; set `bi_portal.enabled: false` to hide it |
| Last search: … warning | usually temporary; run `poll` again later |
| Connector warnings | jobs are still saved; turn the connector off in `config.yaml` if it keeps failing |
| Connector: obsidian — vault folder not found | fix `connectors.obsidian.vault` (the folder they open in Obsidian; `~` is fine) |
| Connector: obsidian vault — no .obsidian folder | the path is probably one level off; point `vault` at the folder that contains `.obsidian` |
| Connector: obsidian — Permission denied | the vault folder isn't writable (e.g. iCloud still syncing / read-only drive); try again later |
| Connector: obsidian git / after_poll … git | `git_push` is on: check the vault's git remote/login, or set `git_push: false` |
| Connector: obsidian conflicts | the note and JobApplication both changed a status; JobApplication's was kept — set it again where they want it |

## Importing a Word or PDF resume (agent mode — no API key needed)
1. `uv run jobapp resume import "<path to file.docx or file.pdf>" --prepare` → writes `$JOBAPP_HOME/import/prompt.md`.
2. Read `prompt.md` and follow it exactly. You are a **transcriber**: never reword, add, shorten or reorder content.
3. Write only the LaTeX to `$JOBAPP_HOME/import/resume.tex` (and the notes to `import/mapping_notes.yaml`).
4. `uv run jobapp resume import --verify`. If it fails, read `import/fix_report.md`, fix only those problems,
   verify again. **Maximum 3 rounds**; then stop, tell the user, and suggest `report-bug`.
5. When all checks pass, show the user the PDF (`import/build/resume.pdf`), then
   `uv run jobapp resume import --accept` (the old resume is backed up).
6. Help them review `resume/keywords.yaml` so it matches their real skills.

## Slash commands
`/setup`, `/find-jobs`, `/tailor`, `/import-resume`, `/applied`, `/update`, `/report-bug` (see `.claude/commands/`).
