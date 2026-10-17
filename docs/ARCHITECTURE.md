# Architecture

```
            config.yaml (pydantic)                    keywords.yaml        resume.tex
                   │                                        │                  │
 sources/*  ──fetch──► poll.py ──apply_filters──► db (SQLite) ◄──score── resume/matching.py
 (simplify,           │    │                        │   ▲                       │
  linkedin,           │    └─fetch JD (kept jobs)───┘   │                resume/build.py (marker rewrite)
  finn, bi_portal)    │                                 │                       │
                      └─► connectors (jsonl, …)         │                resume/tex.py (tectonic/latexmk/pdflatex)
                                                        │                       │
            cli.py (typer) ── web/server.py (FastAPI) ── agent/tools.py ── agent/mcp_server.py (stdio)
```

## Layout
| Path | What |
|---|---|
| `src/jobapp/cli.py` | Every command. Catches all errors; tracebacks go to `logs/jobapp.log` only. |
| `config.py` | pydantic v2 models for `config.yaml` (`extra=forbid`) + friendly "did you mean" errors. |
| `paths.py` | `JOBAPP_HOME` (default `~/JobApplication-data`), bundled examples/prompts lookup. |
| `db/` | SQLite (WAL). Numbered migrations in `db/migrations/NNN_*.sql`, tracked with `PRAGMA user_version`; `_post_migrate` runs Python data steps inside a migration's transaction. FTS5 on company/title/description. |
| `models.py` | `JobPosting` dataclass; job id = first 10 hex of sha1(`source|source_id`). |
| `http.py` | Polite client: browser UA, ≥2 s per host, retry/backoff on 429/5xx, URL guards (robots rules). |
| `sources/` | One module per site + registry (`sources/__init__.py`). See ADDING_A_SOURCE.md. |
| `filters.py` | Pure `apply_filters(job, filters) -> (keep, reason)`. |
| `poll.py` | Orchestration: connectors `pull_all` (two-way) → fetch → filter → upsert → JD for kept jobs → re-filter → score → connectors (`notify_added`, then `after_poll`). |
| `resume/keywords.py` | Keyword bank loader/validator. |
| `resume/matching.py` | JD ↔ bank matching, `missing` terms, `match_pct`. |
| `resume/build.py` | Rewrites only the first `\item` between the SKILLS markers; byte-identical elsewhere. |
| `resume/service.py` | Build a PDF for a job, file naming, page-count warning, `builds` table. |
| `resume/docx_import.py` | Word → LaTeX: extraction, prompt rendering, verification gates, API loop. |
| `web/` | Dashboard (FastAPI + one HTML page). POSTs need `X-JobApp: 1`; Host must be localhost. |
| `agent/` | MCP tools (plain functions) + the MCP server wrapper. |
| `connectors/` | `Connector` protocol; `NullConnector`, `jsonl` reference, `obsidian`. Failures go to `logs/connector_errors.json` (shown by `doctor`), never fatal. Optional hooks: `pull` (+ `two_way`), `after_poll(conn)`, `doctor()`. State (last sync, conflicts) in `logs/connector_state.json`. |
| `connectors/obsidian.py` | One note per job (`Company — Title.md`, layout of the old hand-made notes + `job_id`, `match`, `matched`, `missing`, `url`, `also_on`). Notes found by frontmatter `job_id`, else file name (older notes without id are adopted, their status taken over once by `sync`). Updates touch only managed keys + the "Applied" box (semantic compare, so Obsidian's YAML style never causes rewrites); atomic writes. `_Dashboard.md`/`_New Today.md` (names configurable) regenerated — an existing file without the generated header (and not the old exporter's dashboard) is never overwritten (connector error; `--adopt-dashboards`); optional git commit/push of the folder. Two-way: note status/box → DB via `db.mark` only if the note's mtime is newer than `jobs.status_updated_at`; otherwise DB wins and the conflict is recorded. |
| `schedule.py`, `platform.py`, `secrets.py` | launchd/cron, Finder reveal, Keychain/.env. |
| `doctor.py`, `bugreport.py` | Health checks with hints; redacted bug-report zip. |

## Data rules
- Re-polling refreshes listing fields (title, company, location, URLs, dates, raw) but never `status`, `done`,
  `notes`, or a description the user saved by hand (`jd_saved_at`).
