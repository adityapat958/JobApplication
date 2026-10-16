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
| `db/` | SQLite (WAL). Numbered migrations in `db/migrations/NNN_*.sql`, tracked with `PRAGMA user_version`. FTS5 on company/title/description. |
| `models.py` | `JobPosting` dataclass; job id = first 10 hex of sha1(`source|source_id`). |
| `http.py` | Polite client: browser UA, ≥2 s per host, retry/backoff on 429/5xx, URL guards (robots rules). |
| `sources/` | One module per site + registry (`sources/__init__.py`). See ADDING_A_SOURCE.md. |
| `filters.py` | Pure `apply_filters(job, filters) -> (keep, reason)`. |
| `poll.py` | Orchestration: fetch → filter → upsert → JD for kept jobs → re-filter → score → connectors. |
| `resume/keywords.py` | Keyword bank loader/validator. |
| `resume/matching.py` | JD ↔ bank matching, `missing` terms, `match_pct`. |
| `resume/build.py` | Rewrites only the first `\item` between the SKILLS markers; byte-identical elsewhere. |
| `resume/service.py` | Build a PDF for a job, file naming, page-count warning, `builds` table. |
| `resume/docx_import.py` | Word → LaTeX: extraction, prompt rendering, verification gates, API loop. |
| `web/` | Dashboard (FastAPI + one HTML page). POSTs need `X-JobApp: 1`; Host must be localhost. |
| `agent/` | MCP tools (plain functions) + the MCP server wrapper. |
| `connectors/` | `Connector` protocol; `NullConnector`, `jsonl` reference. Failures logged, never fatal. |
| `schedule.py`, `platform.py`, `secrets.py` | launchd/cron, Finder reveal, Keychain/.env. |
| `doctor.py`, `bugreport.py` | Health checks with hints; redacted bug-report zip. |

## Data rules
- Re-polling refreshes listing fields (title, company, location, URLs, dates, raw) but never `status`, `done`,
  `notes`, or a description the user saved by hand (`jd_saved_at`).
- Jobs the user is tracking (status ≠ `new`) are never hidden by filters.
- After a full poll every saved job is re-filtered, so changing filters takes effect immediately.
- Personal data lives only under `JOBAPP_HOME`; `scripts/privacy_scan.sh` (run by the tests) keeps the repo clean.

## Matching
`match_pct = matched / max(matched + missing, 6)`. `matched` = bank keywords (or aliases) found in the JD,
word-boundary, accent/hyphen-insensitive, plural-tolerant. `missing` = Title-Case/ACRONYM/CamelCase runs in the
JD that aren't in the bank (minus company, places, stopwords). No JD → `match_pct` NULL ("manual JD").

## Tailoring
Order per Skills line: JD-matched keywords → the user's original picks → rest of that bank section, until the
original line's character budget (+5%) is used. This keeps the line count, so page count usually stays the same;
`build` warns if it doesn't.
