# Changelog

## v0.1.2
**Obsidian notes (optional, off by default)**
- `connectors.obsidian`: one note per job in your Obsidian vault (`Jobs/Full-Time`, `Jobs/Internships`,
  `Jobs/Part-Time`) with the familiar layout — details table, Apply link, Status checklist, Notes, Why This
  Role — plus `job_id`, `match`, `matched`, `missing`, `url`, `also_on` in the frontmatter.
- Your text is never touched: updates change only the status/match/link fields and the "Applied" tick box;
  other frontmatter keys and their order stay. Notes are found by `job_id`, so you can rename or move them.
  Older notes without `job_id` (same file name) are adopted, and a status like "applied" in them is taken over.
- `_Dashboard.md` (counts by status, top 20 by match) and `_New Today.md` are regenerated after each search.
- `jobapp connectors sync obsidian` writes notes for the jobs you already have (`--dry-run` to preview;
  running it again changes nothing).
- `two_way: true`: a status changed in a note (or ticking "Applied") comes back at the next search, if the note
  is newer than the last change made here; otherwise this app's status wins and `doctor` shows the conflict.
- `git_push: true`: the Jobs folder is committed ("jobs: update DATE") and pushed if the vault is a git repo
  with a remote. Problems are shown by `doctor`; they never stop a search.
- `doctor` shows the vault, number of notes, last sync and last error. `/setup` asks "Do you use Obsidian?".

**Other**
- `jobapp mark` now also un-hides a job you start tracking (same as the dashboard and Claude Desktop).
- Database migration 003: `status_updated_at` (when a job's status last changed).

## v0.1.1
**Resume import from PDF**
- Resume import now accepts a **PDF** as well as a Word file (`jobapp resume import resume.pdf --prepare`):
  text via `pdftotext -layout` (fallback pypdf) turned into headings/bullets, links from the PDF's link
  annotations, page count from the PDF. Scanned (image-only) PDFs are refused with a plain-English message.
- Word-check now handles ligatures (ﬁ ﬂ ﬀ), bullet glyphs and words hyphenated at a line end (only that
  exact split is forgiven, so rewording is still caught).
- Prompt template, CLI help, CLAUDE.md, `/import-resume`, README and MCP tool descriptions say "Word or PDF".
- Word-check reads PDFs with `pdftotext -raw`: the default mode silently glued compounds broken at a line
  end ("fail-" / "closed" → "failclosed") and failed correct imports.
- Prompt: keep the source order of all Skills lines (CORE = first domain line, TECH = broadest tools line,
  other lines unmarked); match the source's paper size (letter/A4).
- Tailoring with several Skills lines: no repeats of keywords already on another Skills line or inside the
  user's own "AWS (ECS, IAM)"-style item; commas inside brackets no longer split an item.

**Real-world fixes (Word resume from an online resume builder)**
- Invisible text in .docx files (hidden runs, white-on-white tracking codes) is dropped before the word check.
- Custom heading styles count for the section order; prompt rules for summaries, spacer paragraphs,
  U+2011 hyphens / subscripts and skills tables.
- Tailored Skills lines are never hyphenated (an ATS reads "statis-"/"tics" as two words).

**Fixes in this release**
- Page check on import passes when the converted resume has the same number of pages **or fewer** than
  the original; it fails only when it has more. The prompt now asks for the template's default spacing,
  never pads spacing to reach the original page count, and only tightens the spacing knobs to stay
  within it.
- The same job on FINN and LinkedIn (or any two sites) is listed once: company names are compared without
  AS/ASA/AB/Inc/Ltd/LLC/GmbH/Norge/Norway/Bank/Group and punctuation, titles without (m/f/d)-style tags.
  The copy stays in the database for its link and shows as "also on: linkedin" on the main entry
  (list, show, dashboard, Claude). The main entry is the one you are tracking, else the one with a job
  description, else the one seen first. Your status, notes and done flags are never changed. Existing
  databases are cleaned up once by migration 2.
- FINN: the company now comes from the ad's employer data (JSON-LD, then "Arbeidsgiver"), then the search
  card; a "company" equal to the job title is rejected.
- "Missing keywords" no longer lists contact people, phone numbers or e-mail lines: the contact section
  (Kontaktperson / Kontakt / Contact / Spørsmål om stillingen) is removed before keywords are extracted,
  and the contact person's name is ignored anywhere in the ad.
- Sorting by match: equal match % is now ordered by how well the title fits your `title_include` words
  (specific multi-word words beat generic ones like graduate/trainee/junior/intern), then newest. Used by
  `jobapp list --sort match`, the dashboard (now sorted by best match by default) and Claude's
  `list_jobs`. `jobapp show` prints the job's `title_score`.
- Privacy: docs use neutral test-user labels; the privacy scan also blocks the test users' names.

## v0.1.0 — first release
- Job sources: LinkedIn (public guest pages), FINN.no, Simplify GitHub lists; BI portal placeholder (needs login, planned).
- Filters with reasons ("why hidden"), whole-word matching, `*` wildcards for Norwegian compound words, Sr./Jr. abbreviations.
- Keyword matching against your own keyword list (aliases, plurals, hyphens, accents) with match % and missing skills.
- Tailored PDF resume per job: only the Skills lines change; page-count check; `First_Last_Company_Role.pdf`.
- Dashboard (`jobapp serve`): filter, sort, status, paste job descriptions, build + download, show in Finder.
- Word resume import with automatic checks (agent mode via Claude, or API mode with your key).
- Claude integration: CLAUDE.md, slash commands, MCP server for Claude Desktop (`jobapp mcp`, `jobapp mcp-config`).
- Automatic searches (launchd on macOS, crontab line on Linux), keychain storage for API keys.
- `jobapp doctor` with fix hints; `jobapp report-bug` with personal details removed.