- Jobs the user is tracking (status ≠ `new`) are never hidden by filters.
- After a full poll every saved job is re-filtered, so changing filters takes effect immediately.
- `status_updated_at` (migration 003) moves only when the status really changes (`db.set_status`); two-way
  connectors compare it with a note's modification time. `db.mark` = set status + un-hide a tracked job (CLI,
  dashboard, MCP and connector pulls all use it).
- Personal data lives only under `JOBAPP_HOME`; `scripts/privacy_scan.sh` (run by the tests) keeps the repo clean.

## Matching
`match_pct = matched / max(matched + missing, 6)`. `matched` = bank keywords (or aliases, or skills-vocabulary
aliases of a bank keyword — e.g. "maskinlæring" → "Machine Learning") found in the JD, word-boundary,
accent/hyphen-insensitive, plural-tolerant. `missing` = terms of the curated skills vocabulary
(`resume/skills_vocab.yaml`, groups of `Term: [aliases]`, `=Term` = case-sensitive; + `extra_vocab:` in
keywords.yaml, `resume/vocab.py`) that the JD mentions and the bank doesn't cover (a term is covered when it or an
alias equals a bank keyword/alias, or is a phrase inside one: "Object Detection" ⊂ "Object Detection and
Tracking"). Before matching (`matching.clean_jd`): `text.strip_contact` removes contact / "Meet the hiring team" /
"please contact" blocks and the people named there; `text.strip_boilerplate` drops About us / Om oss / Vi tilbyr /
benefits / EEO / LinkedIn page-chrome sections (until the next heading, max two paragraphs), EEO/benefit/funding
sentences, URLs, e-mails and phone numbers. No JD → `match_pct` NULL ("manual JD"). `jobapp rescore` /
`resume.rescore.rescore_all` recompute everything (migration 004 does it once for the active profile).

Resume variants (`resume/variants.py`): `resume.variants` {name: tex, keywords, prefer_if}; per job
`jobs.variant` (user's choice, migration 004) → else most `prefer_if` hits in the title, then in the JD (ties →
`default_variant`) → else `default_variant`. The `Matcher` scores each job with its variant's bank; the build
uses its variant's .tex.

Sort by match = `match_pct` desc → `title_score` desc → posted desc. `title_score` (`filters.title_score`) = weight
of the best `title_include` term the title hits: words + length (specific multi-word terms win); generic terms
(graduate, trainee, junior, intern*) weigh 0.25.

## Importing from the older tracker (`migrate_mongo.py`)
Old `jobdesk.jobs` documents → rows (read-only on Mongo; one transaction; `--dry-run` rolls back). LinkedIn →
`source_id` = the LinkedIn job id (a poll computes the same `id`); Simplify without a `simplify.jobs/p/<id>` link →
`legacy:<old id>` + `legacy_url_key` (normalised apply link). `db.find_existing` (used by poll/upsert) adopts such
a row on the first poll that lists the same link (by title when one link has several imported jobs; else the only
imported row with the same company+title+location) and gives it the new `source_id`. Kept: status, done/done_at,
JD (+ `jd_saved_at` if hand-saved), variant, `date_found` → `first_seen_at` (midday UTC), tier (in `raw`), old id
(`legacy_id`), note path (`note_path`). Old documents of one listing (same LinkedIn id, or same link+place+title)
become one row. Rows already imported are never changed (rerun = 0 changes). Then dedupe, re-filter, re-score.
The Obsidian connector gives an imported job exactly its old note (the stored path, mapped below the configured
jobs folder if the vault moved/was copied — never a path outside it) and never creates a second note for it.

## Cross-source duplicates
`db/dedupe.py`: `dedupe_key` = normalised company (no AS/ASA/AB/Inc/Ltd/LLC/GmbH/Norge/Norway/Bank/Group,
punctuation) + `|` + normalised title (no (m/f/d)-style tags, punctuation). Rows with the same key from different
sources whose posted (else first-seen) dates are within 45 days form a group: the primary is the one the user tracks
(status ≠ new or notes), else not filter-hidden, else with a description, else seen first. The others get
`duplicate_of` = primary (kept for their URL, hidden from list/dashboard/MCP, shown as `also_on`). Only
`duplicate_of` is written; recomputed on insert/update/status/notes/hidden. Migration 002 runs it once.

## Tailoring
Order per Skills line: JD-matched keywords → the user's original picks → rest of that bank section, until the
original line's character budget (+5%) is used. This keeps the line count, so page count usually stays the same;
`build` warns if it doesn't.
