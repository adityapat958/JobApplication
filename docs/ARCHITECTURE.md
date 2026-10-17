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
| `connectors/obsidian.py` | One note per job (`Company — Title.md`, layout of the old hand-made notes + `job_id`, `match`, `matched`, `missing`, `url`, `also_on`). Notes found by frontmatter `job_id`, else file name (older notes without id are adopted, their status taken over once by `sync`). Updates touch only managed keys + the "Applied" box (semantic compare, so Obsidian's YAML style never causes rewrites); atomic writes. `_Dashboard.md`/`_New Today.md` regenerated; optional git commit/push of the folder. Two-way: note status/box → DB via `db.mark` only if the note's mtime is newer than `jobs.status_updated_at`; otherwise DB wins and the conflict is recorded. |
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
`match_pct = matched / max(matched + missing, 6)`. `matched` = bank keywords (or aliases) found in the JD,
word-boundary, accent/hyphen-insensitive, plural-tolerant. `missing` = Title-Case/ACRONYM/CamelCase runs in the
JD that aren't in the bank (minus company, places, stopwords). The contact block (Kontaktperson / Contact /
Spørsmål om stillingen, phone and e-mail lines) is removed first (`text.strip_contact`), and the contact
person's name is ignored anywhere in the ad. No JD → `match_pct` NULL ("manual JD").

Sort by match = `match_pct` desc → `title_score` desc → posted desc. `title_score` (`filters.title_score`) = weight
of the best `title_include` term the title hits: words + length (specific multi-word terms win); generic terms
(graduate, trainee, junior, intern*) weigh 0.25.

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
